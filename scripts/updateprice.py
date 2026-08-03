# -*- coding: utf-8 -*-
"""
Cập nhật giá mỗi giờ cho TẤT CẢ sản phẩm của TẤT CẢ sàn trong DB
(phục vụ train/predict LSTM).

Cải tiến so với bản cũ:
- Dùng CHUNG kết nối MongoDB từ utils/db.py (đọc MONGODB_URI / MONGO_DB từ .env)
- Dùng scraper crawl4ai thật từ scrapers/all_sites.py để cào giá từ từng URL
- Lưu vào collection chính 'products' qua save_search_results()
  → đúng schema LSTM (price_value, scraped_at), dedupe theo giờ, cập nhật thống kê
- Đồng bộ vào collection riêng của từng sàn (tgdd, fpt, cellphones, ...)
  → vì get_product_price_history() ưu tiên collection riêng
- Chạy ngay 1 lần khi khởi động rồi lặp mỗi 1 giờ (APScheduler)
"""
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fix Windows console encoding cho tiếng Việt
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from apscheduler.schedulers.blocking import BlockingScheduler

from utils.db import (
    init_db, get_all_product_urls_by_source, save_search_results, close_db,
    parse_price, get_db,
)
from utils.logging_config import setup_logging
from scrapers.all_sites import (
    TGDDScraper, FPTScraper, CellphoneSScraper, HoangHaScraper,
    DiDongVietScraper, ViettelStoreScraper, ClickBuyScraper, MobileCityScraper,
)

setup_logging(log_filename="crawler.log")
logger = __import__("logging").getLogger(__name__)

# Map tên sàn (source trong DB) → class scraper crawl4ai tương ứng
SOURCE_TO_SCRAPER = {
    "Thế Giới Di Động": TGDDScraper,
    "FPT Shop": FPTScraper,
    "CellphoneS": CellphoneSScraper,
    "Hoàng Hà Mobile": HoangHaScraper,
    "Di Động Việt": DiDongVietScraper,
    "Viettel Store": ViettelStoreScraper,
    "ClickBuy": ClickBuyScraper,
    "Clickbuy": ClickBuyScraper,
    "MobileCity": MobileCityScraper,
}

# Map tên sàn → collection riêng chứa dữ liệu sản phẩm của sàn đó
SOURCE_TO_COLLECTION = {
    "Thế Giới Di Động": "tgdd",
    "FPT Shop": "fpt",
    "CellphoneS": "cellphones",
    "Hoàng Hà Mobile": "hoangha",
    "Di Động Việt": "didongviet",
    "Viettel Store": "viettelstore",
    "ClickBuy": "clickbuy",
    "Clickbuy": "clickbuy",
    "MobileCity": "mobilecity",
}

# Cào tối đa bao nhiêu URL 1 lượt (tránh mở quá nhiều tab cùng lúc)
BATCH_SIZE = 10


def scrape_source_urls(source: str, urls: List[str]) -> Tuple[str, List[Dict], int]:
    """
    Worker xử lý 1 sàn: cào giá mới nhất cho từng URL bằng crawl4ai.
    Trả về: (source, list_product_dicts, ok_count)
    """
    scraper_cls = SOURCE_TO_SCRAPER.get(source)
    if not scraper_cls:
        logger.warning("Không tìm thấy scraper cho sàn '%s'. Bỏ qua %d URL.", source, len(urls))
        return source, [], 0

    scraper = scraper_cls(headless=True)
    product_dicts: List[Dict] = []
    ok_count = 0

    for i in range(0, len(urls), BATCH_SIZE):
        batch = urls[i : i + BATCH_SIZE]
        htmls = scraper.fetch_many(batch)
        for url, html in zip(batch, htmls):
            if not html:
                logger.warning("[%s] Không lấy được HTML: %s", source, url)
                continue
            try:
                product = scraper._parse_product_detail(html, url)
                if not product:
                    continue
                # Chỉ lưu khi có giá thực (bỏ "Liên hệ")
                if parse_price(product.price) <= 0:
                    logger.info("[%s] SKIP (chưa có giá): %s", source, product.name[:50])
                    continue
                product_dicts.append({
                    "name": product.name,
                    "price": product.price,
                    "image_url": product.image_url,
                    "product_url": product.product_url,
                    "source": product.source,
                })
                ok_count += 1
                logger.info("[OK] %s: %s - %s", source, product.price, product.name[:50])
            except Exception as e:
                logger.warning("[%s] Lỗi parse %s: %s", source, url, e)

    logger.info("Hoàn thành sàn '%s': %d/%d URL OK", source, ok_count, len(urls))
    return source, product_dicts, ok_count


