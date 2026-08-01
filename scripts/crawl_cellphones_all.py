"""
Script crawl toàn bộ sản phẩm từ CellphoneS /mobile.html vào MongoDB collection 'cellphones'.
Sử dụng multi-threading để cào comment song song (nhanh hơn).
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
from utils.db import init_cellphones_collection, save_cellphones_products
from scrapers.cellphones import CellphoneSScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    """Crawl tất cả sản phẩm từ CellphoneS /mobile.html và lưu vào MongoDB (multi-threaded comments)."""
    # Khởi tạo collection 'cellphones'
    init_cellphones_collection()
    logger.info("Đã khởi tạo collection 'cellphones'")

    all_products_data = []
    with BrowserManager(headless=True) as browser_manager:
        scraper = CellphoneSScraper(browser_manager)
        
        # Bước 1: Crawl tất cả sản phẩm
        logger.info("Bắt đầu crawl tất cả sản phẩm từ CellphoneS /mobile.html...")
        products = scraper.crawl_all_phones()
        logger.info(f"Đã crawl được {len(products)} sản phẩm")

        # Bước 2: Cào comment MULTI-THREADED
        all_products_data = scraper.extract_all_comments_multithreaded(products, max_workers=5)

    if all_products_data:
        saved = save_cellphones_products(all_products_data)
        logger.info(f"Đã lưu {saved} sản phẩm vào collection 'cellphones'")
    else:
        logger.warning("Không có sản phẩm nào để lưu")

    return all_products_data


if __name__ == "__main__":
    products = main()
    print(f"\n=== KẾT THÚC: {len(products)} sản phẩm đã được crawl và lưu vào MongoDB ===")
