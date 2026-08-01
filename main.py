import logging
import sys
import json
from typing import List, Dict, Any, Tuple
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
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
    save_prediction, get_prediction, get_latest_prices_for_query,
    get_product_comments,
    init_tgdd_collection, save_tgdd_products, get_all_tgdd_products,
    init_fpt_collection, save_fpt_products_incremental, get_all_fpt_products,
    init_viettelstore_collection, save_viettelstore_products, get_all_viettelstore_products,
    init_hoangha_collection, save_hoangha_products, get_all_hoangha_products,
    init_mobilecity_collection, save_mobilecity_products, get_all_mobilecity_products,
    init_clickbuy_collection, save_clickbuy_products, get_all_clickbuy_products,
    init_didongviet_collection, save_didongviet_products, get_all_didongviet_products,
    init_cellphones_collection, save_cellphones_products, get_all_cellphones_products,
)
from utils.search_filter import filter_comparable_phones
from utils.price_predictor import train_and_predict
from utils.chatbot import get_chat_response
from utils.recommendation_engine import (
    calculate_pqs, calculate_price_statistics, get_buy_recommendation,
    analyze_product, analyze_products_batch,
)

# Import 7 scraper
from scrapers.fptshop import FPTShopScraper
from scrapers.didongviet import DiDongVietScraper
from scrapers.clickbuy import ClickbuyScraper
from scrapers.cellphones import CellphoneSScraper
from scrapers.viettelstore import ViettelStoreScraper
from scrapers.hoanghamobile import HoangHaMobileScraper
from scrapers.mobilecity import MobileCityScraper
from scrapers.thegioididong import TheGioiDiDongScraper

# Mapping từ scraper class → tên sàn (để gửi SSE event cho FE)
SCRAPER_NAMES = {
    "FPTShopScraper": "FPT Shop",
    "DiDongVietScraper": "Di Động Việt",
    "ClickbuyScraper": "Clickbuy",
    "CellphoneSScraper": "CellphoneS",
    "ViettelStoreScraper": "Viettel Store",
    "HoangHaMobileScraper": "Hoàng Hà Mobile",
    "MobileCityScraper": "MobileCity",
    "TheGioiDiDongScraper": "Thế Giới Di Động",
}

# Danh sách 7 scraper class
ALL_SCRAPER_CLASSES = [
    FPTShopScraper,
    DiDongVietScraper,
    ClickbuyScraper,
    CellphoneSScraper,
    ViettelStoreScraper,
    HoangHaMobileScraper,
    MobileCityScraper,
    TheGioiDiDongScraper,
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Platform Product Search API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Scheduler chạy ngầm ────────────────────────────────────────────────
scheduler = BackgroundScheduler()


def run_single_scraper(scraper_class, query: str, max_products: int = 5) -> List[Dict[str, Any]]:
    """
    Hàm chạy từng scraper với BrowserManager riêng (thread-safe).
    Mỗi scraper có browser instance riêng để tránh conflict.
    """
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
    max_products = None

    # Mỗi scraper dùng BrowserManager riêng (thread-safe)
    # Giới hạn max_workers=3 để tránh quá tải RAM/CPU
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
        f"Lọc kết quả: {len(all_products)} sản phẩm thô → {len(filtered_products)} điện thoại khớp. "
        f"Lưu hết {len(all_products)} sản phẩm vào DB"
    )

    # Lưu TẤT CẢ sản phẩm vào DB (không chỉ sản phẩm đã lọc)
    if all_products:
        save_search_results(query, all_products)

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
def search_products(
    q: str = Query(..., description="Từ khóa tìm kiếm sản phẩm"),
    force_refresh: bool = Query(False, description="Bỏ qua cache, scrape lại từ đầu"),
):
    # 1. Nếu không force_refresh, check DB trước → trả về ngay nếu đã có
    if not force_refresh:
        cached = get_latest_prices_for_query(q)
        if cached:
            logger.info("Query '%s' found in DB, returning %d cached products instantly", q, len(cached))
            return {
                "query": q,
                "total": len(cached),
                "products": cached,
                "cached": True,
            }

    # 2. Nếu chưa có trong DB (hoặc force_refresh) → scrape từ 7 sàn
    logger.info("Query '%s' not in DB (or force_refresh), scraping from 7 stores...", q)
    all_products = scrape_and_save(q)

    return {
        "query": q,
        "total": len(all_products),
        "products": all_products,
        "cached": False,
    }


