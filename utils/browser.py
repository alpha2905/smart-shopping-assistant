import logging
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, Page, Playwright
import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
]

logger = logging.getLogger(__name__)


class BrowserManager:
    """Manages Playwright browser lifecycle and provides page instances."""

    def __init__(self, headless: bool = True, timeout: int = 20000):
        self.headless = headless
        self.timeout = timeout
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context = None

    def __enter__(self):
        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--lang=vi-VN",
            "--disable-notifications",
            "--disable-popup-blocking",
            # Giảm thiểu phát hiện headless
            "--disable-setuid-sandbox",
            "--window-size=1920,1080",
            "--start-maximized",
        ]

        # Playwright xử lý headless mode nội bộ.
        # Không pass --headless=new qua args vì có thể conflict với Playwright.
        # Playwright >= 1.48 dùng headless="shell" cho chế độ headless mới.
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            env={"LANG": "vi_VN.UTF-8", "LC_ALL": "vi_VN.UTF-8"}
        )
        self._context = self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORT_SIZES),
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            no_viewport=False,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "Connection": "keep-alive",
                "Cache-Control": "max-age=0",
            },
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def new_page(self) -> Page:
        """Create a new browser page with random user-agent and anti-detection settings."""
        page = self._context.new_page()
        page.set_default_timeout(self.timeout)

        # Block unnecessary resources to speed up page loading
        page.route("**/*", lambda route: (
            route.abort()
            if route.request.resource_type in {"font", "media", "image"}
            else route.continue_()
        ))

        page.add_init_script("""
            // Override navigator.webdriver (Playwright already does this, but be safe)
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override navigator.plugins with realistic plugin-like objects
            // (headless Chrome has empty plugins array which is a signal)
            const makePlugin = (name, desc, filename) => ({
                name,
                description: desc,
                filename,
                length: 0,
                item: () => null,
                namedItem: () => null,
                [Symbol.iterator]: function*() {}
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const arr = [
                        makePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer'),
                        makePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'),
                        makePlugin('Native Client', '', 'internal-nacl-plugin'),
                    ];
                    arr.item = i => arr[i] || null;
                    arr.namedItem = name => arr.find(p => p.name === name) || null;
                    arr.refresh = () => {};
                    return arr;
                }
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['vi-VN', 'vi', 'en-US', 'en']
            });

            // Override navigator.platform
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });

            // Override navigator.permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({state: Notification.permission}) :
                    originalQuery(parameters)
            );

            // Override connection rtt to look real
            if (navigator.connection) {
                Object.defineProperty(navigator.connection, 'rtt', {
                    get: () => 100 + Math.floor(Math.random() * 200)
                });
            }

            // Override hardwareConcurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 4 + Math.floor(Math.random() * 4)
            });

            // Override deviceMemory (not present in headless)
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 4 + Math.floor(Math.random() * 4)
            });
        """)

        return page

    @property
    def browser(self) -> Browser:
        return self._browser


def wait_for_page_load(page: Page, timeout: int = 15000) -> None:
    """Wait for page to be fully loaded safely using domcontentloaded."""
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass


def safe_goto(page: Page, url: str, timeout: int = 45000, wait_until: str = "domcontentloaded") -> bool:
    """Navigate to URL with error handling and systematic retry logic."""
    max_retries = 3
    # Different strategies to try on failure, starting with the default.
    wait_strategies = [wait_until, "load", "commit"]

    for attempt in range(max_retries):
        current_wait_strategy = wait_strategies[attempt % len(wait_strategies)]
        try:
            # On retries, add a random delay
            if attempt > 0:
                delay = random.randint(2500, 6000)
                logger.info(f"Retrying ({attempt}/{max_retries}) for {url} after {delay}ms delay using strategy '{current_wait_strategy}'...")
                page.wait_for_timeout(delay)
            
            response = page.goto(url, wait_until=current_wait_strategy, timeout=timeout)
            
            if response and response.status < 400:
                # Success
                wait_for_page_load(page, timeout=min(timeout, 15000))
                return True
            else:
                status = response.status if response else 'N/A'
                logger.warning(f"Attempt {attempt + 1}/{max_retries}: Got HTTP {status} for {url} with strategy '{current_wait_strategy}'")
                
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url} with strategy '{current_wait_strategy}': {e.__class__.__name__}")
            if attempt == max_retries - 1:
                 logger.error(f"All retries failed for {url}. Last error: {e}", exc_info=False)

    return False


def scroll_page(page: Page, scroll_times: int = 3, delay: int = 1000) -> None:
    """Scroll down the page to trigger lazy loading of images and content."""
    for i in range(scroll_times):
        try:
            page.evaluate(f"window.scrollBy(0, {500 + i * 300})")
            page.wait_for_timeout(delay)
        except Exception as e:
            logger.debug(f"Scroll error at step {i}: {e}")
            break
