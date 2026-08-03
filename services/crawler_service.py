from typing import List

from scrapers.all_sites import TGDDScraper, FPTScraper, CellphoneSScraper

from models.product import Product


class CrawlerService:

    # Dùng các scraper mới (crawl4ai-based) từ all_sites.py
    SCRAPERS = [
        FPTScraper,
        TGDDScraper,
        CellphoneSScraper,
    ]

    def search(self, keyword: str) -> List[dict]:
        """
        Tìm kiếm sản phẩm từ danh sách các sàn.
        Trả về danh sách các dictionary sản phẩm.
        """
        results = []

        for scraper_cls in self.SCRAPERS:
            try:
                # Các scraper mới nhận tham số headless (không cần BrowserManager)
                scraper = scraper_cls(headless=True)
                products = scraper.search(keyword)

                if products:
                    # Chuyển Product -> dict
                    for p in products:
                        if isinstance(p, Product):
                            results.append({
                                "name": p.name,
                                "price": p.price,
                                "image_url": p.image_url,
                                "product_url": p.product_url,
                                "source": p.source,
                                "comments": getattr(p, "comments", []),
                            })
                        else:
                            results.append(p)

            except Exception as ex:
                print(f"{scraper_cls.__name__}: {ex}")

        return results