# ─── SSE Streaming Search Endpoint ─────────────────────────────────────

async def _run_scraper_async(scraper_class, query: str, max_products: int) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Chạy 1 scraper trong thread pool (bất đồng bộ).
    Trả về (source_name, products_list).
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, run_single_scraper, scraper_class, query, max_products
    )
    source = SCRAPER_NAMES.get(scraper_class.__name__, scraper_class.__name__)
    return source, result


@app.get("/api/search/stream")
async def search_products_stream(
    q: str = Query(..., description="Từ khóa tìm kiếm sản phẩm"),
    force_refresh: bool = Query(False, description="Bỏ qua cache, scrape lại từ đầu"),
):
    """
    SSE endpoint: scrape 7 sàn song song (asyncio.gather),
    push kết quả từng sàn về FE ngay khi xong (Server-Sent Events).

    Event format:
      event: store   → {"source": "FPT Shop", "products": [...], "count": 5}
      event: cached  → {"total": 35, "products": [...]}
      event: done    → {"total": 35, "query": "iphone", "cached": false}
      event: error   → {"message": "..."}
    """

    # 1. Check cache trước (trả về ngay nếu có)
    if not force_refresh:
        cached = get_latest_prices_for_query(q)
        if cached:
            logger.info("Query '%s' found in DB, streaming %d cached products", q, len(cached))

            async def cached_stream():
                yield f"event: cached\ndata: {json.dumps({'total': len(cached), 'products': cached}, ensure_ascii=False, default=str)}\n\n"
                yield f"event: done\ndata: {json.dumps({'total': len(cached), 'query': q, 'cached': True}, ensure_ascii=False)}\n\n"

            return StreamingResponse(cached_stream(), media_type="text/event-stream")

    # 2. Scrape song song 7 sàn, stream kết quả từng sàn
    max_products = 15

    async def event_stream():
        all_products = []

        # Tạo task cho từng scraper — chạy song song bằng asyncio
        tasks = [
            asyncio.ensure_future(_run_scraper_async(sc, q, max_products))
            for sc in ALL_SCRAPER_CLASSES
        ]

        try:
            # as_completed: yield kết quả theo thứ tự sàn nào xong trước
            for coro in asyncio.as_completed(tasks):
                try:
                    source, result = await coro
                    if result:
                        all_products.extend(result)
                        # Push kết quả sàn này về FE ngay lập tức
                        event_data = {
                            "source": source,
                            "products": result,
                            "count": len(result),
                        }
                        yield f"event: store\ndata: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
                    else:
                        # Sàn không có sản phẩm → vẫn báo cho FE biết
                        event_data = {
                            "source": source,
                            "products": [],
                            "count": 0,
                        }
                        yield f"event: store\ndata: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
                except Exception as e:
                    logger.error(f"Lỗi scraper trong SSE stream: {e}", exc_info=True)
                    yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

            # 3. Lọc để hiển thị/log (nhưng vẫn lưu TẤT CẢ sản phẩm vào DB)
            filtered_products = filter_comparable_phones(all_products, q)
            logger.info(
                f"SSE stream: {len(all_products)} sản phẩm thô → {len(filtered_products)} điện thoại khớp. "
                f"Lưu hết {len(all_products)} sản phẩm vào DB"
            )

            # Lưu TẤT CẢ sản phẩm vào DB (không chỉ sản phẩm đã lọc)
            if all_products:
                save_search_results(q, all_products)

            # 4. Gửi event done
            done_data = {
                "total": len(all_products),
                "query": q,
                "cached": False,
            }
            yield f"event: done\ndata: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng trong SSE stream: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Price History + LSTM Prediction Endpoints ─────────────────────────

@app.get("/api/products-with-history")
def list_products_with_history():
    """List all products that have enough price history for LSTM prediction."""
    products = get_products_with_price_history(min_history=3)
    return {
        "total": len(products),
        "products": products,
    }


# ─── MobileCity Full Crawl Endpoints ──────────────────────────────────

