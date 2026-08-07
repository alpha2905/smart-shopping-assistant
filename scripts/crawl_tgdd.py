# -*- coding: utf-8 -*-
"""
Crawl toàn bộ sản phẩm điện thoại từ https://www.thegioididong.com/dtdd
Lấy: tên, giá, hình, link, bình luận cho TẤT CẢ sản phẩm.

Nhanh gấp nhiều lần: dùng AJAX endpoint /Category/FilterProductBox để lấy toàn bộ
danh sách sản phẩm (không cần browser/scroll), chỉ dùng crawl4ai cho trang chi tiết
để lấy bình luận.
"""
import argparse
import asyncio
import json
import logging
import sys
import os
import time
import urllib.parse
import urllib.request
from typing import List, Tuple

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("crawl_tgdd")

from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

from models.product import Product

BASE = "https://www.thegioididong.com"
CATE_URL = BASE + "/dtdd"
CATE_ID = "42"

# JS cho trang chi tiết: cuộn xuống vùng đánh giá + click "Xem thêm đánh giá" nhiều lần
LOAD_COMMENTS_JS = """
(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
const cnt=sel=>document.querySelectorAll(sel).length;
const btn=()=>document.querySelector('.btn-cmt-larger10');
for(let i=0;i<30;i++){
  window.scrollTo(0,document.body.scrollHeight);await s(700);
  const b=btn();
  if(!b||b.offsetParent===null)break;
  try{b.click()}catch(e){}
  try{b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}))}catch(e){}
  await s(700);
  if(cnt('ul.comment-list li.par')>0&&cnt('ul.comment-list li.par')>=80)break;
}
window.scrollTo(0,0);await s(400)})();
"""


