import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import logging
from typing import List
from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto, wait_for_page_load

logger = logging.getLogger(__name__)


class CellphoneSScraper(BaseScraper):
    """Scraper for CellphoneS (https://cellphones.com.vn)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "CellphoneS"
        self.base_url = "https://cellphones.com.vn"

    def get_search_url(self, query: str) -> str:
        import urllib.parse
        return f"{self.base_url}/catalogsearch/result?q={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")

            if not safe_goto(page, search_url, timeout=45000):
                logger.warning(f"Failed to load search page for {self.site_name}")
                return products

            if not self.is_search_page_valid(page):
                logger.warning(f"[{self.site_name}] Search page appears invalid or blocked")
                return products

            self.wait_and_scroll(page, initial_wait=3000, scroll_times=4)

            products = self.extract_product_info(page, query, max_products)

            for product in products[:2]:
                try:
                    comments = self.extract_comments(page, product.product_url)
                    product.comments = comments
                except Exception as e:
                    logger.debug(f"Failed to get comments for {product.name}: {e}")

        except Exception as e:
            logger.error(f"Error scraping {self.site_name}: {e}")
        finally:
            page.close()

        return products

    def _extract_from_element(self, element) -> dict:
        """Extract product info from a single element using multiple strategies."""
        result = {"name": "", "price": "Liên hệ", "image_url": "", "product_url": ""}

        # Get the HTML for debugging
        try:
            html = element.inner_html()
        except Exception:
            html = ""

        # ---- NAME ----
        for sel in ["h3 a", "h3", "a.product__link", "a[title]", "a[href]", "div.product__name", 
                    "[class*='product__name']", "[class*='name']", "[class*='title']"]:
            try:
                el = element.query_selector(sel)
                if el:
                    txt = el.get_attribute("title") or el.inner_text().strip()
                    if txt and len(txt) > 3:
                        result["name"] = txt
                        break
            except Exception:
                continue

        # ---- PRICE ----
        for sel in ["p.product__price--show", "span.product__price--show", "[class*='price']",
                    ".price", "span.price", "p.price", "strong.price",
                    "[class*='Price']", "[class*='product__price']"]:
            try:
                el = element.query_selector(sel)
                if el:
                    txt = el.inner_text().strip()
                    if txt and any(c.isdigit() for c in txt):
                        result["price"] = txt
                        break
            except Exception:
                continue

        # ---- IMAGE ----
        for sel in ["img.product__img", "img.thumb", "img"]:
            try:
                el = element.query_selector(sel)
                if el:
                    url = el.get_attribute("data-src") or el.get_attribute("src") or ""
                    if url:
                        result["image_url"] = url
                        break
            except Exception:
                continue

        # ---- URL ----
        for sel in ["a.product__link", "a[href]", "a"]:
            try:
                el = element.query_selector(sel)
                if el:
                    href = el.get_attribute("href") or ""
                    if href and href != "#" and href != "/":
                        result["product_url"] = href
                        break
            except Exception:
                continue

        return result

    def extract_product_info(self, page: Page, query: str, max_products: int) -> List[Product]:
        products = []
        try:
            # Multiple outer container selectors
            product_elements = []
            for sel in [
                "div.product-info-container",
                "div.product-item",
                ".product-item",
                ".item",
                "li.item",
                "[class*='product']",
                "div[class*='cate'] div[class*='item']",
                "div[class*='category'] div[class*='item']",
            ]:
                product_elements = page.query_selector_all(sel)
                if product_elements:
                    logger.info(f"[{self.site_name}] Found elements with selector '{sel}': {len(product_elements)}")
                    break

            if not product_elements:
                # Last resort: look for any container with product links
                product_elements = page.query_selector_all("a[href*='/product'], a[href*='/mobile'], a[href*='/dtdd']")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            for element in product_elements[:max_products]:
                try:
                    info = self._extract_from_element(element)

                    if not self._is_phone_product(info["name"], info["product_url"]):
                        logger.debug(f"Bỏ qua sản phẩm không phải điện thoại: {info['name'][:50]}")
                        continue

                    if info["name"] and info["product_url"]:
                        # Normalize URL
                        href = info["product_url"]
                        if href.startswith("/"):
                            href = self.base_url + href
                        elif href.startswith("http"):
                            pass
                        else:
                            continue

                        products.append(Product(
                            name=info["name"].strip(),
                            price=info["price"].strip(),
                            image_url=info["image_url"].strip(),
                            product_url=href.strip(),
                            source=self.site_name
                        ))
                except Exception as e:
                    logger.debug(f"Error extracting product element: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error in extract_product_info for {self.site_name}: {e}")

        return products

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        comments = []
        try:
            if not product_url:
                return comments

            if not safe_goto(page, product_url, timeout=20000):
                return comments

            page.wait_for_timeout(2000)

            comment_selectors = [
                ".comment-content", ".review-content", ".customer-review",
                ".rating-content p", "[class*='comment'] p", "[class*='review'] p",
                ".product-comment p", ".comment-item p", ".feedback-content p",
                "[class*='feedback'] p", ".rc-review p", ".customer-comment p"
            ]
            comment_elements = page.query_selector_all(", ".join(comment_selectors))

            for el in comment_elements[:10]:
                try:
                    text = el.inner_text().strip()
                    if text and len(text) > 10:
                        comments.append(text)
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return comments


if __name__ == "__main__":
    import json
    import sys
    import os

    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST CELLPHONES SCRAPER ===")

    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = CellphoneSScraper(browser_manager=browser_manager)

            query_keyword = input("Nhập từ khóa tìm kiếm (ví dụ: iPhone, Samsung): ").strip()
            max_results = 3

            print(f"Đang tìm kiếm: '{query_keyword}'...")
            products = scraper.search(query=query_keyword, max_products=max_results)

            print(f"\nKết quả tìm thấy: {len(products)} sản phẩm\n" + "-" * 50)

            products_data = []
            for idx, prod in enumerate(products, 1):
                print(f"[{idx}] Tên: {prod.name} - Giá: {prod.price}")

                prod_dict = {
                    "name": prod.name,
                    "price": prod.price,
                    "product_url": prod.product_url,
                    "image_url": prod.image_url,
                    "source": prod.source,
                    "comments": getattr(prod, "comments", [])
                }
                products_data.append(prod_dict)

            output_file = "cellphones_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)

            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")