def _crawl_mobilecity_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones và extract_all_comments_multithreaded cho MobileCity.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
    products_data = []
    try:
        # Scraper không cần browser manager ban đầu vì các method con tự quản lý
        scraper = MobileCityScraper(None)

        # Step 1: Crawl all product listings (multi-threaded page scraping)
        logger.info("Bắt đầu crawl TẤT CẢ sản phẩm từ MobileCity...")
        products = scraper.crawl_all_phones()
        logger.info(f"Đã crawl được {len(products)} sản phẩm từ MobileCity.")

        # Step 2: Crawl comments in parallel (multi-threaded comment scraping)
        if products:
            products_data = scraper.extract_all_comments_multithreaded(products, max_workers=4)

        logger.info(f"Crawl MobileCity hoàn tất: {len(products_data)} sản phẩm với comments.")
    except Exception as e:
        logger.error(f"Lỗi khi crawl MobileCity: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/mobilecity")
async def crawl_mobilecity_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai của MobileCity.
    Lưu vào collection 'mobilecity' (riêng biệt).
    """
    init_mobilecity_collection()

    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_mobilecity_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_mobilecity_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'mobilecity'",
        "total_crawled": len(products),
        "total_saved": saved,
    }

@app.get("/api/mobilecity/products")
def list_mobilecity_products():
    """Liệt kê tất cả sản phẩm đã crawl từ MobileCity (collection 'mobilecity')."""
    products = get_all_mobilecity_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── Clickbuy Full Crawl Endpoints ────────────────────────────────────

def _crawl_clickbuy_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones và extract_all_comments_multithreaded cho Clickbuy.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
    products_data = []
    try:
        # Step 1: Crawl all product listings (single-threaded)
        with BrowserManager(headless=True) as browser_manager:
            scraper = ClickbuyScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm từ Clickbuy...")
            products = scraper.crawl_all_phones()
            logger.info(f"Đã crawl được {len(products)} sản phẩm từ Clickbuy.")

        # Step 2: Crawl comments in parallel (multi-threaded)
        if products:
            scraper_for_comments = ClickbuyScraper(None)
            products_data = scraper_for_comments.extract_all_comments_multithreaded(products, max_workers=5)

        logger.info(f"Crawl Clickbuy hoàn tất: {len(products_data)} sản phẩm với comments.")
    except Exception as e:
        logger.error(f"Lỗi khi crawl Clickbuy: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/clickbuy")
async def crawl_clickbuy_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai của Clickbuy.
    Lưu vào collection 'clickbuy' (riêng biệt).
    """
    init_clickbuy_collection()

    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_clickbuy_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_clickbuy_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'clickbuy'",
        "total_crawled": len(products),
        "total_saved": saved,
    }

@app.get("/api/clickbuy/products")
def list_clickbuy_products():
    """Liệt kê tất cả sản phẩm đã crawl từ Clickbuy (collection 'clickbuy')."""
    products = get_all_clickbuy_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── Di Dong Viet Full Crawl Endpoints ────────────────────────────────

def _crawl_didongviet_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones và extract_all_comments_multithreaded cho Di Động Việt.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
    products_data = []
    try:
        # Step 1: Crawl all product listings (single-threaded)
        with BrowserManager(headless=True) as browser_manager:
            scraper = DiDongVietScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm từ Di Động Việt...")
            products = scraper.crawl_all_phones()
            logger.info(f"Đã crawl được {len(products)} sản phẩm từ Di Động Việt.")

        # Step 2: Crawl comments in parallel (multi-threaded)
        if products:
            scraper_for_comments = DiDongVietScraper(None)
            products_data = scraper_for_comments.extract_all_comments_multithreaded(products, max_workers=5)

        logger.info(f"Crawl Di Động Việt hoàn tất: {len(products_data)} sản phẩm với comments.")
    except Exception as e:
        logger.error(f"Lỗi khi crawl Di Động Việt: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/didongviet")
