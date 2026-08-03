"""
Base scraper dùng chung — tất cả các sàn đều dùng crawl4ai (AsyncWebCrawler).

Mỗi scraper con chỉ cần override:
  - _parse_products(html, query, max_products) -> List[Product]
  - _parse_comments(html) -> List[str]
Kèm thuộc tính: site_name, base_url, category_paths.
"""
import asyncio
import logging
import random
import re
import unicodedata
from abc import ABC, abstractmethod
from typing import List, Optional

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

from models.product import Product

logger = logging.getLogger(__name__)

DEFAULT_LOAD_MORE_JS = """
(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
const fire=el=>{if(!el)return;el.click();try{el.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}))}catch(e){}};
const sels=['.btn-filter-readmore','.button.btn-show-more.button__show-more-product',
'.view-more .see-more-btn','.view-more a','.see-more-btn','.btn-viewmore',
'.btn-show-more','.view-more','.load-more button','[class*="show-more"]','[class*="btn-seemore"]'];
const tryClick=()=>{let n=0;for(const sel of sels){document.querySelectorAll(sel).forEach(b=>{
if(!b||b.offsetParent===null)return;
const a=b.closest('a')||b;b.scrollIntoView({block:'center'});
fire(a);if(a!==b)fire(b);n++;});}return n;};
for(let i=0;i<40;i++){window.scrollBy(0,2500);await s(350);
if(window.scrollY+window.innerHeight>=document.body.scrollHeight)break;}
for(let i=0;i<60;i++){
if(!tryClick())break;
window.scrollTo(0,document.body.scrollHeight);await s(1500);}
window.scrollTo(0,document.body.scrollHeight);await s(500)})();
"""

# Danh sách User-Agent hiện đại (tránh Chrome/116 cũ dễ bị chặn)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
]

# Header giả lập trình duyệt thật (tiếng Việt)
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}

# Điều kiện chờ Cloudflare managed challenge tự giải xong trước khi crawl4ai
# chụp HTML (nếu không, ABID sẽ nhìn thấy script challenge và hard-fail).
# Trả về True khi challenge đã biến mất khỏi DOM.
CLOUDFLARE_WAIT_JS = (
    "js:() => {"
    "  const html = document.documentElement.outerHTML || '';"
    "  const hasChallenge = html.includes('/cdn-cgi/challenge-platform/')"
    "    || html.includes('challenge-form')"
    "    || html.includes('__cf_chl_f_tk=')"
    "    || (document.title && /just a moment|checking your browser/i.test(document.title));"
    "  return !hasChallenge;"
    "}"
)

# Script chạy trước mọi trang — che giấu dấu vết headless/automation
STEALTH_INIT_SCRIPTS = [
    """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = window.chrome || { runtime: {} };
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const mk = (n, d, f) => ({ name: n, description: d, filename: f, length: 0, item: () => null, namedItem: () => null, [Symbol.iterator]: function*() {} });
            const arr = [
                mk('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer'),
                mk('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'),
                mk('Native Client', '', 'internal-nacl-plugin'),
            ];
            arr.item = i => arr[i] || null;
            arr.namedItem = n => arr.find(p => p.name === n) || null;
            arr.refresh = () => {};
            return arr;
        }
    });
    Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 + Math.floor(Math.random() * 4) });
    if (navigator.connection) Object.defineProperty(navigator.connection, 'rtt', { get: () => 100 + Math.floor(Math.random() * 200) });
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
        window.navigator.permissions.query = (p) => p && p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(p);
    }
    """,
]


def normalize_text(s: str) -> str:
    """Bỏ dấu tiếng Việt, chuyển chữ thường để so khớp."""
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def clean_price(text: str) -> str:
    """Chuẩn hóa chuỗi giá: giữ lại con số + đơn vị, ví dụ 29.990.000đ."""
    if not text:
        return "Liên hệ"
    t = re.sub(r"\s+", " ", text.strip())
    t = re.sub(r"([0-9])[.,](?=[0-9]{3})", r"\1.", t)
    return t or "Liên hệ"


