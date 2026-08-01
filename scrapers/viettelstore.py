import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import urllib.parse
from typing import List, Optional, Tuple
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
        return f"{self.base_url}/ket-qua-tim-kiem.html?keyword={urllib.parse.quote(query)}&sort=SearchResult"

    def search(self, query: str, max_products: Optional[int] = 10, fetch_comments: bool = True) -> List[Product]:
        products = []
        search_page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")
            
            if not safe_goto(search_page, search_url, timeout=45000):
                logger.warning(f"Failed to load search page for {self.site_name}")
                return products

            if not self.is_search_page_valid(search_page):
                logger.warning(f"[{self.site_name}] Search page appears invalid or blocked")
                return products

            self.wait_and_scroll(search_page, initial_wait=3000, scroll_times=4)
            products = self.extract_product_info(search_page, query, max_products)
            
            search_page.close()

            if fetch_comments:
                logger.info(f"Bắt đầu lấy comment cho {len(products)} sản phẩm bằng Context...")
                
                if hasattr(self.browser_manager, 'browser') and self.browser_manager.browser:
                    browser = self.browser_manager.browser
                    with browser.new_context() as context:
                        for product in products:
                            try:
                                comments = self._extract_comments_viettel(context, product.product_url)
                                if comments:
                                    product.comments = comments
                                    logger.info(f"Lấy được {len(comments)} comment cho {product.name}")
                                else:
                                    logger.debug(f"Sản phẩm {product.name} chưa có bình luận.")
                            except Exception as e:
                                logger.debug(f"Failed to get comments for {product.name}: {e}")
                else:
                    for product in products:
                        try:
                            comments = self.extract_comments_legacy(product.product_url) 
                            if comments:
                                product.comments = comments
                        except Exception as e:
                            logger.debug(f"Failed to get comments for {product.name}: {e}")

        except Exception as e:
            logger.error(f"Error scraping {self.site_name}: {e}")
        
        return products

    def _extract_single_product_from_element(self, element) -> Optional[Product]:
        """
        Trích xuất thông tin 1 sản phẩm từ element.
        Sử dụng các thuộc tính data-* và fallback về text.
        """
        try:
            link_el = element.query_selector("a[data-name]") or element.query_selector("a")
            
            name = ""
            if link_el:
                name = link_el.get_attribute("data-name") or ""
            if not name:
                name_el = element.query_selector("div.product-name h2, h3, .name, .product-name")
                if name_el:
                    name = name_el.inner_text().strip()

            price = "Liên hệ"
            if link_el and link_el.get_attribute("data-price"):
                raw_price = link_el.get_attribute("data-price")
                try:
                    price = f"{int(float(raw_price)):,} đ".replace(",", ".")
                except (ValueError, TypeError):
                    price = raw_price
            if price == "Liên hệ":
                price_el = element.query_selector("div.price, .product-price")
                if price_el:
                    price = price_el.inner_text().strip()

            img_el = element.query_selector("img.product__img, img")
            image_url = ""
            if img_el:
                image_url = img_el.get_attribute("src") or img_el.get_attribute("data-src") or ""

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
            logger.debug(f"Error extracting single product element: {e}")
        
        return None

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục /dien-thoai của Viettel Store.
        Sử dụng Playwright để click "Xem thêm" và load toàn bộ sản phẩm.
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

            # Click "Xem thêm" để load thêm sản phẩm
            prev_count = 0
            for round_idx in range(30): # max 30 clicks
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                    current_items = page.locator("div.product-item").count()

                    load_more_btn = page.locator("#div_Danh_Sach_San_Pham_loadMore_btn a")
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Click 'Xem thêm' lần {round_idx + 1} ({current_items} items)")
                        # Use evaluate to click, as it's a javascript:void(0) link
                        page.evaluate("document.querySelector('#div_Danh_Sach_San_Pham_loadMore_btn a').click()")
                        page.wait_for_timeout(3000) # Wait for AJAX

                        new_items = page.locator("div.product-item").count()
                        if new_items == prev_count:
                            logger.info(f"[{self.site_name}] Số sản phẩm không đổi. Dừng lại.")
                            break
                        prev_count = new_items
                    else:
                        logger.info(f"[{self.site_name}] Đã load hết sản phẩm sau {round_idx} vòng click.")
                        break
                except Exception as e:
                    logger.debug(f"[{self.site_name}] Lỗi vòng click Xem thêm: {e}")
                    break
            
            page.evaluate("window.scrollTo(0, 0);")
            page.wait_for_timeout(1000)

            product_containers = page.query_selector_all("div.product-info-container.product-item")
            logger.info(f"[{self.site_name}] Tìm thấy {len(product_containers)} product containers")

            limit = max_products if max_products else len(product_containers)
            logger.info(f"[{self.site_name}] Bắt đầu extract {min(limit, len(product_containers))} sản phẩm")

            for container in product_containers[:limit]:
                try:
                    product = self._extract_single_product_from_element(container)
                    if product:
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Error extracting product from container: {e}")
                    continue
            
            logger.info(f"[{self.site_name}] Đã cào được {len(products)} sản phẩm từ /dien-thoai")

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        return products

    def extract_product_info(self, page: Page, query: str, max_products: Optional[int] = None) -> List[Product]:
        products = []
        try:
            product_elements = page.query_selector_all("div.product-info-container.product-item")
            if not product_elements:
                for sel in ["div.product-item", "div.product-info-container", "div[class*='product']", ".item"]:
                    product_elements = page.query_selector_all(sel)
                    if product_elements:
                        break

            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")

            elements_to_process = product_elements if max_products is None else product_elements[:max_products]

            for element in elements_to_process:
                try:
                    product = self._extract_single_product_from_element(element)
                    if product:
                        if not self._is_phone_product(product.name, product.product_url):
                            logger.debug(f"Bỏ qua sản phẩm không phải điện thoại: {product.name[:50]}")
                            continue
                        products.append(product)
                except Exception as e:
                    logger.debug(f"Error extracting product: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error in extract_product_info: {e}")
        return products

    def _extract_comments_viettel(self, context, product_url: str) -> List[str]:
        page = context.new_page() 
        try:
            if not product_url:
                return []

            page.on("popup", lambda popup: popup.close())

            if not safe_goto(page, product_url, timeout=20000):
                return []

            page.wait_for_timeout(3000)
            page.evaluate("window.scrollBy(0, 1200);")
            page.wait_for_timeout(2000)

            max_clicks = 10
            for _ in range(max_clicks):
                try:
                    current_items = page.locator("div.cmt-item-content div.c").count()
                    load_more_btn = page.locator("div.cmt_loadmore a.btnAddCmt, div.cmt_loadmore a").first
                    
                    if load_more_btn.count() == 0 or not load_more_btn.is_visible():
                        break

                    logger.info(f"Đang bấm 'Xem thêm'... (Hiện có {current_items} câu hỏi)")
                    load_more_btn.click(force=True)

                    try:
                        page.wait_for_function(
                            f"() => document.querySelectorAll('div.cmt-item-content div.c').length > {current_items}",
                            timeout=4000
                        )
                        logger.info("Đã load thêm câu hỏi mới!")
                    except Exception:
                        logger.info("Không còn câu hỏi mới để load.")
                        break 

                except Exception as e:
                    logger.debug(f"Lỗi vòng lặp xem thêm: {e}")
                    break

            comments = []
            comment_elements = page.locator("div.cmt-item-content div.c").all()
            
            for el in comment_elements:
                try:
                    if "QUẢN TRỊ VIÊN" not in el.inner_html():
                        text = el.inner_text().strip()
                        text = text.strip('"').strip("'").strip()
                        if text and len(text) > 4:
                            comments.append(text)
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"Error extracting comments: {e}")
            return []
        finally:
            page.close()

        return comments
    
    def extract_comments_legacy(self, product_url: str) -> List[str]:
        return []


