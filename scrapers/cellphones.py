import sys
import os
import json
import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import logging
from typing import List, Optional
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
        return f"{self.base_url}/catalogsearch/result?q={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10, fetch_comments: bool = True) -> List[Product]:
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

            if fetch_comments:
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
                product_elements = page.query_selector_all("a[href*='/product'], a[href*='/mobile'], a[href*='/dtdd']")

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            for element in product_elements[:max_products]:
                try:
                    info = self._extract_from_element(element)

                    if not self._is_phone_product(info["name"], info["product_url"]):
                        logger.debug(f"Bỏ qua sản phẩm không phải điện thoại: {info['name'][:50]}")
                        continue

                    if info["name"] and info["product_url"]:
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

    def scrape_price_from_url(self, product_url: str) -> Optional[Product]:
        """
        Cào tên và giá từ một trang sản phẩm cụ thể của CellphoneS.
        """
        page = self.browser_manager.new_page()
        try:
            if not safe_goto(page, product_url, timeout=45000):
                logger.warning(f"[{self.site_name}] Không thể tải trang sản phẩm: {product_url}")
                return None

            # Chờ cho tên sản phẩm và giá xuất hiện
            page.wait_for_selector("h1.product-info-title, .box-info__box-price .product-price", timeout=15000)

            name_el = page.query_selector("h1.product-info-title")
            name = name_el.inner_text().strip() if name_el else ""

            price_el = page.query_selector(".box-info__box-price .product-price")
            price = price_el.inner_text().strip() if price_el else "Liên hệ"
            
            img_el = page.query_selector(".box-gallery-desktop__list-img img")
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

    # ─── CRAWL ALL PHONES FROM /mobile.html ────────────────────────────────

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ https://cellphones.com.vn/mobile.html.
        Click "Xem thêm" để load hết sản phẩm, sau đó extract từng sản phẩm.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/mobile.html"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /mobile.html page for {self.site_name}")
                return products

            page.wait_for_timeout(3000)

            # Click "Xem thêm" để load thêm sản phẩm
            max_click_rounds = 30
            for round_idx in range(max_click_rounds):
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                    page.wait_for_timeout(1500)

                    btn_xem_them = page.locator(
                        "a.button__show-more-product, "
                        "a.btn-show-more, "
                        "a.button.btn-show-more, "
                        "button[class*='show-more'], "
                        "a:has-text('Xem thêm'), "
                        "a:has-text('Xem them'), "
                        "button:has-text('Xem thêm'), "
                        "button:has-text('Xem them')"
                    )

                    if btn_xem_them.count() > 0 and btn_xem_them.first.is_visible():
                        logger.info(f"[{self.site_name}] Click 'Xem thêm' lần {round_idx + 1}")
                        btn_xem_them.first.click()
                        page.wait_for_timeout(2000)
                    else:
                        logger.info(f"[{self.site_name}] Đã load hết sản phẩm sau {round_idx} vòng click")
                        break
                except Exception as e:
                    logger.debug(f"[{self.site_name}] Lỗi vòng click Xem thêm: {e}")
                    break

            # Cuộn lên đầu trang
            page.evaluate("window.scrollTo(0, 0);")
            page.wait_for_timeout(1000)

            # Lấy tất cả product containers
            product_containers = page.query_selector_all("div.product-info-container.product-item")
            logger.info(f"[{self.site_name}] Tìm thấy {len(product_containers)} product containers")

            if not product_containers:
                product_containers = page.query_selector_all("div.product-info-container")
                logger.info(f"[{self.site_name}] Fallback: tìm thấy {len(product_containers)} product-info-container")

            if not product_containers:
                product_list = page.query_selector("div.product-list-filter")
                if product_list:
                    product_containers = product_list.query_selector_all("div.product-info-container")
                    logger.info(f"[{self.site_name}] Fallback 2: tìm thấy {len(product_containers)} containers trong product-list-filter")

            limit = max_products if max_products else len(product_containers)
            logger.info(f"[{self.site_name}] Bắt đầu extract {min(limit, len(product_containers))} sản phẩm")

            for container in product_containers[:limit]:
                try:
                    product = self._extract_single_product(container)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Error extracting product: {e}")
                    continue

            logger.info(f"[{self.site_name}] Đã cào được {len(products)} sản phẩm từ /mobile.html")

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def _extract_single_product(self, container) -> Optional[Product]:
        """
        Trích xuất thông tin 1 sản phẩm từ container div.product-info-container.
        """
        try:
            link_el = container.query_selector("a.product__link")
            if not link_el:
                link_el = container.query_selector("a[href*='/dien-thoai-'], a[href*='/mobile'], a[href*='/iphone-'], a[href]")

            name = ""
            if link_el:
                img_inside = link_el.query_selector("img")
                if img_inside:
                    name = img_inside.get_attribute("alt") or ""

            if not name:
                name_el = container.query_selector("div.product__name h3, h3")
                if name_el:
                    name = name_el.inner_text().strip()

            if not name and link_el:
                name = link_el.get_attribute("title") or ""

            # Giá
            price = "Liên hệ"
            price_el = container.query_selector("p.product__price--show")
            if price_el:
                price_text = price_el.inner_text().strip()
                if price_text and any(c.isdigit() for c in price_text):
                    price = price_text

            # Hình ảnh
            img_el = container.query_selector("img.product__img, img")
            image_url = ""
            if img_el:
                image_url = (
                    img_el.get_attribute("data-src") or
                    img_el.get_attribute("src") or
                    ""
                )

            # Link
            product_url = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                if href.startswith("/"):
                    product_url = self.base_url + href
                elif href.startswith("http"):
                    product_url = href

            if name and product_url:
                return Product(
                    name=name.strip(),
                    price=price.strip(),
                    image_url=image_url.strip(),
                    product_url=product_url.strip(),
                    source=self.site_name
                )
        except Exception as e:
            logger.debug(f"Error extracting single product: {e}")

        return None

    # ─── EXTRACT COMMENTS (single product) ────────────────────────────────

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        """
        Extract comments/reviews from a CellphoneS product page.
        Dựa trên cấu trúc HTML thực tế:
        - Container: div.boxReview-comment-item
        - Name: div.block-info__name span.name
        - Comment: div.comment-content p
        - "Xem tất cả đánh giá": a.button__view-more-review (has-text-centered is-flex ...)
        """
        comments = []
        try:
            if not product_url:
                return comments

            if not safe_goto(page, product_url, timeout=20000):
                return comments

            page.wait_for_timeout(2000)

            # Cuộn xuống khu vực đánh giá
            for _ in range(5):
                page.evaluate("window.scrollBy(0, 600);")
                page.wait_for_timeout(800)

            # Click "Xem tất cả đánh giá" nếu có
            max_click_attempts = 5
            for i in range(max_click_attempts):
                try:
                    btn_view_more = page.locator(
                        "a.button__view-more-review, "
                        "a.has-text-centered.button__view-more-review, "
                        "a:has-text('Xem tất cả đánh giá'), "
                        "a:has-text('Xem tat ca danh gia'), "
                        "button:has-text('Xem tất cả'), "
                        "a.load-more"
                    )
                    if btn_view_more.count() > 0 and btn_view_more.first.is_visible():
                        logger.info("Tìm thấy nút 'Xem tất cả đánh giá', đang click...")
                        btn_view_more.first.click()
                        page.wait_for_timeout(2000)
                        for _ in range(3):
                            page.evaluate("window.scrollBy(0, 400);")
                            page.wait_for_timeout(500)
                    else:
                        break
                except Exception as e:
                    logger.debug(f"Lỗi khi click nút xem thêm đánh giá: {e}")
                    break

            # Lấy danh sách comment
            comment_items = page.locator("div.boxReview-comment-item").all()
            logger.info(f"Tìm thấy {len(comment_items)} comment items")

            for item in comment_items:
                try:
                    name_el = item.locator("div.block-info__name span.name")
                    reviewer_name = ""
                    if name_el.count() > 0:
                        reviewer_name = name_el.first.inner_text().strip()

                    comment_el = item.locator("div.comment-content p")
                    if comment_el.count() > 0:
                        text = comment_el.first.inner_text().strip()
                        if text and len(text) > 3:
                            comment_text = f"{reviewer_name}: {text}" if reviewer_name else text
                            if comment_text not in comments:
                                comments.append(comment_text)
                except Exception:
                    continue

            logger.info(f"Đã lấy được {len(comments)} comments từ {product_url[:50]}...")

        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")

        return comments

    # ─── EXTRACT ALL COMMENTS MULTI-THREADED ──────────────────────────────

    def extract_all_comments_multithreaded(
        self, products: List[Product], max_workers: int = 5, max_comments: int = 300
    ) -> List[dict]:
        """
        Cào comment cho tất cả sản phẩm bằng multi-threading.
        Mỗi thread dùng BrowserManager riêng (Playwright thread-safe).
        
        Args:
            products: List of Product objects to fetch comments for
            max_workers: Số thread tối đa (mặc định 5)
            max_comments: Giới hạn comment tối đa mỗi sản phẩm
            
        Returns:
            List[dict] với keys: name, price, image_url, product_url, source, comments
        """
        products_data = []
        product_dicts = []
        for p in products:
            product_dicts.append({
                "name": p.name,
                "price": p.price,
                "image_url": p.image_url,
                "product_url": p.product_url,
                "source": p.source,
                "comments": [],
            })

        def _fetch_comments_for_product(prod_dict: dict) -> dict:
            """Hàm chạy trong thread riêng để cào comment cho 1 sản phẩm."""
            page = self.browser_manager.new_page()
            try:
                product_url = prod_dict["product_url"]
                comments = self.extract_comments(page, product_url)
                prod_dict["comments"] = comments[:max_comments]
                logger.info(
                    f"  [Thread] {prod_dict['name'][:40]}... -> {len(comments)} comments"
                )
            except Exception as e:
                logger.warning(
                    f"  [Thread] Lỗi cào comment {prod_dict['name'][:40]}: {e}"
                )
                prod_dict["comments"] = []
            finally:
                page.close()
            return prod_dict

        logger.info(
            f"Bắt đầu cào comment multi-threaded ({max_workers} workers) cho "
            f"{len(product_dicts)} sản phẩm..."
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_fetch_comments_for_product, p)
                for p in product_dicts
            ]
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        products_data.append(result)
                except Exception as e:
                    logger.error(f"Lỗi thread cào comment: {e}")

        logger.info(
            f"Đã hoàn thành cào comment cho {len(products_data)} sản phẩm "
            f"(multi-threaded)"
        )
        return products_data


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

            print("Đang crawl tất cả sản phẩm từ /mobile.html...")
            products = scraper.crawl_all_phones(max_products=None)

            print(f"\nKết quả tìm thấy: {len(products)} sản phẩm\n" + "-" * 50)

            # Cào comment multi-threaded
            print("\nĐang cào comment multi-threaded...")
            products_data = scraper.extract_all_comments_multithreaded(
                products, max_workers=5, max_comments=300
            )

            for idx, prod in enumerate(products_data, 1):
                print(f"[{idx}] Tên: {prod['name']} - Giá: {prod['price']} - Comments: {len(prod['comments'])}")

            output_file = "cellphones_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)

            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")
