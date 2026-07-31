"""
Script dùng cho GitHub Actions - scrape tất cả query đã lưu.
Chạy: python scripts/hourly_scrape.py

Sau khi scrape xong, train LSTM cho tất cả sản phẩm có đủ price history.
"""
import asyncio
import logging
import os
import sys
from typing import List, Dict, Any

# Thêm thư mục gốc của project vào sys.path để import được utils, scrapers,...
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from utils.db import (
    init_db, get_unique_queries, get_products_with_price_history,
    get_product_price_history, save_prediction,
)
from utils.price_predictor import train_and_predict
from utils.search_filter import filter_comparable_phones
from utils.browser import BrowserManager
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import 7 scraper
from scrapers.fptshop import FPTShopScraper
from scrapers.didongviet import DiDongVietScraper
from scrapers.clickbuy import ClickbuyScraper
from scrapers.cellphones import CellphoneSScraper
from scrapers.viettelstore import ViettelStoreScraper
from scrapers.hoanghamobile import HoangHaMobileScraper
from scrapers.thegioididong import TheGioiDiDongScraper


def run_single_scraper(scraper_class, query: str, max_products: int = 5) -> List[Dict[str, Any]]:
    """
    Hàm chạy từng scraper với BrowserManager riêng (thread-safe).
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
        from utils.db import save_search_results
        save_search_results(query, all_products)

    return filtered_products


def train_all_predictions():
    """Train LSTM cho tất cả sản phẩm có đủ price history (≥3 data points)."""
    logger.info("=== Training LSTM predictions for all products ===")
    try:
        products = get_products_with_price_history(min_history=3)
        if not products:
            logger.info("No products with enough price history yet, skipping LSTM training.")
            return

        logger.info(f"Found {len(products)} products to train LSTM")
        for prod in products:
            product_url = prod["product_url"]
            source = prod["source"]
            try:
                price_history = get_product_price_history(product_url, source)
                result = train_and_predict(price_history, predict_days=7)
                if result:
                    save_prediction(product_url, source, result)
                    logger.info(f"  ✓ {source}: {prod['name'][:40]} ({result['model_type']})")
                else:
                    logger.warning(f"  ✗ {source}: {prod['name'][:40]} - not enough data")
            except Exception as e:
                logger.error(f"  ✗ {source}: {prod['name'][:40]} - {e}")
        logger.info("=== LSTM training complete ===")
    except Exception as e:
        logger.error(f"Error in train_all_predictions: {e}", exc_info=True)


def main():
    init_db()
    queries = get_unique_queries()
    print(f"Found {len(queries)} queries to scrape: {queries}")
    for q in queries:
        print(f"Scraping: {q}")
        try:
            results = scrape_and_save(q)
            print(f"  -> {len(results)} products saved")
        except Exception as e:
            print(f"  -> Error: {e}")

    # Train LSTM predictions after scraping
    train_all_predictions()
    print("Done!")


if __name__ == "__main__":
    main()