async def crawl_didongviet_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai.html của Di Động Việt.
    Lưu vào collection 'didongviet' (riêng biệt).
    """
    init_didongviet_collection()

    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_didongviet_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_didongviet_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'didongviet'",
        "total_crawled": len(products),
        "total_saved": saved,
    }

@app.get("/api/didongviet/products")
def list_didongviet_products():
    """Liệt kê tất cả sản phẩm đã crawl từ Di Động Việt (collection 'didongviet')."""
    products = get_all_didongviet_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── ViettelStore Full Crawl Endpoints ────────────────────────────────

def _crawl_viettelstore_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones (Playwright-based) trong thread.
    Trả về list product dicts.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = ViettelStoreScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm /dien-thoai từ Viettel Store...")

            # 1. Crawl all products
            products = scraper.crawl_all_phones()

            # 2. Crawl comments for each product
            logger.info(f"Bắt đầu cào comment cho {len(products)} sản phẩm Viettel Store...")
            if hasattr(browser_manager, 'browser') and browser_manager.browser:
                with browser_manager.browser.new_context() as context:
                    for idx, prod in enumerate(products, 1):
                        try:
                            comments = scraper._extract_comments_viettel(context, prod.product_url)
                            comments = comments[:300]
                            logger.info(f"  [{idx}/{len(products)}] {prod.name[:40]}... -> {len(comments)} comments")
                        except Exception as e:
                            comments = []
                            logger.warning(f"  [{idx}/{len(products)}] Không thể cào comment: {e}")

                        products_data.append({
                            "name": prod.name, "price": prod.price, "image_url": prod.image_url,
                            "product_url": prod.product_url, "source": prod.source, "comments": comments,
                        })
            else:
                logger.warning("Browser context not available, skipping comment extraction.")
                for prod in products:
                    products_data.append({
                        "name": prod.name, "price": prod.price, "image_url": prod.image_url,
                        "product_url": prod.product_url, "source": prod.source, "comments": [],
                    })

            logger.info(f"Crawl Viettel Store /dien-thoai hoàn tất: {len(products_data)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi crawl Viettel Store /dien-thoai: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/viettelstore")
async def crawl_viettelstore_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai của Viettel Store.
    Lưu vào collection 'viettelstore' (riêng biệt).
    """
    init_viettelstore_collection()

    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_viettelstore_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_viettelstore_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'viettelstore'",
        "total_crawled": len(products),
        "total_saved": saved,
    }


@app.get("/api/viettelstore/products")
def list_viettelstore_products():
    """Liệt kê tất cả sản phẩm đã crawl từ Viettel Store /dien-thoai (collection 'viettelstore')."""
    products = get_all_viettelstore_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── Hoang Ha Mobile Full Crawl Endpoints ───────────────────────────────

def _crawl_hoangha_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones và extract_all_comments_multithreaded trong thread.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass
            
    products_data = []
    try:
        # Step 1: Crawl all product listings (single-threaded)
        with BrowserManager(headless=True) as browser_manager:
            scraper = HoangHaMobileScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm từ Hoàng Hà Mobile...")
            products = scraper.crawl_all_phones()
            logger.info(f"Đã crawl được {len(products)} sản phẩm từ Hoàng Hà Mobile.")

        # Step 2: Crawl comments in parallel (multi-threaded)
        if products:
            # Create a new scraper instance without a pre-existing browser manager
            # as the multi-threaded method manages its own.
            scraper_for_comments = HoangHaMobileScraper(None)
            products_data = scraper_for_comments.extract_all_comments_multithreaded(products, max_workers=4)

        logger.info(f"Crawl Hoàng Hà Mobile hoàn tất: {len(products_data)} sản phẩm với comments.")
    except Exception as e:
        logger.error(f"Lỗi khi crawl Hoàng Hà Mobile: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/hoangha")
