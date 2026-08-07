"""Crawl toàn bộ 8 sàn điện thoại bằng crawl4ai rồi lưu vào MongoDB."""
import argparse
import logging

from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)

# site -> (scraper class, save function)
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


def crawl_site(site: str, max_products: int, save: bool) -> int:
    from scrapers import ALL_SCRAPERS
    from utils import db

    scraper_cls = next(c for c in ALL_SCRAPERS if c.__name__ == SITE_MAP[site][0])
    scraper = scraper_cls()
    logger.info(f"=== Crawl {scraper.site_name} ===")
    products = scraper.crawl_all_phones(max_products=max_products)
    logger.info(f"{scraper.site_name}: crawl được {len(products)} sản phẩm")
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
    parser = argparse.ArgumentParser(description="Crawl giá điện thoại 8 sàn")
    parser.add_argument("--site", choices=list(SITE_MAP.keys()), help="Chỉ crawl 1 sàn")
    parser.add_argument("--max-products", type=int, default=None, help="Giới hạn sản phẩm")
    parser.add_argument("--no-save", action="store_true", help="Chỉ in không lưu DB")
    args = parser.parse_args()

    sites = [args.site] if args.site else list(SITE_MAP.keys())
    total = 0
    for s in sites:
        total += crawl_site(s, args.max_products, save=not args.no_save)
    logger.info(f"DONE: {total} sản phẩm từ {len(sites)} sàn")


if __name__ == "__main__":
    main()