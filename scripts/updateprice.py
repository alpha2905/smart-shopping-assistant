"""Cập nhật giá điện thoại từ 8 sàn vào MongoDB.

Dùng cho GitHub Actions chạy định kỳ (hourly_price_update.yml).
- --once : chạy một lần rồi thoát (phù hợp với CI/CD, mỗi job là một lần chạy)
- --site : chỉ cập nhật một sàn cụ thể
- --max-products : giới hạn số sản phẩm mỗi sàn
"""
import argparse
import logging
import os
import sys

# Đảm bảo import được các module ở root repo khi chạy `python scripts/updateprice.py`
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

SITE_MAP = {
    "tgdd": ("TGDDScraper", "save_tgdd_products"),
    "fpt": ("FPTScraper", "save_fpt_products_incremental"),
    "cellphones": ("CellphoneSScraper", "save_cellphones_products"),
    "hoangha": ("HoangHaScraper", "save_hoangha_products"),
    "didongviet": ("DiDongVietScraper", "save_didongviet_products"),
    "viettelstore": ("ViettelStoreScraper", "save_viettelstore_products"),
    "clickbuy": ("ClickBuyScraper", "save_clickbuy_products"),
    "mobilecity": ("MobileCityScraper", "save_mobilecity_products"),
}


def update_prices(
    site: str,
    max_products: int,
    save: bool,
) -> int:
    """Crawl một sàn và lưu giá mới nhất vào MongoDB. Trả về số sản phẩm."""
    from scrapers import ALL_SCRAPERS
    from utils import db

    scraper_cls = next(c for c in ALL_SCRAPERS if c.__name__ == SITE_MAP[site][0])
    scraper = scraper_cls()
    logger.info(f"=== Cập nhật giá {scraper.site_name} ===")
    products = scraper.crawl_all_phones(max_products=max_products)
    logger.info(f"{scraper.site_name}: cập nhật được {len(products)} sản phẩm")
    if not products:
        return 0
    if save:
        save_fn = getattr(db, SITE_MAP[site][1])
        n = save_fn(scraper.product_dicts(products))
        logger.info(f"{scraper.site_name}: lưu {n} bản ghi vào DB")
    else:
        for p in products[:5]:
            print(f"- {p.name} | {p.price} | {p.product_url}")
    return len(products)


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Cập nhật giá điện thoại 8 sàn")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Chạy một lần rồi thoát (dùng cho GitHub Actions hourly job)",
    )
    parser.add_argument("--site", choices=list(SITE_MAP.keys()), help="Chỉ cập nhật 1 sàn")
    parser.add_argument("--max-products", type=int, default=None, help="Giới hạn sản phẩm")
    parser.add_argument("--no-save", action="store_true", help="Chỉ in không lưu DB")
    args = parser.parse_args()

    # Trong GitHub Actions mỗi job chỉ chạy một lần, vì vậy --once không cần vòng lặp.
    # Flag này được giữ để tương thích với lệnh gọi trong workflow hiện tại.
    if args.once:
        logger.info("Chạy chế độ --once: cập nhật giá một lần rồi thoát.")

    sites = [args.site] if args.site else list(SITE_MAP.keys())
    total = 0
    for s in sites:
        try:
            total += update_prices(s, args.max_products, save=not args.no_save)
        except Exception as e:
            logger.error(f"Lỗi cập nhật sàn '{s}': {e}", exc_info=True)
    logger.info(f"DONE: {total} sản phẩm từ {len(sites)} sàn")


if __name__ == "__main__":
    main()