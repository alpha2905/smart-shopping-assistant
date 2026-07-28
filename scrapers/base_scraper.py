import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from models.product import Product
from utils.browser import BrowserManager, Page, scroll_page
import time
import random

def random_delay(min_seconds: float = 1.5, max_seconds: float = 3.5):
    """
    Tạo độ trễ ngẫu nhiên để mô phỏng hành vi người dùng thật, 
    giảm tỷ lệ bị các trang web chặn (Anti-bot).
    """
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
        
logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all site scrapers."""

    def __init__(self, browser_manager: BrowserManager, headless: bool = True):
        self.browser_manager = browser_manager
        self.headless = headless
        self.site_name: str = ""
        self.base_url: str = ""

    @abstractmethod
    def search(self, query: str, max_products: int = 10) -> List[Product]:
        """
        Search for products on the site.
        
        Args:
            query: Search keyword
            max_products: Maximum number of products to return
            
        Returns:
            List of Product objects found
        """
        pass

    @abstractmethod
    def extract_product_info(self, page: Page, query: str, max_products: int) -> List[Product]:
        """
        Extract product information from the search results page.
        
        Args:
            page: Playwright page object with loaded search results
            query: Original search query
            max_products: Maximum number of products to extract
            
        Returns:
            List of Product objects
        """
        pass

    def extract_comments(self, page: Page, product_url: str) -> List[str]:
        """
        Extract comments/reviews from a product detail page.
        Override in subclass if the site supports comments.
        
        Args:
            page: Playwright page object
            product_url: URL of the product detail page
            
        Returns:
            List of comment strings
        """
        return []

    def get_search_url(self, query: str) -> str:
        """
        Build the search URL for the site.
        Override in subclass if custom URL pattern is needed.
        
        Args:
            query: Search keyword
            
        Returns:
            Full search URL
        """
        import urllib.parse
        return f"{self.base_url}/search?q={urllib.parse.quote(query)}"

    def safe_extract(self, page: Page, selector: str, attribute: str = None, default: str = "") -> str:
        """
        Safely extract text or attribute from a page element.
        
        Args:
            page: Playwright page object
            selector: CSS selector
            attribute: If provided, extract this attribute instead of text
            default: Default value if element not found
            
        Returns:
            Extracted text or attribute value
        """
        try:
            element = page.query_selector(selector)
            if element:
                if attribute:
                    return element.get_attribute(attribute) or default
                return element.inner_text().strip() or default
            return default
        except Exception as e:
            logger.debug(f"Error extracting {selector}: {e}")
            return default

    def safe_extract_all(self, page: Page, selector: str, attribute: str = None) -> List[str]:
        """
        Safely extract text or attribute from multiple page elements.
        
        Args:
            page: Playwright page object
            selector: CSS selector
            attribute: If provided, extract this attribute instead of text
            
        Returns:
            List of extracted strings
        """
        try:
            elements = page.query_selector_all(selector)
            results = []
            for element in elements:
                try:
                    if attribute:
                        val = element.get_attribute(attribute)
                    else:
                        val = element.inner_text().strip()
                    if val:
                        results.append(val)
                except Exception:
                    continue
            return results
        except Exception as e:
            logger.debug(f"Error extracting all {selector}: {e}")
            return []

    def is_search_page_valid(self, page: Page) -> bool:
        """
        Check if the search results page loaded correctly and has any content.
        Override in subclass for site-specific validation.
        
        Returns:
            True if page has content, False if blocked or empty
        """
        try:
            body_text = page.inner_text("body").strip().lower()
            # Chỉ check các keyword block rõ ràng, bỏ "robot" vì dễ false positive
            blocked_keywords = ["captcha", "access denied", "429", "too many requests"]
            for keyword in blocked_keywords:
                if keyword in body_text:
                    logger.warning(f"[{self.site_name}] Page appears to be blocked (keyword: {keyword})")
                    return False
            return True
        except Exception as e:
            logger.debug(f"[{self.site_name}] Error checking page validity: {e}")
            return False

    def wait_and_scroll(self, page: Page, initial_wait: int = 3000, scroll_times: int = 3) -> None:
        """Wait for page to load initial content and then scroll to trigger lazy loading."""
        try:
            page.wait_for_timeout(initial_wait)
            scroll_page(page, scroll_times=scroll_times, delay=800)
            # Small extra wait after scrolling
            page.wait_for_timeout(1000)
        except Exception as e:
            logger.debug(f"[{self.site_name}] Error during wait_and_scroll: {e}")
