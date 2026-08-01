import sys
import os

# Thêm thư mục gốc (E:\datn) vào sys.path để Python nhận diện các package như models, scrapers, utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import logging
from typing import List, Optional
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        return f"{self.base_url}/tim-kiem?scope=&kwd={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10, fetch_comments: bool = True) -> List[Product]:
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
            
            if fetch_comments:
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

    def scrape_price_from_url(self, product_url: str) -> Optional[Product]:
        """
        Cào tên và giá từ một trang sản phẩm cụ thể của Hoàng Hà Mobile.
        """
        page = self.browser_manager.new_page()
        try:
            if not safe_goto(page, product_url, timeout=45000):
                logger.warning(f"[{self.site_name}] Không thể tải trang sản phẩm: {product_url}")
                return None

            # Chờ cho tên sản phẩm và giá xuất hiện
            page.wait_for_selector("h1, .product-price", timeout=15000)

            name_el = page.query_selector("h1")
            name = name_el.inner_text().strip() if name_el else ""

            price_el = page.query_selector(".product-price")
            price = price_el.inner_text().strip() if price_el else "Liên hệ"
            
            img_el = page.query_selector(".gall-items img")
            image_url = ""
            if img_el:
                src = img_el.get_attribute("src")
                if src and src.startswith("http"):
                    image_url = src

            if not name:
                logger.warning(f"[{self.site_name}] Không tìm thấy tên sản phẩm tại {product_url}")
                return None

            return Product(
                name=name,
                price=price,
                image_url=image_url,
                product_url=product_url,
                source=self.site_name
            )
        except Exception as e:
            logger.error(f"[{self.site_name}] Lỗi khi cào giá từ {product_url}: {e}")
            return None
        finally:
            page.close()

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục của Hoàng Hà Mobile.
        Click "Xem thêm" để load hết sản phẩm.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/dien-thoai-di-dong"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /dien-thoai-di-dong page for {self.site_name}")
                return products

            page.wait_for_timeout(3000)

            # Click "Xem thêm" để load thêm sản phẩm
            for round_idx in range(30):  # max 30 clicks
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                    load_more_btn = page.locator("#page-pager a, a.show-more")
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Click 'Xem thêm' lần {round_idx + 1}")
                        load_more_btn.first.click()
                        page.wait_for_timeout(2500)
                    else:
                        logger.info(f"[{self.site_name}] Đã load hết sản phẩm sau {round_idx} vòng click.")
                        break
                except Exception as e:
                    logger.debug(f"[{self.site_name}] Lỗi vòng click Xem thêm: {e}")
                    break

            # Extract products
            product_elements = page.query_selector_all("div.pj16-item")
            logger.info(f"[{self.site_name}] Tìm thấy {len(product_elements)} product elements")

            limit = max_products if max_products else len(product_elements)
            for element in product_elements[:limit]:
                try:
                    name_el = element.query_selector("h3")
                    name = name_el.inner_text().strip() if name_el else ""
                    if not name:
                        link_title_el = element.query_selector("a[title]")
                        if link_title_el:
                            name = link_title_el.get_attribute("title") or ""
                    price_el = element.query_selector("div.price strong, .price")
                    price = price_el.inner_text().strip() if price_el else "Liên hệ"
                    img_el = element.query_selector("img")
                    image_url = ""
                    if img_el:
                        image_url = (img_el.get_attribute("data-src") or img_el.get_attribute("src") or img_el.get_attribute("data-lazy") or "")
                    link_el = element.query_selector("a[href]")
                    product_url = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            product_url = self.base_url + href
                        elif href.startswith("http"):
                            product_url = href

                    if name and product_url and self._is_phone_product(name, product_url):
                        products.append(Product(
                            name=name.strip(),
                            price=price.strip(),
                            image_url=image_url.strip(),
                            product_url=product_url.strip(),
                            source=self.site_name
                        ))
                except Exception as e:
                    logger.debug(f"Error extracting product element in crawl_all: {e}")
                    continue

            logger.info(f"[{self.site_name}] Đã cào được {len(products)} sản phẩm từ /dien-thoai-di-dong")

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        all_comments = []
        try:
            if not product_url:
                return []
            
            if not safe_goto(page, product_url, timeout=30000):
                return []
            
            page.wait_for_timeout(2000)
            
            # Cuộn xuống khu vực bình luận để kích hoạt hiển thị
            page.evaluate("window.scrollBy(0, 2000);")
            page.wait_for_timeout(1500)

            while True:
                comment_blocks = page.locator("div.comment-block").all()
                new_comments_found = False
                for block in comment_blocks:
                    try:
                        # Bỏ qua comment của Quản trị viên
                        if block.locator("span.qtv").count() > 0:
                            continue
                        
                        text_tag = block.locator("div.comment-text")
                        if text_tag.count() > 0:
                            content = text_tag.first.inner_text().strip()
                            if content and content not in all_comments:
                                all_comments.append(content)
                                new_comments_found = True
                    except Exception:
                        continue

                # Kiểm tra và bấm nút "Trang sau" của bình luận
                next_cmt_btn = page.locator("li.text.next a, a.page-link[rel='next']")
                if next_cmt_btn.count() > 0 and next_cmt_btn.first.is_visible():
                    logger.info("Clicking next page for comments...")
                    next_cmt_btn.first.click()
                    page.wait_for_timeout(2000)
                else:
                    # Không còn nút trang sau
                    break

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return list(dict.fromkeys(all_comments)) # Trả về list duy nhất

    def extract_all_comments_multithreaded(self, products: List[Product], max_workers: int = 4, max_comments: int = 300) -> List[dict]:
        """
        Cào comment cho tất cả sản phẩm bằng multi-threading.
        """
        products_data = []
        product_dicts = [{"name": p.name, "price": p.price, "image_url": p.image_url, "product_url": p.product_url, "source": p.source, "comments": []} for p in products]

        def _fetch_comments_for_product(prod_dict: dict) -> dict:
            """Hàm chạy trong thread riêng để cào comment cho 1 sản phẩm."""
            page = self.browser_manager.new_page()
            try:
                product_url = prod_dict["product_url"]
                comments = self.extract_comments(page, product_url)
                prod_dict["comments"] = comments[:max_comments]
                logger.info(f"  [Thread] {prod_dict['name'][:40]}... -> {len(comments)} comments")
            except Exception as e:
                logger.warning(f"  [Thread] Lỗi cào comment {prod_dict['name'][:40]}: {e}")
                prod_dict["comments"] = []
            finally:
                page.close()
            return prod_dict

        logger.info(f"Bắt đầu cào comment multi-threaded ({max_workers} workers) cho {len(product_dicts)} sản phẩm...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_fetch_comments_for_product, p) for p in product_dicts]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        products_data.append(result)
                except Exception as e:
                    logger.error(f"Lỗi thread cào comment: {e}")

        logger.info(f"Đã hoàn thành cào comment cho {len(products_data)} sản phẩm (multi-threaded)")
        return products_data

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