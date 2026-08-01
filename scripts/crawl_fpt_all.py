"""
Script cào TẤT CẢ sản phẩm + comment từ trang /dien-thoai của FPT Shop.
Lưu trực tiếp vào MongoDB collection 'fpt'.

Chạy: python scripts/crawl_fpt_all.py
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
from utils.db import init_fpt_collection, save_fpt_products_incremental, get_all_fpt_products
from scrapers.fptshop import FPTShopScraper


def main():
    # Khởi tạo collection 'fpt' + indexes
    init_fpt_collection()
    logger.info("=== BAT DAU CRAWL TAT CA SAN PHAM + COMMENT FPT SHOP /dien-thoai ===")

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = FPTShopScraper(browser_manager)
            logger.info("Dang crawl tat ca san pham tu https://fptshop.com.vn/dien-thoai ...")

            # 1. Crawl tất cả sản phẩm (chỉ thông tin cơ bản)
            products = scraper.crawl_all_phones()
            logger.info(f"Da crawl xong: {len(products)} san pham")

        # 2. Cào comment MULTI-THREADED (mỗi thread dùng BrowserManager riêng)
        if products:
            logger.info(f"Bắt đầu cào comment MULTI-THREADED cho {len(products)} sản phẩm (max_workers=4)...")
            # The scraper instance for this doesn't need a pre-set browser manager
            comment_scraper = FPTShopScraper(None)
            products_data = comment_scraper.extract_all_comments_multithreaded(
                products, max_workers=4, max_comments=300
            )
            logger.info(f"Hoan thanh crawl: {len(products_data)} san pham + comments")
        else:
            logger.warning("Không có sản phẩm nào để cào comment.")

    except Exception as e:
        logger.error(f"Loi khi crawl: {e}", exc_info=True)
        return

    # 3. Lưu vào DB collection 'fpt'
    if products_data:
        saved = save_fpt_products_incremental(products_data)
        logger.info(f"=== Da luu {saved} san pham (voi comments) vao collection 'fpt' ===")

        # Verify: đếm lại trong DB
        all_products = get_all_fpt_products()
        total_comments = sum(p.get("comments_count", 0) for p in all_products)
        logger.info(f"Collection 'fpt' hien co {len(all_products)} san pham, {total_comments} comments tong cong")
    else:
        logger.warning("Khong cao duoc san pham nao!")


if __name__ == "__main__":
    main()