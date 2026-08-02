# scripts/update_prices.py
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
import sys
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional, Tuple

# Fix Windows console encoding for Vietnamese characters
if sys.platform == 'win32' and sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Setup logging to both file and console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("crawler.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
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

def scrape_urls(scraper_class, source_name: str, urls: List[str]) -> Tuple[str, List[Dict], int, int]:
    """
    Một worker xử lý tất cả URL cho một sàn (source) cụ thể.
    Nó sử dụng một BrowserManager (và một BrowserContext) duy nhất để cào tất cả URL,
    giúp duy trì session và tăng hiệu quả.

    Returns:
        Tuple: (source_name, list_of_product_data, success_count, total_count)
    """
    results = []
    ok_count = 0
    with BrowserManager(headless=True) as browser_manager:
        scraper = scraper_class(browser_manager)
        for url in urls:
            page = None
            try:
                page = browser_manager.new_page()
                product = scraper.scrape_price_from_url(url)
                if product:
                    results.append({
                        "name": product.name,
                        "price": product.price,
                        "image_url": product.image_url,
                        "product_url": product.product_url,
                        "source": product.source,
                    })
                    ok_count += 1
                    logger.info(f"[OK] {product.source}: {product.price} - {product.name[:50]}...")
                # Thêm delay ngẫu nhiên để tránh bị rate-limit
                page.wait_for_timeout(random.randint(500, 1800))
            except Exception as e:
                logger.error("%s | %s", type(e).__name__, url, exc_info=False)
            finally:
                if page:
                    page.close()
    return source_name, results, ok_count, len(urls)


def main():
    """
    Hàm chính để cập nhật giá cho tất cả sản phẩm trong cơ sở dữ liệu.
    """
    logger.info("🚀 Bắt đầu quy trình cập nhật giá hàng giờ...")
    init_db()

    urls_by_source = get_all_product_urls_by_source()
    if not urls_by_source:
        logger.info("Không tìm thấy URL sản phẩm nào trong DB. Kết thúc.")
        return

    all_new_products_data = []
    summary_stats = {}
    total_urls = sum(len(urls) for urls in urls_by_source.values())
    logger.info(f"Tìm thấy {total_urls} URL duy nhất từ {len(urls_by_source)} nguồn để cập nhật.")

    # Mỗi worker (luồng) sẽ xử lý một sàn (source)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = []
        for source, urls in urls_by_source.items():
            scraper_class = SOURCE_TO_SCRAPER.get(source)
            if not scraper_class:
                logger.warning(f"Không tìm thấy scraper cho nguồn: '{source}'. Bỏ qua {len(urls)} URL.")
                continue
            logger.info(f"Đưa {len(urls)} URL của '{source}' vào hàng đợi cào dữ liệu...")
            futures.append(executor.submit(scrape_urls, scraper_class, source, urls))

        for future in as_completed(futures):
            try:
                source_name, products, ok, total = future.result()
                if products:
                    all_new_products_data.extend(products)
                summary_stats[source_name] = (ok, total)
            except Exception as e:
                logger.error(f"Một worker đã gặp lỗi nghiêm trọng: {e}", exc_info=True)

    logger.info(f"Đã cào thành công {len(all_new_products_data)} trên tổng số {total_urls} URL.")

    # In bảng tóm tắt
    logger.info("--- Hourly Price Update Summary ---")
    for source, (ok, total) in sorted(summary_stats.items()):
        logger.info(f"{source:<20} {ok}/{total}")
    logger.info("---------------------------------")

    if all_new_products_data:
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