import sys
import os

# Thêm thư mục gốc (E:\datn) vào sys.path để Python nhận diện các package như models, scrapers, utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
from typing import List
from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto, wait_for_page_load

logger = logging.getLogger(__name__)


class ViettelStoreScraper(BaseScraper):
    """Scraper for Viettel Store (https://viettelstore.vn)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "Viettel Store"
        self.base_url = "https://viettelstore.vn"

    def get_search_url(self, query: str) -> str:
        import urllib.parse
        return f"{self.base_url}/ket-qua-tim-kiem.html?keyword={urllib.parse.quote(query)}&sort=SearchResult"

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
                    logger.info(f"Checking comments for: {product.name}")
                    comments = self.extract_comments(page, product.product_url)
                    # Nếu có bình luận thì mới gán vào sản phẩm, không có thì bỏ qua
                    if comments:
                        product.comments = comments
                        logger.info(f"Found {len(comments)} comments for {product.name}")
                    else:
                        logger.info(f"No comments found for {product.name}, skipping.")
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
            # Cập nhật selector chuẩn xác theo cấu trúc HTML thực tế của Viettel Store
            product_elements = page.query_selector_all("div.product-item, div.product-info-container")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            for element in product_elements[:max_products]:
                try:
                    # Thẻ a chính chứa thông tin data-name, data-price
                    link_el = element.query_selector("a[data-name]") or element.query_selector("a")
                    
                    # 1. Lấy tên sản phẩm từ attribute data-name hoặc thẻ chứa tên
                    name = ""
                    if link_el:
                        name = link_el.get_attribute("data-name") or ""
                    
                    if not name:
                        name_el = element.query_selector("h3, .name, .product-name, [class*='name']")
                        if name_el:
                            name = name_el.inner_text().strip()

                    # 2. Lấy giá sản phẩm từ data-price hoặc class price
                    price = "Liên hệ"
                    if link_el and link_el.get_attribute("data-price"):
                        raw_price = link_el.get_attribute("data-price")
                        try:
                            # Xử lý format giá kiểu Viettel Store (vd: 1.199E+07 hoặc số thông thường)
                            price = f"{int(float(raw_price)):,} đ".replace(",", ".")
                        except Exception:
                            price = raw_price

                    if price == "Liên hệ":
                        price_el = element.query_selector(".price, .product-price, [class*='price']")
                        if price_el:
                            price = price_el.inner_text().strip()

                    # 3. Lấy hình ảnh từ img.product__img
                    img_el = element.query_selector("img.product__img, img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("data-src") or 
                            img_el.get_attribute("src") or 
                            img_el.get_attribute("data-lazy") or ""
                        )

                    # 4. Lấy đường dẫn sản phẩm (URL)
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

            # Cuộn xuống dưới một chút để trigger lazy load phần bình luận nếu có
            page.evaluate("window.scrollBy(0, 800)")
            page.wait_for_timeout(2000)

            # Lấy các thẻ chứa nội dung bình luận theo cấu trúc mới phát hiện
            comment_elements = page.query_selector_all(".cmt-item div.c, #div_cmt_lst div.c")

            for el in comment_elements[:10]:
                try:
                    text = el.inner_text().strip()
                    if text and len(text) > 5:
                        comments.append(text)
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return comments

if __name__ == "__main__":
    import sys
    import json
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST VIETTEL STORE SCRAPER ===")
    
    # Sử dụng 'with' để kích hoạt BrowserManager
    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = ViettelStoreScraper(browser_manager=browser_manager)
            
            query_keyword = input("Nhập từ khóa tìm kiếm (ví dụ: Oppo, iPhone): ").strip()
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

            # Xuất kết quả ra file JSON
            output_file = "viettelstore_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)
            
            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")