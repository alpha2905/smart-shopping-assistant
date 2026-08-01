"""
Script cào TẤT CẢ sản phẩm + comment từ trang /dien-thoai của Viettel Store.
Lưu trực tiếp vào MongoDB collection 'viettelstore'.

Chạy: python scripts/crawl_viettelstore_all.py
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
from utils.db import init_viettelstore_collection, save_viettelstore_products
from scrapers.viettelstore import ViettelStoreScraper


def main():
    # Khởi tạo collection 'viettelstore' + indexes
    init_viettelstore_collection()
    logger.info("=== BAT DAU CRAWL TAT CA SAN PHAM + COMMENT VIETTEL STORE /dien-thoai ===")

    products_data = []
    try:
        with BrowserManager(headless=True) as browser_manager:
            scraper = ViettelStoreScraper(browser_manager)
            logger.info("Dang crawl tat ca san pham tu https://viettelstore.vn/dien-thoai ...")

            # 1. Crawl tất cả sản phẩm (chỉ thông tin cơ bản)
            products = scraper.crawl_all_phones()
            logger.info(f"Da crawl xong: {len(products)} san pham")

            # 2. Cào comment cho từng sản phẩm (dùng context để hiệu quả)
            logger.info(f"Bat dau cao comment cho {len(products)} san pham...")
            if hasattr(browser_manager, 'browser') and browser_manager.browser:
                with browser_manager.browser.new_context() as context:
                    for idx, prod in enumerate(products, 1):
                        logger.info(f"[{idx}/{len(products)}] Dang cao comment: {prod.name[:50]}...")
                        comments = []
                        try:
                            comments = scraper._extract_comments_viettel(context, prod.product_url)
                            comments = comments[:300] # Giới hạn 300 comments
                            logger.info(f"  -> Lay duoc {len(comments)} comment")
                        except Exception as e:
                            logger.warning(f"  -> Khong the cao comment: {e}")

                        products_data.append({
                            "name": prod.name, "price": prod.price, "image_url": prod.image_url,
                            "product_url": prod.product_url, "source": prod.source, "comments": comments,
                        })
            else:
                # Fallback nếu không có browser context
                for prod in products:
                     products_data.append({
                        "name": prod.name, "price": prod.price, "image_url": prod.image_url,
                        "product_url": prod.product_url, "source": prod.source, "comments": [],
                    })

            logger.info(f"Hoan thanh crawl: {len(products_data)} san pham + comments")

    except Exception as e:
        logger.error(f"Loi khi crawl: {e}", exc_info=True)
        return

    # 3. Lưu vào DB collection 'viettelstore'
    if products_data:
        saved = save_viettelstore_products(products_data)
        logger.info(f"=== Da luu {saved} san pham (voi comments) vao collection 'viettelstore' ===")
        
if __name__ == "__main__":
    main()