async def crawl_hoangha_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai-di-dong của Hoàng Hà Mobile.
    Lưu vào collection 'hoangha' (riêng biệt).
    """
    init_hoangha_collection()

    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_hoangha_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_hoangha_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'hoangha'",
        "total_crawled": len(products),
        "total_saved": saved,
    }

@app.get("/api/hoangha/products")
def list_hoangha_products():
    """Liệt kê tất cả sản phẩm đã crawl từ Hoàng Hà Mobile (collection 'hoangha')."""
    products = get_all_hoangha_products()
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


# ─── Chatbot Endpoint ──────────────────────────────────────────────────

@app.post("/api/chat")
def chat_endpoint(message: Dict[str, Any]):
    """
    Chatbot endpoint for shopping assistant.
    Accepts: {"message": "Tìm iPhone 16 Pro Max"}
    Returns: {"text": "...", "intent": "search", "query": "iPhone 16 Pro Max"}
    """
    user_message = message.get("message", "").strip()
    if not user_message:
        return {
            "text": "Bạn chưa nhập tin nhắn. Hãy gửi tin nhắn để tôi hỗ trợ bạn nhé! 😊",
            "intent": "empty",
            "query": None,
        }

    logger.info(f"Chat request: '{user_message[:100]}'")
    response = get_chat_response(user_message)
    return response


# ─── Product Quality Score (PQS) & Recommendation Endpoints ────────────

@app.get("/api/product-analysis")
def product_analysis(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    """
    Phân tích tổng thể sản phẩm: PQS, thống kê giá, khuyến nghị mua hàng.
    """
    # Get product info from DB
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    # Get latest product info
    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    # Get forecast if available
    forecast = get_prediction(product_url, source)
    forecast_result = forecast.get("prediction") if forecast else None

    # Run full analysis
    result = analyze_product(
        product=product,
        comments=get_product_comments(product_url, source),
        forecast_result=forecast_result,
    )
    return result


@app.get("/api/product-pqs")
def product_pqs(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    """
    Tính Product Quality Score (PQS) cho một sản phẩm.
    """
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    pqs_result = calculate_pqs(
        product=product,
        comments=get_product_comments(product_url, source),
    )
    return pqs_result


@app.get("/api/price-statistics")
def price_statistics(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    """
    Thống kê giá: min, max, avg, current, volatility.
    """
    stats = calculate_price_statistics(product_url, source)
    if not stats:
        return {"error": "Not enough price history (need >=2 data points)"}
    return stats


@app.get("/api/buy-recommendation")
def buy_recommendation(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    """
    Khuyến nghị mua hàng dựa trên PQS, giá, dự báo.
    """
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    # Get PQS
    pqs_result = calculate_pqs(
        product=product,
        comments=get_product_comments(product_url, source),
    )

    # Get price stats
    price_stats = calculate_price_statistics(product_url, source)

    # Get forecast
    forecast = get_prediction(product_url, source)
    forecast_result = forecast.get("prediction") if forecast else None

    # Get recommendation
    recommendation = get_buy_recommendation(
        product=product,
        pqs_result=pqs_result,
        price_stats=price_stats,
        forecast_result=forecast_result,
    )
    return recommendation


@app.get("/api/products-ranked")
def products_ranked(
    query: str = Query(..., description="Search query"),
):
    """
    Danh sách sản phẩm xếp hạng theo PQS cho một query.
    """
    products = get_latest_prices_for_query(query)
    if not products:
        return {"query": query, "total": 0, "products": []}

    results = analyze_products_batch(products)
    return {
        "query": query,
        "total": len(results),
        "products": results,
    }


# ─── CellphoneS Full Crawl Endpoints ────────────────────────────────────

def _crawl_cellphones_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones trong thread (sync Playwright).
    Trả về list product dicts.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = CellphoneSScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm /mobile.html từ CellphoneS...")
            products = scraper.crawl_all_phones()

            # Cào comment cho từng sản phẩm
            logger.info(f"Bắt đầu cào comment cho {len(products)} sản phẩm CellphoneS...")
            for idx, prod in enumerate(products, 1):
                try:
                    page = browser_manager.new_page()
                    comments = scraper.extract_comments(page, prod.product_url)
                    page.close()
                    comments = comments[:300]
                    logger.info(f"  [{idx}/{len(products)}] {prod.name[:40]}... -> {len(comments)} comments")
                except Exception as e:
                    comments = []
                    logger.warning(f"  [{idx}/{len(products)}] Không thể cào comment: {e}")

                products_data.append({
                    "name": prod.name,
                    "price": prod.price,
                    "image_url": prod.image_url,
                    "product_url": prod.product_url,
                    "source": prod.source,
                    "comments": comments,
                })

            logger.info(f"Crawl CellphoneS /mobile.html hoàn tất: {len(products_data)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi crawl CellphoneS /mobile.html: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/cellphones")
async def crawl_cellphones_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /mobile.html của CellphoneS.
    Lưu vào collection 'cellphones' (riêng biệt).
    """
    from utils.db import init_cellphones_collection, save_cellphones_products
    init_cellphones_collection()

    # Chạy crawl trong thread pool (Playwright sync API)
    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_cellphones_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_cellphones_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'cellphones'",
        "total_crawled": len(products),
        "total_saved": saved,
    }


