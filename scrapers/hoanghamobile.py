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


class HoangHaMobileScraper(BaseScraper):
    """Scraper for Hoàng Hà Mobile (https://hoanghamobile.com)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "Hoàng Hà Mobile"
        self.base_url = "https://hoanghamobile.com"

    def get_search_url(self, query: str) -> str:
        import urllib.parse
        return f"{self.base_url}/tim-kiem?scope=&kwd={urllib.parse.quote(query)}"

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
            # Cập nhật selector chuẩn xác theo cấu trúc HTML thực tế của Hoàng Hà Mobile
            product_elements = page.query_selector_all("div.pj16-item")
            
            if not product_elements:
                product_elements = page.query_selector_all(".v5-item, .item, [class*='pj16-item']")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")
            
            for element in product_elements[:max_products]:
                try:
                    # 1. Lấy tên sản phẩm từ thẻ h3 hoặc attribute title của thẻ a
                    name_el = element.query_selector("h3")
                    name = name_el.inner_text().strip() if name_el else ""
                    
                    if not name:
                        link_title_el = element.query_selector("a[title]")
                        if link_title_el:
                            name = link_title_el.get_attribute("title") or ""

                    # 2. Lấy giá sản phẩm từ div.price strong hoặc .price
                    price_el = element.query_selector("div.price strong, .price")
                    price = price_el.inner_text().strip() if price_el else "Liên hệ"
                    
                    # 3. Lấy hình ảnh sản phẩm từ thẻ img
                    img_el = element.query_selector("img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("data-src") or 
                            img_el.get_attribute("src") or 
                            img_el.get_attribute("data-lazy") or ""
                        )
                    
                    # 4. Lấy đường dẫn chi tiết sản phẩm từ thẻ a
                    link_el = element.query_selector("a[href]")
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
        all_comments_set = set()  # Dùng set để chống trùng lặp bình luận
        try:
            if not product_url:
                return []
            
            if not safe_goto(page, product_url, timeout=20000):
                return []
            
            page.wait_for_timeout(2000)
            
            # Cuộn xuống khu vực bình luận để kích hoạt hiển thị
            page.evaluate("window.scrollBy(0, 1500);")
            page.wait_for_timeout(2000)

            def collect_current_page_comments():
                comment_elements = page.locator("div.comment-text, div.comment-block div.comment-text").all()
                for el in comment_elements:
                    try:
                        text = el.inner_text().strip()
                        # Làm sạch dấu ngoặc kép thừa
                        text = text.strip('"').strip("'").strip()
                        if text and len(text) > 4:
                            all_comments_set.add(text)
                    except Exception:
                        continue

            # === BƯỚC 1: LẤY DỮ LIỆU TRANG 1 ===
            collect_current_page_comments()

            # === BƯỚC 2: XỬ LÝ PHÂN TRANG ĐỘNG (CUỐN CHIẾU) ===
            current_page_idx = 2
            max_detected_page = 1

            # Quét tìm các số trang ban đầu xuất hiện trên thanh phân trang
            try:
                pagination_ol = page.locator("ol.pagination").first
                if pagination_ol.count() > 0:
                    lis = pagination_ol.locator("li").all()
                    for li in lis:
                        text = li.inner_text().strip()
                        text_val = "".join(filter(str.isdigit, text))
                        if text_val.isdigit():
                            max_detected_page = max(max_detected_page, int(text_val))
            except Exception as e:
                logger.debug(f"Lỗi khởi tạo phân trang: {e}")

            # Vòng lặp duyệt qua các trang bình luận tiếp theo
            while current_page_idx <= max_detected_page and current_page_idx <= 5:
                try:
                    # Click vào số trang tiếp theo
                    page.locator(f"ol.pagination >> li:has-text('{current_page_idx}')").first.click()
                    page.wait_for_timeout(2500)
                    logger.info(f"Đã click sang trang bình luận {current_page_idx}")

                    # Thu thập comment của trang hiện tại
                    collect_current_page_comments()

                    # Cập nhật lại max_detected_page nếu xuất hiện các trang mới lộ ra (ví dụ từ trang 3 lộ trang 6)
                    pagination_ol = page.locator("ol.pagination").first
                    if pagination_ol.count() > 0:
                        lis = pagination_ol.locator("li").all()
                        for li in lis:
                            text = li.inner_text().strip()
                            text_val = "".join(filter(str.isdigit, text))
                            if text_val.isdigit():
                                page_num = int(text_val)
                                if page_num > max_detected_page:
                                    max_detected_page = page_num

                except Exception as e:
                    logger.debug(f"Không thể chuyển tới trang bình luận {current_page_idx}: {e}")
                    break

                current_page_idx += 1

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return list(all_comments_set)

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST HOÀNG HÀ MOBILE SCRAPER ===")
    
    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = HoangHaMobileScraper(browser_manager=browser_manager)
            
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

            output_file = "hoanghamobile_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)
            
            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")