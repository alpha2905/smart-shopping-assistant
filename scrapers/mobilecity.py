import sys
import os
import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from models.product import Product
from scrapers.base_scraper import BaseScraper
from utils.browser import BrowserManager, Page, safe_goto

logger = logging.getLogger(__name__)


class MobileCityScraper(BaseScraper):
    """Scraper for MobileCity (https://mobilecity.vn)"""

    def __init__(self, browser_manager: BrowserManager):
        super().__init__(browser_manager)
        self.site_name = "MobileCity"
        self.base_url = "https://mobilecity.vn"

    def get_search_url(self, query: str) -> str:
        return f"{self.base_url}/tim-kiem?keyword={urllib.parse.quote(query)}"

    def search(self, query: str, max_products: int = 10, fetch_comments: bool = True) -> List[Product]:
        products = []
        page = self.browser_manager.new_page()
        try:
            search_url = self.get_search_url(query)
            logger.info(f"Searching {self.site_name}: {search_url}")
            
            if not safe_goto(page, search_url, timeout=45000):
                return products

            if not self.is_search_page_valid(page):
                return products

            self.wait_and_scroll(page, initial_wait=3000, scroll_times=2)
            products = self.extract_product_info(page, query, max_products)
        except Exception as e:
            logger.error(f"Error scraping {self.site_name}: {e}")
        finally:
            page.close()
        return products

    def extract_product_info(self, page: Page, query: str, max_products: Optional[int]) -> List[Product]:
        products = []
        try:
            product_elements = page.locator(".product-list-item").all()
            logger.info(f"Found {len(product_elements)} product elements on {self.site_name}")
            
            limit = max_products if max_products is not None else len(product_elements)
            for element in product_elements[:limit]:
                try:
                    name_elem = element.locator(".product-item-info .name a")
                    name = name_elem.inner_text().strip() if name_elem.count() > 0 else ""
                    link = name_elem.get_attribute("href") if name_elem.count() > 0 else ""
                    
                    price_elem = element.locator(".product-item-info .price")
                    price = price_elem.inner_text().strip() if price_elem.count() > 0 else "Liên hệ"
                    
                    img_elem = element.locator(".product-item-image img")
                    image_url = ""
                    if img_elem.count() > 0:
                        image_url = img_elem.get_attribute("data-original-src") or img_elem.get_attribute("src") or ""
                    
                    product_url = link
                    if link and not link.startswith("http"):
                        product_url = self.base_url + link if link.startswith("/") else self.base_url + "/" + link
                    
                    if not self._is_phone_product(name, product_url):
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
        except Exception as e:
            logger.warning(f"Error in extract_product_info for {self.site_name}: {e}")
        return products

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """
        Cào TẤT CẢ sản phẩm điện thoại từ trang danh mục của MobileCity.
        Click "Xem thêm" để load hết sản phẩm.
        """
        products = []
        page = self.browser_manager.new_page()
        try:
            url = f"{self.base_url}/dien-thoai"
            logger.info(f"Crawling ALL phones from {self.site_name}: {url}")

            if not safe_goto(page, url, timeout=60000, wait_until="domcontentloaded"):
                logger.warning(f"Failed to load /dien-thoai page for {self.site_name}")
                return products

            # Click "Xem thêm" để load hết sản phẩm
            load_more_selector = "a#product_view_more, a.more:has-text('Xem thêm')"
            for _ in range(30): # Giới hạn 30 lần click
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1000)
                    
                    load_more_btn = page.locator(load_more_selector)
                    if load_more_btn.count() > 0 and load_more_btn.first.is_visible():
                        logger.info(f"[{self.site_name}] Clicking 'Xem thêm'...")
                        load_more_btn.first.click()
                        page.wait_for_timeout(2500) # Chờ AJAX load
                    else:
                        logger.info(f"[{self.site_name}] Không còn nút 'Xem thêm', đã load hết sản phẩm.")
                        break
                except Exception as e:
                    logger.warning(f"[{self.site_name}] Lỗi khi click 'Xem thêm': {e}")
                    break
            
            # Sau khi load hết, extract tất cả sản phẩm
            products = self.extract_product_info(page, "", max_products)

        except Exception as e:
            logger.error(f"Error crawling all phones from {self.site_name}: {e}", exc_info=True)
        finally:
            page.close()

        if max_products:
            products = products[:max_products]
            
        logger.info(f"[{self.site_name}] Crawled a total of {len(products)} products.")
        return products

    def scrape_price_from_url(self, product_url: str) -> Optional[Product]:
        """
        Cào tên và giá từ một trang sản phẩm cụ thể của MobileCity.
        """
        page = self.browser_manager.new_page()
        try:
            if not safe_goto(page, product_url, timeout=45000):
                logger.warning(f"[{self.site_name}] Không thể tải trang sản phẩm: {product_url}")
                return None

            # Chờ cho tên sản phẩm và giá xuất hiện
            page.wait_for_selector("h1.name, .price-box .price", timeout=15000)

            name_el = page.query_selector("h1.name")
            name = name_el.inner_text().strip() if name_el else ""

            price_el = page.query_selector(".price-box .price")
            price = price_el.inner_text().strip() if price_el else "Liên hệ"
            
            img_el = page.query_selector(".product-image-gallery img")
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
        comments = []
        try:
            if not product_url: return []
            if not safe_goto(page, product_url, timeout=45000): return []
            
            page.wait_for_load_state("networkidle")
            
            load_more_selector = "a.btn-view-more-comment"
            for _ in range(20):
                try:
                    btn = page.locator(load_more_selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click()
                        page.wait_for_timeout(1500)
                    else:
                        break
                except Exception:
                    break
            
            comment_elements = page.locator("div.comment-item div.content").all()
            for el in comment_elements:
                text = el.inner_text().strip()
                if text and text not in comments:
                    comments.append(text)
        except Exception as e:
            logger.debug(f"Error extracting comments from {product_url}: {e}")
        return comments

    def extract_all_comments_multithreaded(self, products: List[Product], max_workers: int = 4, max_comments: int = 300) -> List[dict]:
        products_data = []
        product_dicts = [{"name": p.name, "price": p.price, "image_url": p.image_url, "product_url": p.product_url, "source": p.source, "comments": []} for p in products]

        def _fetch_comments_for_product(prod_dict: dict) -> dict:
            page = self.browser_manager.new_page()
            try:
                comments = self.extract_comments(page, prod_dict["product_url"])
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