def sync_to_source_collection(source: str, products: List[Dict]) -> int:
    """
    Đồng bộ giá mới vào collection riêng của sàn (tgdd, fpt, ...).
    Đúng schema price_history (price_value, scraped_at) để LSTM/API đọc được.
    Dedupe: không push nếu entry cuối cùng giá và cách < 55 phút.
    """
    col_name = SOURCE_TO_COLLECTION.get(source)
    if not col_name or not products:
        return 0

    col = get_db()[col_name]
    now = datetime.utcnow()
    updated = 0

    for prod in products:
        url = prod.get("product_url", "")
        if not url:
            continue
        new_price_value = parse_price(prod.get("price", ""))

        # Kiểm tra entry cuối để dedupe theo giờ
        existing = col.find_one({"product_url": url}, {"price_history": 1})
        should_push = True
        if existing:
            history = existing.get("price_history", [])
            if history:
                last = history[-1]
                last_price = last.get("price_value", parse_price(last.get("price", "")))
                last_time = last.get("scraped_at")
                if last_price == new_price_value and last_time and now - last_time < timedelta(minutes=55):
                    should_push = False

        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": prod.get("price", ""),
            "price_value": new_price_value,
            "source": source,
            "last_scraped_at": now,
        }

        op = {"$set": set_fields}
        if should_push:
            op["$push"] = {
                "price_history": {
                    "price": prod.get("price", ""),
                    "price_value": new_price_value,
                    "scraped_at": now,
                }
            }

        col.update_one({"product_url": url}, op)
        updated += 1
        logger.info("  [SYNC %s] %s -> %s", col_name, url[:60], prod.get("price", ""))

    return updated


def update_hourly_prices() -> None:
    """Cập nhật giá toàn bộ sản phẩm toàn bộ sàn trong DB."""
    logger.info("🚀 Bắt đầu cập nhật giá hàng giờ lúc %s", datetime.now())
    init_db()

    urls_by_source = get_all_product_urls_by_source()
    if not urls_by_source:
        logger.info("Không tìm thấy URL sản phẩm nào trong DB. Kết thúc.")
        return

    total_urls = sum(len(urls) for urls in urls_by_source.values())
    logger.info("Tìm thấy %d URL từ %d sàn để cập nhật.", total_urls, len(urls_by_source))

    all_new_products: List[Dict] = []
    products_by_source: Dict[str, List[Dict]] = {}
    summary: Dict[str, Tuple[int, int]] = {}

    # Chạy song song từng sàn (mỗi sàn 1 thread, crawl4ai quản lý browser riêng)
    sources = [s for s in urls_by_source if s in SOURCE_TO_SCRAPER]
    with ThreadPoolExecutor(max_workers=len(sources) or 1) as executor:
        futures = {
            executor.submit(scrape_source_urls, source, urls_by_source[source]): source
            for source in sources
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                src, products, ok = future.result()
                summary[source] = (ok, len(urls_by_source[source]))
                if products:
                    all_new_products.extend(products)
                    products_by_source[src] = products
            except Exception as e:
                logger.error("Worker sàn '%s' gặp lỗi: %s", source, e, exc_info=True)

    logger.info("Đã cào thành công %d / %d URL.", len(all_new_products), total_urls)
    logger.info("--- Tóm tắt cập nhật giá ---")
    for source, (ok, total) in sorted(summary.items()):
        logger.info("%-20s %d/%d", source, ok, total)
    logger.info("-----------------------------")

    # 1) Lưu vào collection chính 'products' — đúng schema LSTM + dedupe + thống kê
    if all_new_products:
        save_search_results("hourly_price_update", all_new_products)
        logger.info("✅ Đã lưu %d bản ghi vào collection 'products'.", len(all_new_products))
    else:
        logger.warning("Không cào được dữ liệu giá mới nào. Không có gì để lưu.")

    # 2) Đồng bộ sang collection riêng của từng sàn
    for source, products in products_by_source.items():
        try:
            n = sync_to_source_collection(source, products)
            logger.info("✅ Đã đồng bộ %d bản ghi vào collection '%s'.", n, SOURCE_TO_COLLECTION.get(source))
        except Exception as e:
            logger.error("Lỗi đồng bộ sàn '%s': %s", source, e, exc_info=True)

    logger.info("🎉 Hoàn tất chu kỳ cập nhật giá lúc %s", datetime.now())


def main() -> None:
    # Chạy ngay 1 lần khi khởi động để kiểm tra kết nối + cập nhật tức thì
    update_hourly_prices()

    # Mode CI/GitHub Action: chạy 1 lần rồi thoát (không block bởi scheduler)
    if "--once" in sys.argv:
        close_db()
        logger.info("Da chay xong 1 lan (--once). Thoat.")
        return

    # Lập lịch chạy mỗi 1 giờ (chỉ dùng khi chạy local để giữ tiến trình sống)
    scheduler = BlockingScheduler()
    scheduler.add_job(update_hourly_prices, "interval", hours=1)
    logger.info("=== HỆ THỐNG CÀO GIÁ TỰ ĐỘNG CHO LSTM ĐÃ KHỞI ĐỘNG (mỗi 1 giờ) ===")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Đã dừng hệ thống scheduler thủ công.")
    finally:
        close_db()


if __name__ == "__main__":
    main()