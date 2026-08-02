from typing import List

from utils.db import (
    search_products,
    save_search_results,
)

from services.crawler_service import CrawlerService


class SearchService:

    def __init__(self):
        self.crawler = CrawlerService()

    def search(self, keyword: str) -> List[dict]:

        keyword = keyword.strip()

        if not keyword:
            return []

        # ===== STEP 1 =====
        # Search MongoDB

        products = search_products(keyword)

        if products:
            return products

        # ===== STEP 2 =====
        # Crawl nếu chưa có

        crawler_results = self.crawler.search(keyword)

        if crawler_results:

            save_search_results(
                keyword,
                crawler_results
            )

        # ===== STEP 3 =====
        # Query lại

        return search_products(keyword)