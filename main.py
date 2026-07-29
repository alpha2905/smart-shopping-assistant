import logging
import sys
from typing import List, Dict, Any
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
from datetime import datetime

# APScheduler cho tác vụ định kỳ
from apscheduler.schedulers.background import BackgroundScheduler

from utils.browser import BrowserManager
from utils.db import (
    init_db, save_search_results, get_unique_queries, close_db,
    get_product_price_history, get_products_with_price_history,
    save_prediction, get_prediction,
)
from utils.search_filter import filter_comparable_phones
from utils.price_predictor import train_and_predict

# Import 7 scraper
from scrapers.fptshop import FPTShopScraper
from scrapers.didongviet import DiDongVietScraper
from scrapers.clickbuy import ClickbuyScraper
from scrapers.cellphones import CellphoneSScraper
from scrapers.viettelstore import ViettelStoreScraper
from scrapers.hoanghamobile import HoangHaMobileScraper
from scrapers.thegioididong import TheGioiDiDongScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Platform Product Search API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Scheduler chạy ngầm ────────────────────────────────────────────────
scheduler = BackgroundScheduler()


def run_single_scraper(scraper_class, query: str, max_products: int = 5) -> List[Dict[str, Any]]:
    """Hàm chạy từng scraper, có thiết lập riêng event loop cho luồng phụ trên Windows."""
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = scraper_class(browser_manager)
            logger.info(f"Đang cào từ {scraper.site_name} (query='{query}')...")
            products = scraper.search(query=query, max_products=max_products)
            for p in products:
                products_data.append({
                    "name": p.name,
                    "price": p.price,
                    "image_url": p.image_url,
                    "product_url": p.product_url,
                    "source": p.source,
                    "comments": getattr(p, "comments", [])
                })
            logger.info(f"Hoàn thành {scraper.site_name}: {len(products)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi cào từ {scraper_class.__name__}: {e}", exc_info=True)
    return products_data


def scrape_and_save(query: str) -> List[Dict[str, Any]]:
    """Scrape từ tất cả sàn cho 1 query, lưu vào MongoDB, trả về kết quả."""
    scraper_classes = [
        FPTShopScraper,
        DiDongVietScraper,
        ClickbuyScraper,
        CellphoneSScraper,
        ViettelStoreScraper,
        HoangHaMobileScraper,
        TheGioiDiDongScraper,
    ]

    all_products = []
    max_products = 15

    with ThreadPoolExecutor(max_workers=7) as executor:
        future_map = {
            executor.submit(run_single_scraper, sc, query, max_products): sc.__name__
            for sc in scraper_classes
        }

        for future in as_completed(future_map):
            scraper_name = future_map[future]
            try:
                result = future.result()
                if result:
                    all_products.extend(result)
            except Exception as e:
                logger.error(f"Luồng thực thi {scraper_name} gặp sự cố: {e}")

    filtered_products = filter_comparable_phones(all_products, query)
    logger.info(
        f"Lọc kết quả: {len(all_products)} sản phẩm thô → {len(filtered_products)} điện thoại khớp"
    )

    # Lưu vào MongoDB (chỉ sản phẩm đã lọc, có thể so sánh giá)
    if filtered_products:
        save_search_results(query, filtered_products)

    return filtered_products


def scheduled_scrape_all():
    """Chạy mỗi giờ: scrape lại toàn bộ query đã từng được tìm kiếm."""
    logger.info("=== Scheduled scrape: bắt đầu cào lại tất cả query ===")
    try:
        queries = get_unique_queries()
        if not queries:
            logger.info("Chưa có query nào trong DB, bỏ qua scheduled scrape.")
            return
        for q in queries:
            logger.info(f"Scheduled scrape cho query: '{q}'")
            try:
                scrape_and_save(q)
            except Exception as e:
                logger.error(f"Lỗi scheduled scrape query '{q}': {e}", exc_info=True)
        logger.info("=== Scheduled scrape hoàn tất ===")
    except Exception as e:
        logger.error(f"Lỗi scheduled scrape: {e}", exc_info=True)


# ─── Sự kiện vòng đời FastAPI ──────────────────────────────────────────

@app.on_event("startup")
def startup():
    """Khởi tạo DB + scheduler khi app start."""
    # Khởi tạo MongoDB indexes
    init_db()

    # Schedule: scrape mỗi giờ (cả khi không có request nào)
    scheduler.add_job(
        scheduled_scrape_all,
        "interval",
        hours=1,
        id="hourly_scrape",
        replace_existing=True,
        next_run_time=None,  # None = không chạy ngay khi start, đợi đúng giờ
    )
    scheduler.start()
    logger.info("Scheduler started: sẽ scrape lại tất cả query mỗi 1 giờ")


@app.on_event("shutdown")
def shutdown():
    """Dọn dẹp khi app tắt."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    close_db()


# ─── API Endpoint ──────────────────────────────────────────────────────

@app.get("/api/search")
def search_products(q: str = Query(..., description="Từ khóa tìm kiếm sản phẩm")):
    all_products = scrape_and_save(q)

    return {
        "query": q,
        "total": len(all_products),
        "products": all_products
    }


# ─── Price History + LSTM Prediction Endpoints ─────────────────────────

@app.get("/api/products-with-history")
def list_products_with_history():
    """List all products that have enough price history for LSTM prediction."""
    products = get_products_with_price_history(min_history=3)
    return {
        "total": len(products),
        "products": products,
    }


@app.get("/api/price-history")
def get_price_history(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
    force_retrain: bool = Query(False, description="Force retrain LSTM (bypass cache)"),
):
    """
    Get price history + LSTM prediction for a product.

    Strategy for speed:
      1. Check cache first → return instantly if available
      2. If no cache → train LSTM on-the-fly (fast, ~2-5s)
      3. Cache result for next time
    """
    # 1. Check cache first (unless force_retrain)
    if not force_retrain:
        cached = get_prediction(product_url, source)
        if cached:
            logger.info("Returning cached prediction for %s/%s", source, product_url[:50])
            return {
                "product_url": product_url,
                "source": source,
                "cached": True,
                "prediction_updated_at": cached.get("prediction_updated_at"),
                **cached["prediction"],
            }

    # 2. Get price history from DB
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {
            "product_url": product_url,
            "source": source,
            "error": "No price history found for this product",
        }

    # 3. Train LSTM and predict
    result = train_and_predict(price_history, predict_days=7)
    if result is None:
        return {
            "product_url": product_url,
            "source": source,
            "error": "Not enough price data for prediction (need ≥3 data points)",
            "history_count": len(price_history),
        }

    # 4. Cache the prediction
    save_prediction(product_url, source, result)

    return {
        "product_url": product_url,
        "source": source,
        "cached": False,
        **result,
    }
