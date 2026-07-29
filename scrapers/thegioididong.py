import sys
import os
import json
import logging
from typing import List
import urllib.parse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto, wait_for_page_load

logger = logging.getLogger(__name__)


class TheGioiDiDongScraper(BaseScraper):
    """Scraper for Thế Giới Di Động (https://www.thegioididong.com)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "Thế Giới Di Động"
        self.base_url = "https://www.thegioididong.com"

    def get_search_url(self, query: str) -> str:
        return f"{self.base_url}/tim-kiem?key={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")

            # TGDĐ uses Cloudflare/anti-bot protection. Try multiple approaches.
            loaded = False

            # Approach 1: Standard navigation with full load
            loaded = safe_goto(page, search_url, timeout=60000, wait_until="domcontentloaded")

            # If approach 1 fails, try with "commit" + extra wait (handles some Cloudflare setups)
            if not loaded:
                logger.info(f"[{self.site_name}] Retry 1 failed, trying alternate navigation...")
                try:
                    page.wait_for_timeout(3000)
                    response = page.goto(search_url, wait_until="commit", timeout=45000)
                    if response:
                        # Wait for possible Cloudflare challenge to resolve
                        page.wait_for_timeout(5000)
                        wait_for_page_load(page, timeout=10000)
                        if response.status < 400:
                            loaded = True
                        else:
                            logger.warning(f"[{self.site_name}] Got HTTP {response.status} after retry")
                except Exception as e2:
                    logger.warning(f"[{self.site_name}] Retry 2 failed: {e2}")

            if not loaded:
                logger.warning(f"Failed to load search page for {self.site_name}")
                return products

            # Validate page loaded correctly
            if not self.is_search_page_valid(page):
                logger.warning(f"[{self.site_name}] Search page appears invalid or blocked")
                return products

            # Wait for content to load and scroll for lazy loading
            self.wait_and_scroll(page, initial_wait=3000, scroll_times=4)

            products = self.extract_product_info(page, query, max_products)

            # Try to get comments for first 2 products
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

    def extract_product_info(self, page: Page, query: str, max_products: int) -> List[Product]:
        products = []
        try:
            # Thử nhiều selector khác nhau để tìm sản phẩm
            product_elements = page.query_selector_all("ul.listproduct li.item, li.item[data-id]")
            if not product_elements:
                product_elements = page.query_selector_all("li.item, div.product-item, [class*='product'] article")
            if not product_elements:
                product_elements = page.query_selector_all("[data-id], div[class*='product'], li[class*='item']")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            for element in product_elements[:max_products]:
                try:
                    link_el = element.query_selector("a.main-contain") or element.query_selector("a[href*='dien-thoai']") or element.query_selector("a")

                    # 1. Lấy tên sản phẩm
                    name = ""
                    if link_el:
                        name = link_el.get_attribute("data-name") or ""
                    if not name:
                        for sel in ["h3", ".text-name", ".name", ".product-name", "[class*='name']"]:
                            name_el = element.query_selector(sel)
                            if name_el:
                                name = name_el.inner_text().strip()
                                if name:
                                    break

                    # 2. Lấy giá
                    price = "Liên hệ"
                    if link_el and link_el.get_attribute("data-price"):
                        raw_price = link_el.get_attribute("data-price")
                        try:
                            price = f"{int(float(raw_price)):,} đ".replace(",", ".")
                        except Exception:
                            price = raw_price
                    if price == "Liên hệ":
                        for sel in [".price", ".price-s", "strong.price", "[class*='price']", "span.price"]:
                            price_el = element.query_selector(sel)
                            if price_el:
                                t = price_el.inner_text().strip()
                                if t and any(c.isdigit() for c in t):
                                    price = t
                                    break

                    # 3. Lấy hình ảnh
                    img_el = element.query_selector(".item-img img, img.thumb, img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("data-src") or
                            img_el.get_attribute("src") or
                            img_el.get_attribute("data-original") or ""
                        )

                    # 4. Lấy đường dẫn sản phẩm
                    product_url = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            product_url = self.base_url + href
                        elif href.startswith("http"):
                            product_url = href

                    # Chỉ giữ sản phẩm là điện thoại
                    if not self._is_phone_product(name, product_url):
                        logger.debug(f"Bỏ qua sản phẩm không phải điện thoại: {name[:50]}")
                        continue

                    if name and product_url:
                        products.append(Product(
                            name=name.strip(),
                            price=price.strip(),
                            image_url=image_url.strip(),
                            product_url=product_url.strip(),
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST THẾ GIỚI DI ĐỘNG SCRAPER ===")

    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = TheGioiDiDongScraper(browser_manager=browser_manager)

            query_keyword = input("Nhập từ khóa tìm kiếm (ví dụ: iPhone 15): ").strip()
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

            output_file = "thegioididong_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)

            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")
