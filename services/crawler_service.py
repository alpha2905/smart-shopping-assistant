from typing import List

from scrapers.fptshop import FPTShopScraper
from scrapers.thegioididong import TheGioiDiDongScraper
from scrapers.cellphones import CellphoneSScraper

from utils.browser import BrowserManager


class CrawlerService:

    SCRAPERS = [
        FPTShopScraper,
        TheGioiDiDongScraper,
        CellphoneSScraper,
    ]

    def search(self, keyword: str) -> List[dict]:

        results = []

        with BrowserManager(headless=True) as browser:

            for scraper_cls in self.SCRAPERS:

                scraper = scraper_cls(browser)

                try:

                    products = scraper.search(keyword)

                    if products:
                        results.extend(products)

                except Exception as ex:

                    print(
                        f"{scraper_cls.__name__}: {ex}"
                    )

        return results