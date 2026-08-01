import sys
import os
import json
import logging
from typing import List, Optional
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto, wait_for_page_load

logger = logging.getLogger(__name__)


class FPTShopScraper(BaseScraper):
    """Scraper for FPT Shop (https://fptshop.com.vn)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "FPT Shop"
        self.base_url = "https://fptshop.com.vn"

    def get_search_url(self, query: str) -> str:
        return f"{self.base_url}/tim-kiem?key={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: Optional[int] = 10, fetch_comments: bool = True) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")

            if not safe_goto(page, search_url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load search page for {self.site_name}")
                return products

            if not self.is_search_page_valid(page):
                logger.warning(f"[{self.site_name}] Search page appears invalid or blocked")
                return products

            # Bấm "Xem thêm" để load hết sản phẩm trên trang tìm kiếm
            for _ in range(30): # Giới hạn 30 lần click
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                    load_more_btn = page.locator("button:has-text('Xem thêm')")
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Clicking 'Xem thêm' on search page...")
                        load_more_btn.first.click()
                        page.wait_for_timeout(3000) # Chờ AJAX load
                    else:
                        break
                except Exception:
                    break

            products = self.extract_product_info(page, query, max_products)

        except Exception as e:
            logger.error(f"Error scraping {self.site_name}: {e}")
        finally:
            page.close()
        return products

    def _get_total_pages(self, page: Page) -> int:
        """
        Lấy tổng số trang từ phân trang (pagination) trên FPT Shop.
        Tìm các phần tử có class 'pagerLink' và lấy số trang cuối cùng.
        """
        try:
            # Tìm tất cả page links
            page_links = page.locator("span.pagerLink, a.pagerLink, [class*='pagerLink']").all()
            max_page = 0
            for link in page_links:
                try:
                    text = link.inner_text().strip()
                    if text.isdigit():
                        num = int(text)
                        if num > max_page:
                            max_page = num
                except Exception:
                    continue
            if max_page > 0:
                logger.info(f"[{self.site_name}] Tìm thấy {max_page} trang phân trang")
                return max_page
        except Exception as e:
            logger.debug(f"[{self.site_name}] Không tìm thấy phân trang: {e}")
        return 1

    def _extract_product_from_element(self, element) -> Optional[Product]:
        """
        Trích xuất thông tin sản phẩm từ một element container trên FPT Shop.
        Dựa trên cấu trúc HTML thực tế:
        - Container: div.group.relative.flex...rounded-[10px]
        - Tên: h3.line-clamp-2.b2-regular
        - Giá: p.b1-semibold
        - Ảnh: img.object-contain
        - Link: a[href*="/dien-thoai/"]
        """
        try:
            # Tìm link sản phẩm - ưu tiên a có href chứa /dien-thoai/
            link_el = element.query_selector("a[href*='/dien-thoai/']") or element.query_selector("a")

            name = ""
            if link_el:
                name = link_el.get_attribute("data-name") or ""
                if not name:
                    # Tìm h3 với class line-clamp-2 (tên sản phẩm)
                    name_el = element.query_selector("h3[class*='line-clamp-2'], h3[class*='b2-regular'], h3")
                    if name_el:
                        name = name_el.inner_text().strip()

            # Giá sản phẩm - p với class b1-semibold
            price = "Liên hệ"
            price_el = element.query_selector("p[class*='b1-semibold'], p[class*='semibold'], [class*='price']")
            if price_el:
                price_text = price_el.inner_text().strip()
                if price_text and price_text != "$0":
                    price = price_text

            # Hình ảnh - img với class object-contain
            img_el = element.query_selector("img[class*='object-contain'], img")
            image_url = ""
            if img_el:
                image_url = (
                    img_el.get_attribute("data-src") or
                    img_el.get_attribute("src") or
                    img_el.get_attribute("data-original") or ""
                )

            # Link sản phẩm
            product_url = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href.startswith("/"):
                    product_url = self.base_url + href
                elif href.startswith("http"):
                    product_url = href

            # Chỉ giữ sản phẩm có link chứa /dien-thoai/ và có tên
            if product_url and "/dien-thoai/" in product_url and name:
                return Product(
                    name=name.strip(),
                    price=price.strip(),
                    image_url=image_url.strip(),
                    product_url=product_url.strip(),
                    source=self.site_name
                )
        except Exception as e:
            logger.debug(f"Error extracting product element: {e}")
        return None

    def _extract_products_from_page(self, page: Page, max_products: Optional[int] = None) -> List[Product]:
        """
        Trích xuất tất cả sản phẩm từ trang hiện tại.
        Sử dụng container selector phù hợp với cấu trúc HTML của FPT Shop.
        """
        products = []
        try:
            # Container chính: div.group.relative (FPT Shop dùng class group cho product card)
            # Các container có thể khác nhau trên các trang, thử nhiều selector
            product_elements = page.query_selector_all(
                "div[class*='group'][class*='rounded'], "
                "div[class*='group'][class*='flex'], "
                "div[class*='group']"
            )

            # Lọc: chỉ giữ element có chứa link /dien-thoai/ (điện thoại) và có h3
            valid_elements = []
            for el in product_elements:
                try:
                    has_phone_link = el.query_selector("a[href*='/dien-thoai/']")
                    has_h3 = el.query_selector("h3")
                    if has_phone_link and has_h3:
                        valid_elements.append(el)
                except Exception:
                    continue

            if not valid_elements:
                # Fallback: lấy tất cả div có chứa link /dien-thoai/
                logger.info(f"[{self.site_name}] Không tìm thấy elements với selector chính, thử fallback...")
                all_divs = page.query_selector_all("div")
                for el in all_divs:
                    try:
                        has_phone_link = el.query_selector("a[href*='/dien-thoai/']")
                        has_h3 = el.query_selector("h3")
                        if has_phone_link and has_h3:
                            valid_elements.append(el)
                    except Exception:
                        continue

            logger.info(f"[{self.site_name}] Tìm thấy {len(valid_elements)} sản phẩm hợp lệ trên trang")

            limit = max_products if max_products else len(valid_elements)
            for element in valid_elements[:limit]:
                product = self._extract_product_from_element(element)
                if product:
                    products.append(product)

        except Exception as e:
            logger.warning(f"[{self.site_name}] Error extracting products from page: {e}")

        return products

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục /dien-thoai của FPT Shop.
        Hỗ trợ phân trang (pagination) để lấy sản phẩm từ nhiều trang.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/dien-thoai"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /dien-thoai page for {self.site_name}")
                return products

            page.wait_for_timeout(3000)

            # Bấm "Xem thêm" để load hết sản phẩm
            for _ in range(30): # Giới hạn 30 lần click
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.wait_for_timeout(1000)
                    load_more_btn = page.locator("button:has-text('Xem thêm')")
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Clicking 'Xem thêm' on category page...")
                        load_more_btn.first.click()
                        page.wait_for_timeout(3000) # Chờ AJAX load
                    else:
                        logger.info(f"[{self.site_name}] Không còn nút 'Xem thêm', đã load hết sản phẩm.")
                        break
                except Exception as e:
                    logger.warning(f"[{self.site_name}] Lỗi khi click 'Xem thêm': {e}")
                    break

            # Sau khi load hết, extract tất cả sản phẩm
            products = self._extract_products_from_page(page, max_products)

            if max_products and len(products) > max_products:
                products = products[:max_products]

            logger.info(f"[{self.site_name}] Đã cào được tổng cộng {len(products)} sản phẩm từ /dien-thoai")

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def extract_product_info(self, page: Page, query: str, max_products: Optional[int] = None) -> List[Product]:
        """
        Trích xuất thông tin sản phẩm từ trang tìm kiếm.
        Dùng cùng selectors mới như crawl_all_phones.
        """
        products = []
        try:
            # Sử dụng cùng phương thức _extract_products_from_page để tái sử dụng logic
            products = self._extract_products_from_page(page, max_products)

            # Lọc theo query
            if query and products:
                query_lower = query.lower()
                filtered = []
                for p in products:
                    if query_lower in p.name.lower():
                        filtered.append(p)
                if filtered:
                    products = filtered
                    logger.info(f"[{self.site_name}] Lọc theo query '{query}': {len(products)} sản phẩm")

        except Exception as e:
            logger.warning(f"Error in extract_product_info for {self.site_name}: {e}")

        return products

    def scrape_price_from_url(self, product_url: str) -> Optional[Product]:
        """
        Cào tên và giá từ một trang sản phẩm cụ thể của FPT Shop.
        """
        page = self.browser_manager.new_page()
        try:
            if not safe_goto(page, product_url, timeout=45000):
                logger.warning(f"[{self.site_name}] Không thể tải trang sản phẩm: {product_url}")
                return None

            # Chờ cho tên sản phẩm và giá xuất hiện
            page.wait_for_selector("h1.st-name, .st-price-main", timeout=15000)

            name_el = page.query_selector("h1.st-name")
            name = name_el.inner_text().strip() if name_el else ""

            price_el = page.query_selector(".st-price-main")
            price = price_el.inner_text().strip() if price_el else "Liên hệ"
            
            img_el = page.query_selector(".f-prd-gallery__img img")
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

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        """
        Extract comments/reviews from a FPT Shop product page.
        Uses the provided logic for comment extraction and pagination.
        """
        comments = []
        try:
            if not product_url:
                return comments

            if not safe_goto(page, product_url, timeout=45000):
                return comments

            page.wait_for_timeout(1500) # Initial wait

            page_num = 1
            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)

                detail_soup = BeautifulSoup(page.content(), "html.parser")

                # Cào nội dung bình luận (Bỏ qua tên người dùng)
                comment_blocks = detail_soup.find_all(
                    "div", class_=lambda x: x and "flex flex-col pb-4 pt-0" in x
                )
                for block in comment_blocks:
                    content_tag = block.find(
                        "div",
                        class_=lambda x: x and "text-textOnWhitePrimary b2-regular" in x,
                    )
                    content = content_tag.text.strip() if content_tag else ""
                    if content and content not in comments:
                        comments.append(content)

                # Xử lý lật trang bình luận
                try:
                    # Selector cho nút next page của FPT Shop comments
                    next_btn_locator = page.locator("nav ul li").last
                    
                    # Check if the last li element has 'cursor-not-allowed' class
                    classes = next_btn_locator.get_attribute("class") or ""
                    if "cursor-not-allowed" in classes:
                        break # No more pages

                    next_btn_locator.scroll_into_view_if_needed()
                    next_btn_locator.click()
                    page_num += 1
                    page.wait_for_timeout(2500) # Wait for AJAX

                    if page_num > 20:  # Safety limit
                        logger.info(f"Reached safety limit of 20 comment pages for {product_url}")
                        break
                except Exception as e:
                    logger.debug(f"Error navigating comment pages for {product_url}: {e}")
                    break

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return comments

    def extract_all_comments_multithreaded(self, products: List[Product], max_workers: int = 4, max_comments: int = 300) -> List[dict]:
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


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST FPT SHOP SCRAPER ===")

    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = FPTShopScraper(browser_manager=browser_manager)
            
            # Crawl tất cả sản phẩm điện thoại
            print("Đang crawl tất cả sản phẩm điện thoại từ FPT Shop...")
            products = scraper.crawl_all_phones()

            print(f"\nTìm thấy tổng cộng {len(products)} sản phẩm")
            print("-" * 50)

            products_data = []
            for idx, prod in enumerate(products, 1):
                print(f"[{idx}] Tên: {prod.name[:50]}...")
                print(f"     Giá: {prod.price}")
                print(f"     Comments: {len(prod.comments)}")
                if prod.comments:
                    print(f"     -> Comment mẫu: {prod.comments[0][:50]}...")
                
                prod_dict = {
                    "name": prod.name,
                    "price": prod.price,
                    "product_url": prod.product_url,
                    "image_url": prod.image_url,
                    "source": prod.source,
                    "comments": prod.comments
                }
                products_data.append(prod_dict)

            output_file = "fptshop_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)
            
            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")
