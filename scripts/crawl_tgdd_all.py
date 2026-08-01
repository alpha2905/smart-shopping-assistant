"""
Script cào TẤT CẢ sản phẩm + comment từ trang /dtdd của Thế Giới Di Động.
Lưu trực tiếp vào MongoDB collection 'tgdd'.

Chạy: python scripts/crawl_tgdd_all.py
"""
import asyncio
import logging
import os
import sys

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Fix Windows console encoding for Vietnamese characters
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from utils.browser import BrowserManager
from utils.db import init_tgdd_collection, save_tgdd_products, get_all_tgdd_products
from scrapers.thegioididong import TheGioiDiDongScraper


def main():
    # Khởi tạo collection 'tgdd' + indexes
    init_tgdd_collection()
    logger.info("=== BAT DAU CRAWL TAT CA SAN PHAM + COMMENT TGDD /dtdd ===")

    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = TheGioiDiDongScraper(browser_manager)
            logger.info("Dang crawl tat ca san pham tu https://www.thegioididong.com/dtdd ...")
            
            # Step 1: Crawl all product listings
            products = scraper.crawl_all_dtdd()
            logger.info(f"Da crawl xong: {len(products)} san pham")

            # Step 2: Crawl comments in parallel (multi-threaded)
            if products:
                products_data = scraper.extract_all_comments_multithreaded(products, max_workers=4)
            else:
                products_data = []

    except Exception as e:
        logger.error(f"Loi khi crawl: {e}", exc_info=True)
        return

    # 3. Lưu vào DB collection 'tgdd'
    if products_data:
        saved = save_tgdd_products(products_data)
        logger.info(f"=== Da luu {saved} san pham (voi comments) vao collection 'tgdd' ===")

        # Verify: đếm lại trong DB
        all_products = get_all_tgdd_products()
        total_comments = sum(p.get("comments_count", 0) for p in all_products)
        logger.info(f"Collection 'tgdd' hien co {len(all_products)} san pham, {total_comments} comments tong cong")
    else:
        logger.warning("Khong cao duoc san pham nao!")


if __name__ == "__main__":
    main()