def fetch_ajax_page(pi: int, ps: int = 20) -> Tuple[int, str, dict]:
    """Gọi AJAX FilterProductBox. Trả (total, listproducts_html, raw_json)."""
    url = f"{BASE}/Category/FilterProductBox?c={CATE_ID}&pi={pi}&ps={ps}"
    data = urllib.parse.urlencode({
        "IsParentCate": "False",
        "IsShowCompare": "True",
        "IsAffiliate": "False",
        "prevent": "True",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": CATE_URL,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    resp = urllib.request.urlopen(req, timeout=30)
    d = json.loads(resp.read().decode("utf-8", errors="replace"))
    return int(d.get("total") or 0), d.get("listproducts") or "", d


def parse_products_from_html(html: str, base: str) -> List[Product]:
    """Parse name/price/image/link từ HTML danh mục TGDD (trang chính hoặc AJAX listproducts)."""
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
        href = a.get("href", "")
        if href and href.startswith("/"):
            href = base + href
        if not name or not href:
            continue
        price = "Liên hệ"
        raw = a.get("data-price")
        if raw:
            try:
                price = f"{int(float(raw)):,}đ".replace(",", ".")
            except Exception:
                price = raw
        img = li.select_one("img")
        img_url = ""
        if img:
            for attr in ("data-src", "data-original", "data-lazy", "src"):
                val = img.get(attr)
                if val:
                    img_url = val.strip()
                    break
        out.append(Product(name=name, price=price, image_url=img_url,
                           product_url=href, source="Thế Giới Di Động"))
    # de-dup giữ link
    seen = set()
    uniq = []
    for p in out:
        if p.product_url not in seen:
            seen.add(p.product_url)
            uniq.append(p)
    return uniq


def fetch_all_products(max_pages: int = 30, sleep: float = 0.6) -> List[Product]:
    """Lấy toàn bộ sản phẩm qua AJAX pagination (pi=0,1,2,...)."""
    all_products: List[Product] = []
    seen_urls = set()
    total: int | None = None
    stale = 0

    for pi in range(max_pages):
        try:
            total, html, _ = fetch_ajax_page(pi)
        except Exception as e:
            logger.warning(f"pi={pi} lỗi: {e}; thử lại 1 lần...")
            time.sleep(2)
            try:
                total, html, _ = fetch_ajax_page(pi)
            except Exception as e2:
                logger.warning(f"pi={pi} lỗi lần 2: {e2}; bỏ qua")
                break

        # Trang hết dữ liệu: server trả total=0 & list rỗng
        if not html or len(parse_products_from_html(html, BASE)) == 0:
            logger.info(f"pi={pi}: hết dữ liệu (total={total}) -> dừng phân trang")
            break

        products = parse_products_from_html(html, BASE)
        new_on_page = 0
        for p in products:
            if p.product_url not in seen_urls:
                seen_urls.add(p.product_url)
                all_products.append(p)
                new_on_page += 1

        logger.info(f"pi={pi}: total={total} parsed={len(products)} new={new_on_page} "
                    f"cumulative={len(all_products)}")

        if new_on_page == 0:
            stale += 1
            if stale >= 2:
                logger.info("Không còn sản phẩm mới -> dừng phân trang")
                break
        else:
            stale = 0

        # Dừng sớm nếu đã thu đủ (chỉ khi total > 0 hợp lệ)
        if total and total > 0 and len(all_products) >= total:
            logger.info(f"Đã đủ {len(all_products)} >= total {total}")
            break

        time.sleep(sleep)

    if total is None:
        logger.warning("Không xác định được total; lấy được %d sản phẩm", len(all_products))
    return all_products


def parse_comments_from_html(html: str) -> List[str]:
    """Parse bình luận từ trang chi tiết sản phẩm TGDD."""
    soup = BeautifulSoup(html, "html.parser")
    comments: List[str] = []
    # 1) Bình luận chính: li.par trong ul.comment-list (TGDD hiện tại)
    for block in soup.select("ul.comment-list li.par"):
        n = block.select_one(".cmt-top-name")
        t = block.select_one("p.cmt-txt")
        if t:
            text = t.get_text(" ", strip=True)
            if text and len(text) > 3:
                full = f"{n.get_text(strip=True)}: {text}" if n else text
                if full not in comments:
                    comments.append(full)
    # 2) Fallback: các khối bình luận cũ
    for block in soup.select(".box-user, .cmt-item, .item-cmt, .user-cmt, .cmt-item-detail"):
        n = block.select_one("span.name, b.name, .cmt-name, .name-cmt")
        t = block.select_one("p.cmt-txt, .comment-text, .cmt-content, p.content-cmt")
        if t:
            text = t.get_text(" ", strip=True)
            if text and len(text) > 3:
                full = f"{n.get_text(strip=True)}: {text}" if n else text
                if full not in comments:
                    comments.append(full)
    # 3) Bình luận nhúng dạng JSON/JS: tìm chuỗi nội dung
    import re
    for m in re.finditer(r'"content"\s*:\s*"([^"]{10,600})"', html):
        text = m.group(1).encode().decode("unicode_escape", errors="ignore")
        if text and len(text) > 3 and text not in comments:
            comments.append(text)
    return comments


async def fetch_all(urls: List[str], headless: bool = True, js_code: str = "") -> List[str]:
    """Lấy HTML nhiều URL song song, giữ thứ tự. js_code chạy trước khi parse."""
    bc = BrowserConfig(headless=headless, verbose=False, text_mode=True)
    results: List[str] = []
    async with AsyncWebCrawler(config=bc) as c:
        for i in range(0, len(urls), 8):
            batch = urls[i:i + 8]
            cfgs = [CrawlerRunConfig(cache_mode=CacheMode.BYPASS, js_code=js_code or None) for _ in batch]
            rs = await asyncio.gather(*[c.arun(url=u, config=cfg) for u, cfg in zip(batch, cfgs)])
            results.extend(r.html if r and r.success else "" for r in rs)
            logger.info(f"Fetched {i + len(batch)}/{len(urls)} detail pages")
    return results


def main():
    parser = argparse.ArgumentParser(description="Crawl TGDD: tên, giá, hình, link, cmt (AJAX nhanh)")
    parser.add_argument("--max-products", type=int, default=None, help="Giới hạn sản phẩm (mặc định: tất cả)")
    parser.add_argument("--max-comments", type=int, default=300, help="Số comment tối đa/sp")
    parser.add_argument("--headless", action="store_true", default=False, help="Chạy headless (không hiện browser)")
    parser.add_argument("--skip-comments", action="store_true", help="Chỉ lấy danh sách sản phẩm, không crawl bình luận")
    parser.add_argument("--save-json", type=str, default="", help="Lưu kết quả ra file JSON nếu có (vd: tgdd.json)")
    args = parser.parse_args()

    # ---------- 1) Lấy toàn bộ danh sách sản phẩm qua AJAX ----------
    logger.info("Đang lấy danh sách sản phẩm qua AJAX FilterProductBox...")
    products = fetch_all_products()
    logger.info(f"Parsed {len(products)} sản phẩm từ AJAX")
    if args.max_products:
        products = products[:args.max_products]
    if not products:
        logger.error("Không parse được sản phẩm nào!")
        sys.exit(1)

    with open("debug_tgdd_all.html", "w", encoding="utf-8") as f:
        f.write('\n'.join(f'<li><a href="{p.product_url}" data-name="{p.name}">{p.name}</a>'
                          f'<strong class="price">{p.price}</strong>'
                          f'<img src="{p.image_url}"></li>' for p in products))

    # ---------- 2) Lấy bình luận (trừ khi --skip-comments) ----------
    if not args.skip_comments:
        logger.info(f"Đang lấy bình luận cho {len(products)} sản phẩm...")
        detail_htmls = asyncio.run(fetch_all(
            [p.product_url for p in products], headless=args.headless, js_code=LOAD_COMMENTS_JS))
        for p, html in zip(products, detail_htmls):
            if html:
                cmts = parse_comments_from_html(html)
                p.comments = cmts[:args.max_comments]
            logger.info(f"{len(p.comments)} comments | {p.name[:50]}")
    else:
        logger.info("Bỏ qua crawl bình luận (--skip-comments)")

    # ---------- 3) Lưu JSON nếu yêu cầu ----------
    if args.save_json:
        import json as _json
        data = [{
            "name": p.name,
            "price": p.price,
            "image_url": p.image_url,
            "product_url": p.product_url,
            "source": p.source,
            "comments": p.comments,
        } for p in products]
        with open(args.save_json, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Đã lưu {len(data)} sản phẩm vào {args.save_json}")

    # ---------- 4) In kết quả ----------
    print("\n" + "=" * 100)
    print(f"TỔNG SẢN PHẨM: {len(products)} (Thế Giới Di Động - {CATE_URL})")
    print("=" * 100)
    for i, p in enumerate(products, 1):
        print(f"\n[{i}] {p.name}")
        print(f"    Giá      : {p.price}")
        print(f"    Hình     : {p.image_url}")
        print(f"    Link     : {p.product_url}")
        print(f"    Bình luận: {len(p.comments)}")
        for c in p.comments[:5]:
            print(f"      - {c[:120]}")

    # Tổng kết
    total_cmts = sum(len(p.comments) for p in products)
    print("\n" + "=" * 100)
    print(f"KẾT QUẢ: {len(products)} sản phẩm, {total_cmts} bình luận")
    print("=" * 100)


if __name__ == "__main__":
    main()