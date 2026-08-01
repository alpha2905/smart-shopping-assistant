import sys
import os
import json
import logging
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    def search(self, query: str, max_products: int = 10, fetch_comments: bool = True) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")

            loaded = False
            loaded = safe_goto(page, search_url, timeout=60000, wait_until="domcontentloaded")

            if not loaded:
                logger.info(f"[{self.site_name}] Retry 1 failed, trying alternate navigation...")
                try:
                    page.wait_for_timeout(3000)
                    response = page.goto(search_url, wait_until="commit", timeout=45000)
                    if response:
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

            if not self.is_search_page_valid(page):
                logger.warning(f"[{self.site_name}] Search page appears invalid or blocked")
                return products

            self.wait_and_scroll(page, initial_wait=3000, scroll_times=4)
            products = self.extract_product_info(page, query, max_products)

            if fetch_comments:
                # Sử dụng context để cào comment hiệu quả hơn
                if hasattr(self.browser_manager, 'browser') and self.browser_manager.browser:
                    with self.browser_manager.browser.new_context() as context:
                        for product in products[:2]:
                            try:
                                page_cmt = context.new_page()
                                comments = self.extract_comments(page_cmt, product.product_url)
                                product.comments = comments
                                logger.info(f"Lấy được {len(comments)} comment cho {product.name}")
                                page_cmt.close()
                            except Exception as e:
                                logger.debug(f"Failed to get comments for {product.name}: {e}")

        except Exception as e:
            logger.error(f"Error scraping {self.site_name}: {e}")
        finally:
            page.close()

        return products

    def crawl_all_dtdd(self, max_products: int = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục /dtdd của TGDD.
        Không cần từ khóa tìm kiếm — cào hết tất cả sản phẩm có link /dtdd/.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/dtdd"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /dtdd page for {self.site_name}")
                return products

            page.wait_for_timeout(3000)

            # Cuộn xuống + bấm "Xem thêm" để load hết sản phẩm (lazy loading)
            max_load_rounds = 30  # Tối đa 30 vòng click "Xem thêm"
            for round_idx in range(max_load_rounds):
                try:
                    # Cuộn xuống cuối trang
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.wait_for_timeout(1500)

                    # Tìm nút "Xem thêm" (có thể là link hoặc button)
                    btn_xem_them = page.locator(
                        "a.view-more:has-text('Xem thêm'), "
                        "a.see-more:has-text('Xem thêm'), "
                        "a:has-text('Xem thêm sản phẩm'), "
                        ".view-more a, "
                        "a.viewmore"
                    )

                    if btn_xem_them.count() > 0 and btn_xem_them.first.is_visible():
                        logger.info(f"[{self.site_name}] Click 'Xem thêm' lần {round_idx + 1}")
                        btn_xem_them.first.click()
                        page.wait_for_timeout(2000)
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                        page.wait_for_timeout(1500)
                    else:
                        # Không còn nút "Xem thêm" → đã load hết
                        logger.info(f"[{self.site_name}] Đã load hết sản phẩm sau {round_idx} vòng")
                        break
                except Exception as e:
                    logger.debug(f"[{self.site_name}] Lỗi vòng load thêm: {e}")
                    break

            # Lấy số lượng sản phẩm trên trang
            product_count = page.locator("ul.listproduct li.item").count()
            logger.info(f"[{self.site_name}] Tìm thấy {product_count} sản phẩm trên trang /dtdd")

            # Extract tất cả sản phẩm (bỏ qua _is_phone_product vì đã ở trang /dtdd)
            product_elements = page.query_selector_all("ul.listproduct li.item, li.item[data-id]")
            if not product_elements:
                product_elements = page.query_selector_all("li.item")

            limit = max_products if max_products else len(product_elements)
            logger.info(f"[{self.site_name}] Bắt đầu extract {min(limit, len(product_elements))} sản phẩm")

            for element in product_elements[:limit]:
                try:
                    link_el = element.query_selector("a.main-contain")
                    name = ""
                    if link_el:
                        name = link_el.get_attribute("data-name") or ""
                    if not name:
                        name_el = element.query_selector("p.product-title, h3, .text-name")
                        if name_el:
                            name = name_el.inner_text().strip()

                    price = "Liên hệ"
                    if link_el and link_el.get_attribute("data-price"):
                        raw_price = link_el.get_attribute("data-price")
                        try:
                            price = f"{int(float(raw_price)):,} đ".replace(",", ".")
                        except Exception:
                            price = raw_price
                    if price == "Liên hệ":
                        price_el = element.query_selector("strong.price, .price")
                        if price_el:
                            price = price_el.inner_text().strip()

                    img_el = element.query_selector(".item-img img, img.thumb, img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("data-src") or
                            img_el.get_attribute("src") or
                            img_el.get_attribute("data-original") or ""
                        )

                    product_url = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            product_url = self.base_url + href
                        elif href.startswith("http"):
                            product_url = href

                    # Chỉ giữ sản phẩm có link chứa /dtdd/
                    if product_url and "/dtdd/" in product_url and name:
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

            logger.info(f"[{self.site_name}] Đã cào được {len(products)} sản phẩm từ /dtdd")

        except Exception as e:
            logger.error(f"Error crawling all dtdd from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def extract_product_info(self, page: Page, query: str, max_products: int) -> List[Product]:
        # ... (Giữ nguyên logic của bạn tại đây) ...
        # Hàm này của bạn đã viết tốt, không cần update, để tôi viết lại ngắn gọn cho khớp
        products = []
        try:
            product_elements = page.query_selector_all("ul.listproduct li.item, li.item[data-id]")
            if not product_elements:
                product_elements = page.query_selector_all("li.item")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            for element in product_elements[:max_products]:
                try:
                    link_el = element.query_selector("a.main-contain")
                    name = ""
                    if link_el:
                        name = link_el.get_attribute("data-name") or ""
                    if not name:
                        name_el = element.query_selector("p.product-title, h3, .text-name")
                        if name_el:
                            name = name_el.inner_text().strip()

                    price = "Liên hệ"
                    if link_el and link_el.get_attribute("data-price"):
                        raw_price = link_el.get_attribute("data-price")
                        try:
                            price = f"{int(float(raw_price)):,} đ".replace(",", ".")
                        except Exception:
                            price = raw_price
                    if price == "Liên hệ":
                        price_el = element.query_selector("strong.price, .price")
                        if price_el:
                            price = price_el.inner_text().strip()

                    img_el = element.query_selector(".item-img img, img.thumb, img")
                    image_url = ""
                    if img_el:
                        image_url = (
                            img_el.get_attribute("data-src") or
                            img_el.get_attribute("src") or
                            img_el.get_attribute("data-original") or ""
                        )

                    product_url = ""
                    if link_el:
                        href = link_el.get_attribute("href") or ""
                        if href.startswith("/"):
                            product_url = self.base_url + href
                        elif href.startswith("http"):
                            product_url = href

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

            # 1. Cuộn chuột xuống khu vực đánh giá để hiển thị các nút tương tác
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800);")
                page.wait_for_timeout(1000)

            # 2. Vòng lặp nhấn nút "Xem thêm đánh giá" vài lần cho đến khi nút xem tất cả / chuyển trang xuất hiện
            max_click_attempts = 15
            for i in range(max_click_attempts):
                try:
                    # Kiểm tra nếu nút "Xem tất cả" hoặc chuyển hướng chuyên sâu đã xuất hiện thì dừng việc bấm xem thêm
                    btn_view_all = page.locator("a#showall-cmt, a.btn-view-all")
                    if btn_view_all.count() > 0 and btn_view_all.first.is_visible():
                        logger.info("Nút xem tất cả / trang đánh giá chuyên sâu đã xuất hiện.")
                        btn_view_all.first.click(force=True)
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(2000)
                        break

                    # Tìm và bấm nút "Xem thêm đánh giá"
                    btn_load_more = page.locator("div.c-btn-rate.btn-cmt-larger10, div.c-btn-rate:has-text('Xem thêm đánh giá')")
                    if btn_load_more.count() > 0 and btn_load_more.first.is_visible():
                        btn_load_more.first.click()
                        page.wait_for_timeout(2500)  # Đợi dữ liệu load AJAX
                    else:
                        # Đã hết nút xem thêm
                        break
                except Exception as e:
                    logger.debug(f"Lỗi khi click nút xem thêm: {e}")
                    break

            # 3. Vòng lặp quét qua các trang phân trang dạng JavaScript ratingCmtList(page) (nếu có)
            current_page_idx = 1
            max_pages = 30

            while current_page_idx <= max_pages:
                # Lấy tất cả nội dung bình luận hiện có trên trang
                comment_elements = page.locator("p.cmt-txt").all()
                for el in comment_elements:
                    try:
                        text = el.inner_text().strip()
                        text = text.strip('"').strip("'")
                        if text and len(text) > 5 and text not in comments:
                            comments.append(text)
                    except Exception:
                        continue

                # Tìm nút chuyển trang tiếp theo dựa trên hàm JS ratingCmtList
                next_page_idx = current_page_idx + 1
                next_page_link = page.locator(f"a[href*='ratingCmtList({next_page_idx})']")

                if next_page_link.count() > 0 and next_page_link.first.is_visible():
                    logger.info(f"Chuyển sang trang đánh giá số {next_page_idx}...")
                    next_page_link.first.click(force=True)
                    page.wait_for_timeout(2000)
                    current_page_idx = next_page_idx
                else:
                    break

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")
        finally:
            # Không đóng page ở đây vì nó được quản lý bởi hàm gọi
            pass

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
                    comments = self.extract_comments(page, prod_dict["product_url"])
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

    print("=== BẮT ĐẦU CRAWL TẤT CẢ SẢN PHẨM VÀ COMMENT TỪ THẾ GIỚI DI ĐỘNG ===")

    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = TheGioiDiDongScraper(browser_manager=browser_manager)

            # Lấy tất cả sản phẩm điện thoại
            max_results = None  # Đặt số lượng giới hạn sản phẩm nếu muốn (vd: 10), hoặc None để lấy tất cả
            print("Đang tiến hành cào toàn bộ danh mục điện thoại...")
            products = scraper.crawl_all_dtdd(max_products=max_results)

            print(f"\nTìm thấy tổng cộng {len(products)} sản phẩm. Bắt đầu cào comment (tối đa 500 cmt/sản phẩm)...\n" + "-" * 50)

            products_data = []
            for idx, prod in enumerate(products, 1):
                print(f"[{idx}/{len(products)}] Đang cào comment cho: {prod.name}...")
                
                try:
                    # Để test, ta cần tạo page và truyền vào
                    page_cmt = browser_manager.new_page()
                    comments = scraper.extract_comments(page_cmt, prod.product_url)
                    page_cmt.close()

                    # Giới hạn tối đa 300 comment
                    comments = comments[:300]
                    
                    print(f"  -> Lấy thành công {len(comments)} comment.")
                except Exception as e:
                    print(f"  -> Không thể cào comment: {e}")

                prod_dict = {
                    "name": prod.name,
                    "price": prod.price,
                    "product_url": prod.product_url,
                    "image_url": prod.image_url,
                    "source": prod.source,
                    "comments": comments
                }
                products_data.append(prod_dict)

            output_file = "thegioididong_all_dtdd_with_comments.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)

            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC CRAWL ===")