if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    print("=== BẮT ĐẦU TEST VIETTEL STORE SCRAPER ===")
    with BrowserManager(headless=False) as browser_manager:
        try:
            scraper = ViettelStoreScraper(browser_manager=browser_manager)
            query_keyword = input("Nhập từ khóa tìm kiếm (ví dụ: Oppo, iPhone): ").strip()
            
            max_results = None
            print(f"Đang tìm kiếm: '{query_keyword}'...")
            
            products = scraper.search(query=query_keyword, max_products=max_results)

            print(f"\nKết quả tìm thấy: {len(products)} sản phẩm\n" + "-" * 50)
            
            products_data = []
            for idx, prod in enumerate(products, 1):
                print(f"[{idx}] Tên: {prod.name} - Giá: {prod.price} - Comments: {len(prod.comments)}")
                if len(prod.comments) > 0:
                    print(f"   -> Comment mẫu: {prod.comments[0][:50]}...")
                prod_dict = {
                    "name": prod.name,
                    "price": prod.price,
                    "product_url": prod.product_url,
                    "image_url": prod.image_url,
                    "source": prod.source,
                    "comments": prod.comments
                }
                products_data.append(prod_dict)

            output_file = "viettelstore_results.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(products_data, f, ensure_ascii=False, indent=4)
            
            print(f"\nĐã xuất kết quả thành công ra file: {os.path.abspath(output_file)}")

        except Exception as e:
            print(f"Đã xảy ra lỗi: {e}")

    print("=== KẾT THÚC TEST ===")