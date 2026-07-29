import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import logging
from typing import List
from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto, wait_for_page_load

logger = logging.getLogger(__name__)


class DiDongVietScraper(BaseScraper):
    """Scraper for Di Động Việt (https://didongviet.vn)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "Di Động Việt"
        self.base_url = "https://didongviet.vn"

    def get_search_url(self, query: str) -> str:
        import urllib.parse
        return f"{self.base_url}/search?q={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")
            
            if not safe_goto(page, search_url, timeout=45000):
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
            # Cập nhật selector chuẩn xác theo cấu trúc HTML thực tế của Di Động Việt
            product_elements = page.query_selector_all("ul.grid > li")
            
            if not product_elements:
                product_elements = page.query_selector_all(".product-item, .item")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")
            
            for element in product_elements[:max_products]:
                try:
                    # 1. Lấy tên sản phẩm từ thẻ p chứa tên hoặc attribute title của thẻ a
                    name_el = element.query_selector("p.font-normal, [class*='text-sm'][class*='font-normal']")
                    name = ""
                    if name_el:
                        name = name_el.inner_text().strip()
                    if not name:
                        link_el = element if element.get_attribute("href") else element.query_selector("a")
                        if link_el:
                            name = link_el.get_attribute("title") or ""
                    
                    # 2. Lấy giá sản phẩm từ thẻ p có class font-bold text-primary-500
                    price_el = element.query_selector("p.font-bold, [class*='text-primary-500'], .price")
                    price = price_el.inner_text().strip() if price_el else "Liên hệ"
                    
                    # 3. Lấy ảnh sản phẩm từ thẻ img
                    img_el = element.query_selector("img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("src") or 
                            img_el.get_attribute("data-src") or ""
                        )
                    
                    # 4. Lấy đường dẫn chi tiết sản phẩm từ thẻ a
                    link_el = element if element.get_attribute("href") else element.query_selector("a[href]")
                    product_url = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            product_url = self.base_url + href
                        elif href.startswith("http"):
                            product_url = href
                        elif href and not href.startswith("#"):
                            product_url = href
                    
                    # Chỉ giữ sản phẩm là điện thoại
                    if not self._is_phone_product(name, product_url):
                        logger.debug(f"Bỏ qua sản phẩm không phải điện thoại: {name[:50]}")
                        continue

                    if name:
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
            
            comment_elements = page.query_selector_all(
                ".comment-content, .review-content, .customer-review, "
                ".rating-content p, [class*='comment'] p, [class*='review'] p, "
                ".product-comment p, .comment-item p, .feedback-content p, "
                "[class*='feedback'] p, .rc-review p, .customer-comment p"
            )
            
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

    # Đảm bảo nhận diện đúng thư mục gốc nếu chạy trực tiếp
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST DI ĐỘNG VIỆT SCRAPER ===")
    
    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = DiDongVietScraper(browser_manager=browser_manager)
            
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

            output_file = "didongviet_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)
            
            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")