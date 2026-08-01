import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import logging
from typing import List
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

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
        return f"{self.base_url}/search?q={urllib.parse.quote(query)}"

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

    def scrape_price_from_url(self, product_url: str) -> Optional[Product]:
        """
        Cào tên và giá từ một trang sản phẩm cụ thể của Di Động Việt.
        """
        page = self.browser_manager.new_page()
        try:
            if not safe_goto(page, product_url, timeout=45000):
                logger.warning(f"[{self.site_name}] Không thể tải trang sản phẩm: {product_url}")
                return None

            # Chờ cho tên sản phẩm và giá xuất hiện
            page.wait_for_selector("h1, .price-goc, .price-final", timeout=15000)

            name_el = page.query_selector("h1")
            name = name_el.inner_text().strip() if name_el else ""

            price_el = page.query_selector(".price-goc")
            if not price_el:
                price_el = page.query_selector(".price-final")
            price = price_el.inner_text().strip() if price_el else "Liên hệ"
            
            img_el = page.query_selector(".swiper-wrapper .swiper-slide img")
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
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục của Di Động Việt.
        Click "Xem thêm" để load hết sản phẩm.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/dien-thoai.html"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /dien-thoai.html page for {self.site_name}")
                return products

            # Click "Xem thêm" để load hết sản phẩm
            for _ in range(30): # Giới hạn 30 lần click
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                    load_more_btn = page.locator("button:has-text('Xem thêm')")
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Clicking 'Xem thêm'...")
                        load_more_btn.first.click()
                        page.wait_for_timeout(2500)
                    else:
                        break
                except Exception:
                    break
            
            products = self.extract_product_info(page, "", max_products)
            logger.info(f"[{self.site_name}] Đã cào được {len(products)} sản phẩm từ /dien-thoai.html")

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        comments = []
        try:
            if not product_url:
                return comments
            
            if not safe_goto(page, product_url, timeout=45000, wait_until="domcontentloaded"):
                return comments
            
            # Cuộn xuống để load comment
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6);")
            page.wait_for_timeout(1500)

            comment_tags = page.locator("p[class*='text-[13px]']").all()
            for cmt in comment_tags:
                try:
                    text = cmt.inner_text().strip()
                    if text and text not in comments:
                        comments.append(text)
                except Exception:
                    continue
                    
        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return comments

    def extract_all_comments_multithreaded(self, products: List[Product], max_workers: int = 5, max_comments: int = 300) -> List[dict]:
        """
        Cào comment cho tất cả sản phẩm bằng multi-threading.
        """
        products_data = []
        product_dicts = [{"name": p.name, "price": p.price, "image_url": p.image_url, "product_url": p.product_url, "source": p.source, "comments": []} for p in products]

        def _fetch_comments_for_product(prod_dict: dict) -> dict:
            """Hàm chạy trong thread riêng để cào comment cho 1 sản phẩm."""
            try:
                with BrowserManager(headless=True) as bm:
                    page = bm.new_page()
                    product_url = prod_dict["product_url"]
                    comments = self.extract_comments(page, product_url)
                    page.close()
                    prod_dict["comments"] = comments[:max_comments]
                    logger.info(f"  [Thread] {prod_dict['name'][:40]}... -> {len(comments)} comments")
            except Exception as e:
                logger.warning(f"  [Thread] Lỗi cào comment {prod_dict['name'][:40]}: {e}")
                prod_dict["comments"] = []
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