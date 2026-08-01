"""
Script crawl toàn bộ sản phẩm từ Hoàng Hà Mobile và lưu vào MongoDB.
Sử dụng multi-threading để cào comment song song.

Chạy: python scripts/crawl_hoangha_all.py
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
from utils.db import init_hoangha_collection, save_hoangha_products
from scrapers.hoanghamobile import HoangHaMobileScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    """Crawl tất cả sản phẩm từ Hoàng Hà Mobile và lưu vào MongoDB."""
    init_hoangha_collection()
    logger.info("Đã khởi tạo collection 'hoangha'")

    # Step 1: Crawl all product listings (single-threaded)
    with BrowserManager(headless=True) as bm:
        scraper = HoangHaMobileScraper(bm)
        logger.info("Bắt đầu crawl tất cả sản phẩm từ Hoàng Hà Mobile...")
        products = scraper.crawl_all_phones()
        logger.info(f"Đã crawl được {len(products)} sản phẩm")

    # Step 2: Crawl comments in parallel (multi-threaded)
    # The scraper instance for this doesn't need a pre-set browser manager
    comment_scraper = HoangHaMobileScraper(None)
    all_products_data = comment_scraper.extract_all_comments_multithreaded(
        products, max_workers=4, max_comments=300
    )

    # Step 3: Save to MongoDB
    if all_products_data:
        saved = save_hoangha_products(all_products_data)
        logger.info(f"Đã lưu {saved} sản phẩm vào collection 'hoangha'")
    else:
        logger.warning("Không có sản phẩm nào để lưu")

if __name__ == "__main__":
    main()
    print("\n=== KẾT THÚC: Hoàn thành crawl Hoàng Hà Mobile ===")