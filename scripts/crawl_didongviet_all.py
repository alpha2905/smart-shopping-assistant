"""
Script crawl toàn bộ sản phẩm từ Di Động Việt và lưu vào MongoDB.
Sử dụng multi-threading để cào comment song song.

Chạy: python scripts/crawl_didongviet_all.py
"""
import asyncio
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from utils.browser import BrowserManager
from utils.db import init_didongviet_collection, save_didongviet_products
from scrapers.didongviet import DiDongVietScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    """Crawl tất cả sản phẩm từ Di Động Việt và lưu vào MongoDB."""
    init_didongviet_collection()
    logger.info("Đã khởi tạo collection 'didongviet'")

    with BrowserManager(headless=True) as browser_manager:
        scraper = DiDongVietScraper(browser_manager)
        
        # Step 1: Crawl all product listings
        logger.info("Bắt đầu crawl tất cả sản phẩm từ Di Động Việt...")
        products = scraper.crawl_all_phones()
        logger.info(f"Đã crawl được {len(products)} sản phẩm")

        # Step 2: Crawl comments in parallel
        all_products_data = scraper.extract_all_comments_multithreaded(products, max_workers=5)

        # Step 3: Save to MongoDB
        if all_products_data:
            saved = save_didongviet_products(all_products_data)
            logger.info(f"Đã lưu {saved} sản phẩm vào collection 'didongviet'")

if __name__ == "__main__":
    main()
    print("\n=== KẾT THÚC: Hoàn thành crawl Di Động Việt ===")