class BaseScraper(ABC):
    """Base class dùng crawl4ai cho mọi sàn."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.site_name: str = ""
        self.base_url: str = ""
        self.category_paths: List[str] = []
        # JS chạy trước khi parse trang danh mục — tự click nút "Xem thêm" nhiều lần.
        self.load_more_js: str = DEFAULT_LOAD_MORE_JS

        user_agent = random.choice(USER_AGENTS)
        viewport = random.choice(VIEWPORT_SIZES)

        self._browser_cfg = BrowserConfig(
            headless=headless,
            verbose=False,
            text_mode=True,
            enable_stealth=True,
            user_agent=user_agent,
            viewport=viewport,
            headers=dict(DEFAULT_HEADERS),
            init_scripts=list(STEALTH_INIT_SCRIPTS),
            extra_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--lang=vi-VN",
                "--window-size=1920,1080",
            ],
        )

    # ---------------------------------------------------------------- fetch
    async def _fetch_async(self, url: str, crawler: AsyncWebCrawler, wait_for: str = "", js_code: str = "") -> Optional[str]:
        cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            js_code=js_code or None,
            page_timeout=45000,
            wait_until="load",
            max_retries=2,
            simulate_user=True,
            override_navigator=True,
            magic=True,
            # Chờ Cloudflare challenge tự giải xong (nếu có) trước khi chụp HTML
            wait_for=wait_for or CLOUDFLARE_WAIT_JS,
            wait_for_timeout=30000,
        )
        try:
            result = await crawler.arun(url=url, config=cfg)
            if result and result.success:
                return result.html
            logger.warning(f"[{self.site_name}] crawl4ai fail: {url}")
        except asyncio.TimeoutError:
            logger.warning(f"[{self.site_name}] Timeout: {url}")
        except Exception as e:
            logger.warning(f"[{self.site_name}] Lỗi fetch {url}: {e}")
        return None

    def fetch_html(self, url: str, wait_for: str = "") -> Optional[str]:
        """Cào 1 URL, trả về HTML string (sync wrapper)."""
        async def _run():
            async with AsyncWebCrawler(config=self._browser_cfg) as c:
                return await self._fetch_async(url, c, wait_for)
        return asyncio.run(_run())

    def fetch_many(self, urls: List[str], wait_for: str = "") -> List[Optional[str]]:
        """Cào nhiều URL song song trong cùng 1 crawler (async)."""
        async def _run():
            async with AsyncWebCrawler(config=self._browser_cfg) as c:
                return await asyncio.gather(
                    *(self._fetch_async(u, c, wait_for) for u in urls)
                )
        if not urls:
            return []
        return asyncio.run(_run())

    # ---------------------------------------------------------------- parse
    @abstractmethod
    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        """Parse danh sách sản phẩm từ HTML — override ở từng sàn."""

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        """Parse nội dung bình luận từ HTML trang chi tiết — override nếu cần."""
        return []

    def _parse_product_detail(self, html: str, url: str = "") -> Optional[Product]:
        """Parse 1 trang chi tiết sản phẩm — dùng chung cho mọi sàn.

        Ưu tiên JSON-LD Product/Offer (chuẩn schema.org), fallback:
        h1/title cho tên, _find_price cho giá, og:image/img cho ảnh.
        Sàn nào có cấu trúc riêng có thể override.
        """
        import json
        soup = BeautifulSoup(html, "html.parser")

        name = ""
        price = "Liên hệ"
        image_url = ""
        price_is_zero = False
        def _fmt_price(raw_price):
            """Định dạng giá số -> chuỗi, đánh dấu nếu là 0."""
            nonlocal price_is_zero
            try:
                val = float(str(raw_price).replace(",", "").replace("đ", "").strip())
            except Exception:
                return str(raw_price)
            # JSON-LD đôi khi trả price=0 khi hết hàng / 'Liên hệ' — coi như chưa có giá
            if val <= 0:
                price_is_zero = True
                return "Liên hệ"
            return f"{int(val):,}đ".replace(",", ".")

        # 1) JSON-LD Product / Offer — nguồn chính xác nhất
        for ld in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(ld.get_text(strip=True))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            node = data
            if data.get("@graph") and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        node = item
                        break
            if not isinstance(node, dict) or node.get("@type") != "Product":
                continue
            if not name:
                name = (node.get("name") or "").strip()
            imgs = node.get("image") or []
            if isinstance(imgs, list) and imgs:
                first = imgs[0]
                image_url = first if isinstance(first, str) else (first.get("url") or "" if isinstance(first, dict) else "")
            elif isinstance(imgs, str):
                image_url = imgs
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                raw_price = offers.get("price")
                if raw_price is not None:
                    try:
                        price = f"{int(float(raw_price)):,}đ".replace(",", ".")
                    except Exception:
                        price = str(raw_price)
            if name and price != "Liên hệ":
                break

        # 2) Fallback tên từ h1 / title
        if not name:
            h1 = soup.select_one("h1")
            name = h1.get_text(" ", strip=True) if h1 else ""
        if not name:
            t = soup.select_one("title")
            name = (t.get_text(strip=True).split("|")[0] if t else "").strip()

        # 3) Fallback giá từ _find_price trên toàn trang
        if price == "Liên hệ":
            price = self._find_price(soup)

        # 4) Fallback ảnh từ og:image / thẻ img
        if not image_url:
            og = soup.select_one("meta[property='og:image']")
            if og and og.get("content"):
                image_url = og["content"].strip()
            else:
                image_url = self._img_from_soup(soup.select_one("img[src], img[data-src]"))

        if not name:
            return None
        canonical = soup.select_one("link[rel='canonical']")
        href = url or self._abs_url(self.base_url, canonical.get("href", "") if canonical else "")
        return Product(name=name, price=price, image_url=image_url,
                       product_url=href, source=self.site_name)

    # ---------------------------------------------------------------- helpers
    def _norm(self, s: str) -> str:
        return normalize_text(s)

    def _is_phone_product(self, name: str, product_url: str = "") -> bool:
        """Lọc sản phẩm không phải điện thoại."""
        if not name:
            return False
        norm_name = self._norm(name)
        norm_url = self._norm(product_url.replace("-", " ").replace("/", " "))
        excluded = [
            "tai nghe", "op lung", "sac du phong", "pin du phong", "cap sac",
            "loa", "may tinh bang", "tablet", "ipad", "laptop", "macbook",
            "dong ho", "smartwatch", "apple watch", "airpods", "phu kien",
            "bao da", "kinh cuong luc", "dan man hinh", "chuot", "ban phim",
            "the nho", "usb", "camera", "may anh", "tivi", "router", "modem",
            "sim", "goi cuoc", "tra gop", "balo", "gia do", "chan may",
        ]
        for kw in excluded:
            if kw in norm_name:
                return False
        if any(h in norm_url for h in ["dien thoai", "dien-thoai", "phone", "smartphone", "mobile"]):
            return True
        hints = [
            "iphone", "galaxy", "redmi", "poco", "xiaomi", "oppo", "vivo",
            "realme", "nokia", "huawei", "honor", "oneplus", "pixel", "zenfone",
            "dien thoai", "smartphone", "itel", "infinix", "tecno", "vsmart",
        ]
        if any(h in norm_name for h in hints):
            return True
        return True

    def _find_price(self, container) -> str:
        """Tìm giá trong 1 container: ưu tiên class price--show/.product__price,
        fallback phần tử ngắn chứa chữ số + 'đ'."""
        for sel in ("[class*='price--show']", ".product__price",
                    "[class*='special-price']", ".price"):
            el = container.select_one(sel)
            if el:
                t = el.get_text(" ", strip=True)
                if any(c.isdigit() for c in t):
                    return clean_price(t)
        for el in container.select("p, span, div, strong, b"):
            t = el.get_text(" ", strip=True)
            m = re.search(r"\d[\d.,]*\s*đ", t)
            if m:
                return clean_price(m.group(0))
        return "Liên hệ"

    @staticmethod
    def _img_from_soup(img) -> str:
        """Lấy URL ảnh từ thẻ <img> (data-src trước, fallback src)."""
        if img is None:
            return ""
        for attr in ("data-src", "data-original", "data-lazy", "src"):
            val = img.get(attr)
            if val:
                return val.strip()
        return ""

    @staticmethod
    def _abs_url(base: str, href: str) -> str:
        if not href:
            return ""
        href = href.strip()
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return base + href
        return href

    # ---------------------------------------------------------------- public API
    def search(self, query: str, max_products: int = 10, fetch_comments: bool = True) -> List[Product]:
        """Tìm kiếm sản phẩm — override get_search_url nếu cần."""
        from urllib.parse import quote
        url = f"{self.base_url}/search?q={quote(query)}"
        html = self.fetch_html(url)
        if not html:
            return []
        products = self._parse_products(html, query, max_products)
        if fetch_comments:
            self._attach_comments(products)
        return products

    def crawl_all_phones(self, max_products: Optional[int] = None) -> List[Product]:
        """Cào toàn bộ điện thoại từ category_paths."""
        all_products: List[Product] = []
        seen = set()

        async def _crawl():
            async with AsyncWebCrawler(config=self._browser_cfg) as c:
                for path in self.category_paths:
                    url = self.base_url + path
                    logger.info(f"[{self.site_name}] Crawl danh mục {url}")
                    html = await self._fetch_async(url, c, js_code=self.load_more_js)
                    if not html:
                        continue
                    for p in self._parse_products(html, "", 100000):
                        if p.product_url not in seen:
                            seen.add(p.product_url)
                            all_products.append(p)
                    logger.info(f"[{self.site_name}] {path} -> {len(all_products)} sp")
                return all_products

        products = asyncio.run(_crawl())
        if max_products:
            products = products[:max_products]
        return products

    def _attach_comments(self, products: List[Product], max_comments: int = 300) -> None:
        """Cào bình luận cho danh sách sản phẩm (async, song song)."""
        if not products:
            return
        urls = [p.product_url for p in products]

        async def _run():
            async with AsyncWebCrawler(config=self._browser_cfg) as c:
                htmls = await asyncio.gather(*(self._fetch_async(u, c) for u in urls))
                return htmls

        htmls = asyncio.run(_run())
        for prod, html in zip(products, htmls):
            if html:
                cmts = self._parse_comments(html, prod.product_url)
                prod.comments = cmts[:max_comments]
            logger.info(f"[{self.site_name}] {prod.name[:40]} -> {len(prod.comments)} comments")

    def product_dicts(self, products: List[Product]) -> List[dict]:
        """Chuyển List[Product] -> List[dict] để lưu DB."""
        return [
            {"name": p.name, "price": p.price, "image_url": p.image_url,
             "product_url": p.product_url, "source": p.source, "comments": p.comments}
            for p in products
        ]