# scripts/update_prices.py
import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Import scrapers và các hàm tiện ích DB
from utils.db import init_db, get_all_product_urls_by_source, save_search_results, close_db
from utils.browser import BrowserManager
from models.product import Product

from scrapers.fptshop import FPTShopScraper
from scrapers.didongviet import DiDongVietScraper
from scrapers.clickbuy import ClickbuyScraper
from scrapers.cellphones import CellphoneSScraper
from scrapers.viettelstore import ViettelStoreScraper
from scrapers.hoanghamobile import HoangHaMobileScraper
from scrapers.mobilecity import MobileCityScraper
from scrapers.thegioididong import TheGioiDiDongScraper

# Map tên nguồn (source) với class scraper tương ứng
SOURCE_TO_SCRAPER = {
    "FPT Shop": FPTShopScraper,
    "Di Động Việt": DiDongVietScraper,
    "Clickbuy": ClickbuyScraper,
    "CellphoneS": CellphoneSScraper,
    "Viettel Store": ViettelStoreScraper,
    "Hoàng Hà Mobile": HoangHaMobileScraper,
    "MobileCity": MobileCityScraper,
    "Thế Giới Di Động": TheGioiDiDongScraper,
}

def scrape_and_update_price(scraper, url: str) -> Optional[Dict[str, Any]]:
    """
    Hàm worker để cào một URL duy nhất.
    Sử dụng scraper instance đã được khởi tạo với BrowserManager chung.
    """
    product_data = None
    try:
        # Giả định: mỗi scraper sẽ có phương thức `scrape_price_from_url`
        # Phương thức này sẽ tự quản lý việc tạo và đóng page.
        if hasattr(scraper, 'scrape_price_from_url') and callable(getattr(scraper, 'scrape_price_from_url')):
            product = scraper.scrape_price_from_url(url)
            if product:
                product_data = {
                    "name": product.name, "price": product.price, "image_url": product.image_url,
                    "product_url": product.product_url, "source": product.source,
                }
                logger.info(f"  [OK] {product.source}: {product.price} - {product.name[:50]}...")
        else:
            logger.warning(f"Scraper {scraper.__class__.__name__} thiếu phương thức 'scrape_price_from_url'.")
    except Exception as e:
        logger.error(f"Lỗi khi cào URL {url} với {scraper.__class__.__name__}: {e}", exc_info=False)
    
    return product_data

def main():
    """
    Hàm chính để cập nhật giá cho tất cả sản phẩm trong cơ sở dữ liệu.
    """
    logger.info("🚀 Bắt đầu quy trình cập nhật giá hàng giờ...")
    init_db()

    # 1. Lấy tất cả URL sản phẩm duy nhất từ DB
    urls_by_source = get_all_product_urls_by_source()
    if not urls_by_source:
        logger.info("Không tìm thấy URL sản phẩm nào trong DB. Kết thúc.")
        return

    all_new_products_data = []
    total_urls = sum(len(urls) for urls in urls_by_source.values())
    logger.info(f"Tìm thấy {total_urls} URL duy nhất từ {len(urls_by_source)} nguồn để cập nhật.")

    # 2. Khởi tạo BrowserManager và cào giá song song
    # Sử dụng 1 browser chung cho tất cả các luồng để tiết kiệm tài nguyên
    with BrowserManager(headless=True) as browser_manager:
        # Tăng số luồng vì không còn tốn tài nguyên khởi tạo browser cho mỗi task
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            
            # Tạo scraper instances với BrowserManager chung
            scrapers = {
                source: scraper_class(browser_manager)
                for source, scraper_class in SOURCE_TO_SCRAPER.items()
            }

            for source, urls in urls_by_source.items():
                scraper = scrapers.get(source)
                if not scraper:
                    logger.warning(f"Không tìm thấy scraper cho nguồn: '{source}'. Bỏ qua {len(urls)} URL.")
                    continue
                
                logger.info(f"Đưa {len(urls)} URL của '{source}' vào hàng đợi cào dữ liệu...")
                for url in urls:
                    futures.append(executor.submit(scrape_and_update_price, scraper, url))

            # 3. Thu thập kết quả khi các tác vụ hoàn thành
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        all_new_products_data.append(result)
                except Exception as e:
                    logger.error(f"Một tác vụ cào dữ liệu đã phát sinh lỗi: {e}")

    logger.info(f"Đã cào thành công {len(all_new_products_data)} trên tổng số {total_urls} URL.")

    # 4. Lưu dữ liệu giá mới vào DB
    if all_new_products_data:
        # Tái sử dụng hàm save_search_results. Hàm này sẽ lưu các bản ghi mới với timestamp,
        # tạo ra lịch sử giá mà không xóa dữ liệu cũ.
        logger.info(f"Đang lưu {len(all_new_products_data)} bản ghi giá mới vào DB...")
        save_search_results("hourly_price_update", all_new_products_data)
        logger.info("✅ Đã lưu thành công dữ liệu giá mới.")
    else:
        logger.warning("Không cào được dữ liệu giá mới nào. Không có gì để lưu.")

    close_db()
    logger.info("🎉 Quy trình cập nhật giá hàng giờ đã hoàn tất.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    main()