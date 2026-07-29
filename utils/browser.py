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

    def __init__(self, headless: bool = True, timeout: int = 45000):
        self.headless = headless
        self.timeout = timeout
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

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
        ]
        # Add --headless=new via args for newer Chromium stealth headless mode,
        # instead of setting headless=True on the launch object (which is easily detectable).
        if self.headless:
            launch_args.append("--headless=new")

        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=launch_args,
            env={"LANG": "vi_VN.UTF-8", "LC_ALL": "vi_VN.UTF-8"}
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def new_page(self) -> Page:
        """Create a new browser page with random user-agent and anti-detection settings."""
        selected_user_agent = random.choice(USER_AGENTS)
        selected_viewport = random.choice(VIEWPORT_SIZES)

        page = self._browser.new_page(
            user_agent=selected_user_agent,
            viewport=selected_viewport,
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
        page.set_default_timeout(self.timeout)

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
    """Navigate to URL with error handling and retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = page.goto(url, wait_until=wait_until, timeout=timeout)
            if response and response.status < 400:
                wait_for_page_load(page, timeout=min(timeout, 15000))
                return True
            logger.warning(f"Attempt {attempt + 1}: Got status {response.status if response else 'None'} for {url}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt == max_retries - 1:
                return False
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
