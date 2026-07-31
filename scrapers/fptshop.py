import sys
import os
import json
import logging
from typing import List, Optional
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

    def search(self, query: str, max_products: Optional[int] = None) -> List[Product]:
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

            self.wait_and_scroll(page, initial_wait=3000, scroll_times=4)
            products = self.extract_product_info(page, query, max_products)

            # Lấy comment cho từng sản phẩm
            for product in products[:max_products if max_products else len(products)]:
                try:
                    comments = self.extract_comments(product.product_url)
                    product.comments = comments
                    logger.info(f"Lấy được {len(comments)} comment cho {product.name}")
                except Exception as e:
                    logger.debug(f"Failed to get comments for {product.name}: {e}")

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

            # Cuộn xuống để load lazy images
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 0);")
            page.wait_for_timeout(1000)

            # Lấy tổng số trang
            total_pages = self._get_total_pages(page)
            logger.info(f"[{self.site_name}] Tổng số trang: {total_pages}")

            # Trang hiện tại là trang 1
            current_page = 1

            while current_page <= total_pages:
                logger.info(f"[{self.site_name}] Đang xử lý trang {current_page}/{total_pages}")

                # Cuộn để load hết sản phẩm trên trang hiện tại
                for _ in range(5):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.wait_for_timeout(1000)

                # Extract sản phẩm từ trang hiện tại
                page_products = self._extract_products_from_page(page, max_products)
                logger.info(f"[{self.site_name}] Trang {current_page}: tìm thấy {len(page_products)} sản phẩm")

                # Kiểm tra trùng lặp trước khi thêm
                existing_urls = {p.product_url for p in products}
                new_products = [p for p in page_products if p.product_url not in existing_urls]
                products.extend(new_products)
                logger.info(f"[{self.site_name}] Thêm {len(new_products)} sản phẩm mới (tổng: {len(products)})")

                # Kiểm tra nếu đã đủ số lượng max_products
                if max_products and len(products) >= max_products:
                    logger.info(f"[{self.site_name}] Đã đạt max_products={max_products}, dừng lại")
                    products = products[:max_products]
                    break

                # Chuyển sang trang tiếp theo
                current_page += 1
                if current_page > total_pages:
                    break

                # Tìm link đến trang tiếp theo và click
                try:
                    next_page_link = page.locator(f"span.pagerLink:has-text('{current_page}'), "
                                                   f"a.pagerLink:has-text('{current_page}'), "
                                                   f"[class*='pagerLink']:has-text('{current_page}')")
                    if next_page_link.count() > 0 and next_page_link.first.is_visible():
                        logger.info(f"[{self.site_name}] Chuyển sang trang {current_page}")
                        next_page_link.first.click()
                        page.wait_for_timeout(3000)
                        # Đợi trang mới load
                        for _ in range(3):
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                            page.wait_for_timeout(1000)
                    else:
                        # Thử click bằng href hoặc tìm kiếm
                        all_pager = page.locator("[class*='pagerLink']").all()
                        clicked = False
                        for pager in all_pager:
                            try:
                                text = pager.inner_text().strip()
                                if text == str(current_page):
                                    pager.click()
                                    page.wait_for_timeout(3000)
                                    clicked = True
                                    break
                            except Exception:
                                continue
                        if not clicked:
                            logger.warning(f"[{self.site_name}] Không tìm thấy link trang {current_page}, dừng phân trang")
                            break
                except Exception as e:
                    logger.warning(f"[{self.site_name}] Lỗi khi chuyển trang {current_page}: {e}")
                    break

            logger.info(f"[{self.site_name}] Đã cào được tổng cộng {len(products)} sản phẩm từ /dien-thoai ({total_pages} trang)")

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

    def extract_comments(self, product_url: str) -> List[str]:
        """
        Extract comments/reviews from a FPT Shop product page.
        Tìm comment trong span.break-word hoặc các container comment khác.
        """
        comments = []
        page = None
        try:
            if not product_url:
                return comments

            page = self.browser_manager.new_page()
            if not safe_goto(page, product_url, timeout=20000):
                return comments

            # Cuộn xuống khu vực đánh giá
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800);")
                page.wait_for_timeout(1000)

            # Click "Xem thêm đánh giá" nếu có
            max_click_attempts = 10
            for i in range(max_click_attempts):
                try:
                    # Tìm nút "Xem thêm" theo text, vì class thường là generic
                    btn_load_more = page.locator("button:has-text('Xem thêm'), a:has-text('Xem thêm')")
                    if btn_load_more.count() > 0 and btn_load_more.first.is_visible():
                        logger.info("Tìm thấy nút 'Xem thêm' đánh giá.")
                        btn_load_more.first.click()
                        page.wait_for_timeout(2500)
                    else:
                        break
                except Exception as e:
                    logger.debug(f"Lỗi khi click nút xem thêm: {e}")
                    break

            # Lấy danh sách comment - ưu tiên span.break-word (theo cấu trúc HTML bạn cung cấp)
            comment_elements = page.locator(
                "span.break-word, "
                "div[class*='comment'] p, "
                "div[class*='review'] p, "
                ".comment-content, "
                ".review-content, "
                "p[class*='comment'], "
                "p[class*='review'], "
                "[class*='comment']"
            ).all()

            for el in comment_elements:
                try:
                    text = el.inner_text().strip()
                    text = text.strip('"').strip("'")
                    if text and len(text) > 5 and text not in comments:
                        comments.append(text)
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")
        finally:
            if page:
                page.close()

        return comments


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
