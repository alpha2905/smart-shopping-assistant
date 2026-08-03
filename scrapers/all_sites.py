"""
Gộp 8 scraper sàn điện thoại — TẤT CẢ dùng crawl4ai.
Mỗi sàn override _parse_products / _parse_comments.
"""
from typing import List, Optional
from bs4 import BeautifulSoup
from models.product import Product
from scrapers.base_scraper import BaseScraper, clean_price, normalize_text


class TGDDScraper(BaseScraper):
    """Thế Giới Di Động"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "Thế Giới Di Động"
        self.base_url = "https://www.thegioididong.com"
        self.category_paths = ["/dtdd"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for li in soup.select("li.item"):
            a = li.select_one("a.main-contain") or li.select_one("a[href*='/dtdd/']")
            if not a:
                continue
            name = (a.get("data-name") or "").strip()
            if not name:
                h3 = li.select_one("h3")
                name = h3.get_text(strip=True) if h3 else ""
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = "Liên hệ"
            raw = a.get("data-price")
            if raw:
                try:
                    price = f"{int(float(raw)):,}đ".replace(",", ".")
                except Exception:
                    price = raw
            if price == "Liên hệ":
                pe = li.select_one(".price, strong.price, .box-price")
                if pe:
                    price = clean_price(pe.get_text(" ", strip=True))
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(li.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select(".box-user, .cmt-item, .item-cmt"):
            n = block.select_one("span.name, b.name, .cmt-name")
            t = block.select_one("p.cmt-txt, .comment-text, .cmt-content")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3:
                    full = f"{n.get_text(strip=True)}: {text}" if n else text
                    if full not in comments:
                        comments.append(full)
        for t in soup.select("p.cmt-txt"):
            text = t.get_text(" ", strip=True)
            if text and len(text) > 3 and text not in comments:
                comments.append(text)
        return comments


class FPTScraper(BaseScraper):
    """FPT Shop"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "FPT Shop"
        self.base_url = "https://fptshop.com.vn"
        self.category_paths = ["/dien-thoai"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for div in soup.select("div[class*='group']"):
            a = div.select_one("a[href*='/dien-thoai/']")
            h3 = div.select_one("h3")
            if not a or not h3:
                continue
            name = (a.get("data-name") or h3.get_text(strip=True) or "").strip()
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = self._find_price(div)
            if price == "Liên hệ":
                import re
                slug = href.rsplit("/", 1)[-1]
                m = re.search(r'"productUrl"[^}]*?%s[^}]*?"price"\s*:\s*"?([\d.]+)' % re.escape(slug), html)
                if not m:
                    m = re.search(r'"price"\s*:\s*"?([\d.]+)"?[^}]*?"productUrl"[^}]*?%s' % re.escape(slug), html)
                if m:
                    price = f"{int(float(m.group(1))):,}đ".replace(",", ".")
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(div.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for div in soup.select("div[class*='text-textOnWhitePrimary']"):
            text = div.get_text(" ", strip=True)
            if text and len(text) > 3 and "bị ẩn" not in text and text not in comments:
                comments.append(text)
        return comments


class CellphoneSScraper(BaseScraper):
    """CellphoneS"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "CellphoneS"
        self.base_url = "https://cellphones.com.vn"
        self.category_paths = ["/mobile.html", "/dien-thoai-chinh-hang.html"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for div in soup.select("div.product-info-container"):
            a = div.select_one("a.product__link") or div.select_one("a[href*='dien-thoai']") or div.select_one("a[href]")
            if not a:
                continue
            img = a.select_one("img")
            name = (img.get("alt") if img else "") or ""
            if not name:
                n3 = div.select_one("h3")
                name = n3.get_text(strip=True) if n3 else ""
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = self._find_price(div)
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(img or div.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for item in soup.select("div.boxReview-comment-item"):
            n = item.select_one("span.name")
            t = item.select_one("div.comment-content p, p.comment-content")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3:
                    full = f"{n.get_text(strip=True)}: {text}" if n else text
                    if full not in comments:
                        comments.append(full)
        return comments


class HoangHaScraper(BaseScraper):
    """Hoàng Hà Mobile"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "Hoàng Hà Mobile"
        self.base_url = "https://hoanghamobile.com"
        self.category_paths = ["/dien-thoai-di-dong"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for item in soup.select("div.pj16-item, .item"):
            h3 = item.select_one("h3")
            a = item.select_one("a[href]")
            if not h3 or not a:
                continue
            name = (h3.get_text(strip=True) or a.get("title") or "").strip()
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = "Liên hệ"
            pe = item.select_one("div.price strong, .price")
            if pe:
                pt = pe.get_text(" ", strip=True)
                if any(c.isdigit() for c in pt):
                    price = clean_price(pt)
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(item.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select("div.comment-block"):
            if block.select_one("span.qtv"):
                continue
            n = block.select_one(".comment-name, span.name")
            t = block.select_one("div.comment-text")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3:
                    full = f"{n.get_text(strip=True)}: {text}" if n else text
                    if full not in comments:
                        comments.append(full)
        return comments


class DiDongVietScraper(BaseScraper):
    """Di Động Việt — card: li.h-full a/product-card (Next.js render sẵn)."""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "Di Động Việt"
        self.base_url = "https://didongviet.vn"
        self.category_paths = ["/dien-thoai"]

    def _parse_product_detail(self, html: str, url: str = "") -> Optional[Product]:
        """Parse 1 trang chi tiết sản phẩm — ưu tiên JSON-LD Product, fallback HTML."""
        import json
        import re as _re
        soup = BeautifulSoup(html, "html.parser")

        name = ""
        price = "Liên hệ"
        image_url = ""

        # 1) JSON-LD Product block — nguồn chính xác nhất
        for ld in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(ld.get_text(strip=True))
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("@type") != "Product":
                continue
            name = (data.get("name") or "").strip()
            imgs = data.get("image") or []
            if isinstance(imgs, list) and imgs:
                image_url = imgs[0]
            elif isinstance(imgs, str):
                image_url = imgs
            offers = data.get("offers") or {}
            raw_price = offers.get("price") if isinstance(offers, dict) else None
            if raw_price is not None:
                try:
                    price = f"{int(float(raw_price)):,}đ".replace(",", ".")
                except Exception:
                    price = str(raw_price)
            break

        # 2) Fallback tên từ h1 / title
        if not name:
            h1 = soup.select_one("h1")
            name = h1.get_text(" ", strip=True) if h1 else ""
        if not name:
            t = soup.select_one("title")
            name = (t.get_text(strip=True).split("|")[0] if t else "").strip()

        # 3) Fallback giá từ khối "Giá sản phẩm ... / MUA NGAY" (bỏ qua line-through giá cũ)
        if price == "Liên hệ":
            for box in soup.select("div.fixed, div[class*='z-40']"):
                t = box.get_text(" ", strip=True)
                m = _re.search(r"Giá sản phẩm\s*([\d][\d.,]*\s*đ)", t)
                if m:
                    price = clean_price(m.group(1))
                    break
        if price == "Liên hệ":
            # Khối khuyến mãi có giá thật đứng trước giá cũ
            for el in soup.select("span, p, strong, b, div"):
                cls = el.get("class") or []
                if "line-through" in cls:
                    continue
                t = el.get_text(" ", strip=True)
                m = _re.search(r"[\d][\d.,]*\s*đ", t)
                if m and el.find_parent(class_="line-through") is None:
                    price = clean_price(m.group(0))
                    break

        # 4) Fallback ảnh từ thẻ img
        if not image_url:
            img = soup.select_one("meta[property='og:image']")
            if img and img.get("content"):
                image_url = img["content"].strip()
            else:
                image_url = self._img_from_soup(soup.select_one("img[src], img[data-src]"))

        if not name:
            return None
        href = url or self._abs_url(self.base_url, soup.select_one("link[rel='canonical']").get("href", "") if soup.select_one("link[rel='canonical']") else "")
        return Product(name=name, price=price, image_url=image_url,
                       product_url=href, source=self.site_name)

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        import re as _re
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for item in soup.select("li.h-full a[href*='/dien-thoai/']"):
            img = item.select_one("img[alt]")
            name = (img.get("alt") or "").strip() if img else ""
            if not name:
                t = item.get_text(" ", strip=True)
                name = t.split(" ")[0] if t else ""
            href = self._abs_url(self.base_url, item.get("href", ""))
            if not name or not href:
                continue
            price = "Liên hệ"
            # Giá thật đứng trước giá cũ (line-through); bỏ qua phần tử khuyến mãi/ảnh sticker
            for el in item.select("span, p, strong, b, div"):
                cls = el.get("class") or []
                if "line-through" in cls:
                    continue
                t = el.get_text(" ", strip=True)
                m = _re.search(r"[\d][\d.,]*\s*đ", t)
                if m:
                    price = clean_price(m.group(0))
                    break
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(img),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        import re
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select(".comment-item, .cmt-item, .box-comment"):
            t = block.select_one("p, .content, .cmt-content")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3 and text not in comments:
                    comments.append(text)
        for m in re.finditer(r'"content"\s*:\s*"([^"]{10,600})"', html):
            text = m.group(1).encode().decode("unicode_escape", errors="ignore")
            if text and text not in comments:
                comments.append(text)
        return comments


class ViettelStoreScraper(BaseScraper):
    """Viettel Store"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "Viettel Store"
        self.base_url = "https://viettelstore.vn"
        self.category_paths = ["/dien-thoai"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for item in soup.select("div.product-item, div.item, li.product"):
            a = item.select_one("a[href]")
            if not a:
                continue
            ne = item.select_one("h3, .name, [class*='name']")
            name = ne.get_text(strip=True) if ne else ""
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = "Liên hệ"
            pe = item.select_one(".price, span[class*='price'], .price-box")
            if pe:
                pt = pe.get_text(" ", strip=True)
                if any(c.isdigit() for c in pt):
                    price = clean_price(pt)
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(item.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select(".comment, .review-item, .comment-item"):
            t = block.select_one("p, .content, .text")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3 and text not in comments:
                    comments.append(text)
        return comments


class ClickBuyScraper(BaseScraper):
    """ClickBuy — card: div.list-products__item (render sẵn)."""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "ClickBuy"
        self.base_url = "https://clickbuy.com.vn"
        self.category_paths = ["/dien-thoai"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for item in soup.select("div.list-products__item"):
            a = item.select_one("a[href]")
            n = item.select_one("strong.title_name")
            if not a or not n:
                continue
            name = n.get_text(strip=True)
            href = self._abs_url(self.base_url, a.get("href", ""))
            if not name or not href:
                continue
            price = "Liên hệ"
            pe = item.select_one("ins.new-price")
            if pe:
                pt = pe.get_text(" ", strip=True)
                if any(c.isdigit() for c in pt):
                    price = clean_price(pt)
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(item.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select(".comment-item, .cmt-item, .review-item"):
            t = block.select_one("p, .content")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3 and text not in comments:
                    comments.append(text)
        return comments


class MobileCityScraper(BaseScraper):
    """MobileCity — card: div.product-list-item (render sẵn)."""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.site_name = "MobileCity"
        self.base_url = "https://mobilecity.vn"
        self.category_paths = ["/dien-thoai"]

    def _parse_products(self, html: str, query: str, max_products: int) -> List[Product]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[Product] = []
        for item in soup.select("div.product-list-item"):
            ne = item.select_one("p.name a") or item.select_one("p.name")
            if not ne:
                continue
            name = ne.get_text(strip=True)
            a = ne if ne.name == "a" else ne.select_one("a[href]") or item.select_one("a[href]")
            href = self._abs_url(self.base_url, a.get("href", "")) if a else ""
            if not name or not href:
                continue
            price = "Liên hệ"
            pe = item.select_one("p.price")
            if pe:
                pt = pe.get_text(" ", strip=True)
                if any(c.isdigit() for c in pt):
                    price = clean_price(pt)
            if query and normalize_text(query) not in normalize_text(name):
                continue
            out.append(Product(name=name, price=price,
                               image_url=self._img_from_soup(item.select_one("img")),
                               product_url=href, source=self.site_name))
        return out

    def _parse_comments(self, html: str, url: str = "") -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        comments: List[str] = []
        for block in soup.select(".comment-item, .cmt-item, .review-item"):
            t = block.select_one("p, .content")
            if t:
                text = t.get_text(" ", strip=True)
                if text and len(text) > 3 and text not in comments:
                    comments.append(text)
        return comments


ALL_SCRAPERS = [
    TGDDScraper,
    FPTScraper,
    CellphoneSScraper,
    HoangHaScraper,
    DiDongVietScraper,
    ViettelStoreScraper,
    ClickBuyScraper,
    MobileCityScraper,
]