@app.get("/api/cellphones/products")
def list_cellphones_products():
    """Liệt kê tất cả sản phẩm đã crawl từ CellphoneS /mobile.html (collection 'cellphones')."""
    from utils.db import get_all_cellphones_products
    products = get_all_cellphones_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── TGDD Full Crawl Endpoints ─────────────────────────────────────────

def _crawl_tgdd_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_dtdd trong thread (sync Playwright).
    Trả về list product dicts.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = TheGioiDiDongScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm /dtdd từ TGDD...")
            products = scraper.crawl_all_dtdd()
            for p in products:
                products_data.append({
                    "name": p.name,
                    "price": p.price,
                    "image_url": p.image_url,
                    "product_url": p.product_url,
                    "source": p.source,
                    "comments": getattr(p, "comments", []),
                })
            logger.info(f"Crawl TGDD /dtdd hoàn tất: {len(products_data)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi crawl TGDD /dtdd: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/tgdd")
async def crawl_tgdd_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dtdd của Thế Giới Di Động.
    Lưu vào collection 'tgdd' (riêng biệt).
    """
    init_tgdd_collection()

    # Chạy crawl trong thread pool (Playwright sync API)
    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_tgdd_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_tgdd_products(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'tgdd'",
        "total_crawled": len(products),
        "total_saved": saved,
    }


@app.get("/api/tgdd/products")
def list_tgdd_products():
    """Liệt kê tất cả sản phẩm đã crawl từ TGDD /dtdd (collection 'tgdd')."""
    products = get_all_tgdd_products()
    return {
        "total": len(products),
        "products": products,
    }


# ─── FPT Full Crawl Endpoints ──────────────────────────────────────────

def _crawl_fpt_all_sync() -> List[Dict[str, Any]]:
    """
    Chạy crawl_all_phones trong thread (sync Playwright).
    Trả về list product dicts.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = FPTShopScraper(browser_manager)
            logger.info("Bắt đầu crawl TẤT CẢ sản phẩm /dien-thoai từ FPT Shop...")
            products = scraper.crawl_all_phones()
            logger.info(f"Đã crawl được {len(products)} sản phẩm từ FPT Shop.")

        # Step 2: Crawl comments in parallel (multi-threaded)
        if products:
            # Create a new scraper instance without a pre-existing browser manager
            # as the multi-threaded method manages its own.
            scraper_for_comments = FPTShopScraper(None)
            products_data = scraper_for_comments.extract_all_comments_multithreaded(
                products, max_workers=4, max_comments=300
            )
        else:
            logger.warning("Không có sản phẩm nào để cào comment.")

        if products_data:
            logger.info(f"Crawl FPT /dien-thoai hoàn tất: {len(products_data)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi crawl FPT /dien-thoai: {e}", exc_info=True)
    return products_data


@app.post("/api/crawl/fpt")
async def crawl_fpt_all():
    """
    Cào TẤT CẢ sản phẩm từ trang /dien-thoai của FPT Shop.
    Lưu vào collection 'fpt' (riêng biệt).
    """
    init_fpt_collection()

    # Chạy crawl trong thread pool (Playwright sync API)
    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_fpt_all_sync)

    if not products:
        return {"message": "Không cào được sản phẩm nào", "total": 0}

    saved = save_fpt_products_incremental(products)

    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection 'fpt'",
        "total_crawled": len(products),
        "total_saved": saved,
    }


@app.get("/api/fpt/products")
def list_fpt_products():
    """Liệt kê tất cả sản phẩm đã crawl từ FPT Shop /dien-thoai (collection 'fpt')."""
    products = get_all_fpt_products()
    return {
        "total": len(products),
        "products": products,
    }
