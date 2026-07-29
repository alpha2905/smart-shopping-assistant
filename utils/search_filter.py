import re
import unicodedata
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

# Từ khóa loại trừ — không phải điện thoại
NON_PHONE_KEYWORDS = [
    "op lung", "tai nghe", "sac ", " cap ", "cáp ", "pin du phong", "loa bluetooth",
    "may tinh bang", "tablet", "ipad", "laptop", "macbook", "dong ho thong minh",
    "smartwatch", "airpods", "phu kien", "phụ kiện", "bao da", "kinh cuong luc",
    "dan man hinh", "chuot", "ban phim", "the nho", "the nho", "o cung",
    "camera", "may anh", "tivi", "man hinh", "guong", "tripod", "gia do",
]

PHONE_URL_HINTS = [
    "dien-thoai", "dien-thoai-", "/phone", "/mobile", "smartphone",
]

BRAND_PREFIXES = [
    "apple", "samsung", "xiaomi", "oppo", "vivo", "realme", "nokia", "huawei",
    "honor", "oneplus", "google", "dien thoai", "smartphone", "may",
]

# ========== MỞ RỘNG TỪ VIẾT TẮT ==========
# Mapping: viết tắt → tên thương hiệu đầy đủ
ABBREV_BRAND = {
    "ip": "iphone",
    "ss": "samsung",
    "rm": "redmi",
    "xm": "xiaomi",
    "op": "oppo",
    "opp": "oneplus",
    "vv": "vivo",
    "rl": "realme",
    "nk": "nokia",
    "hw": "huawei",
    "hr": "honor",
    "px": "pixel",
    "zf": "zenfone",
    "rog": "rog phone",
}

# Mapping: số model viết tắt → tên model đầy đủ (thường gặp)
ABBREV_MODEL = {
    # iPhone
    r"\bip(\d+)\b": r"iphone \1",
    r"\bip(\d+)pro\b": r"iphone \1 pro",
    r"\bip(\d+)promax\b": r"iphone \1 pro max",
    r"\bip(\d+)plus\b": r"iphone \1 plus",
    r"\biphone(\d+)\b": r"iphone \1",
    # Samsung Galaxy
    r"\bss\s*s(\d+)\b": r"samsung galaxy s\1",
    r"\bss\s*s(\d+)ultra\b": r"samsung galaxy s\1 ultra",
    r"\bss\s*s(\d+)fe\b": r"samsung galaxy s\1 fe",
    r"\bss\s*a(\d+)\b": r"samsung galaxy a\1",
    r"\bss\s*z(\w+)\b": r"samsung galaxy z \1",
    r"\bss\s*note(\d+)\b": r"samsung galaxy note \1",
    r"\bss\s*m(\d+)\b": r"samsung galaxy m\1",
    r"\bsamsung\s*s(\d+)\b": r"samsung galaxy s\1",
    r"\bsamsung\s*a(\d+)\b": r"samsung galaxy a\1",
    r"\bsamsung\s*z(\w+)\b": r"samsung galaxy z \1",
    # Xiaomi / Redmi / Poco
    r"\brm\s*note(\d+)\b": r"redmi note \1",
    r"\brm\s*(\d+[a-z]*)\b": r"redmi \1",
    r"\bxiaomi\s*(\d+)\b": r"xiaomi \1",
    r"\bpo\s*(\w+)\b": r"poco \1",
    r"\bpoco\s*x(\d+)\b": r"poco x\1",
    r"\bpoco\s*m(\d+)\b": r"poco m\1",
    r"\bpoco\s*f(\d+)\b": r"poco f\1",
    # Oppo
    r"\bop\s*(find|reno|a)\s*(\w+)\b": r"oppo \1 \2",
    r"\boppo\s*(find|reno|a)\s*(\w+)\b": r"oppo \1 \2",
    # Vivo
    r"\bvv\s*y(\d+)\b": r"vivo y\1",
    r"\bvv\s*v(\d+)\b": r"vivo v\1",
    r"\bvv\s*x(\d+)\b": r"vivo x\1",
    # Realme
    r"\brl\s*c(\d+)\b": r"realme c\1",
    r"\brl\s*(\d+)pro\b": r"realme \1 pro",
    r"\brl\s*gt\b": r"realme gt",
    # Nokia
    r"\bnk\s*(\d+)\b": r"nokia \1",
    # Huawei
    r"\bhw\s*p(\d+)\b": r"huawei p\1",
    r"\bhw\s*mate(\d+)\b": r"huawei mate \1",
    r"\bhw\s*nova(\d+)\b": r"huawei nova \1",
    # Honor
    r"\bhr\s*(\d+)\b": r"honor \1",
    r"\bhonor\s*x(\d+)\b": r"honor x\1",
}

# Regex gộp từ ABBREV_MODEL để apply 1 lần
_ABBREV_PATTERNS = [(re.compile(p, re.IGNORECASE), r) for p, r in ABBREV_MODEL.items()]


def expand_query(query: str) -> List[str]:
    """
    Mở rộng query viết tắt thành nhiều biến thể đầy đủ.
    VD: "ip14" → ["ip14", "iphone 14"]
         "ss s24" → ["ss s24", "samsung galaxy s24"]
         "rm note 13" → ["rm note 13", "redmi note 13"]

    Trả về danh sách các query, bao gồm query gốc ở vị trí đầu tiên.
    """
    results = [query]
    norm = query.lower().strip()

    # Thử từng pattern abbreviation
    expanded_set = set()
    for pattern, replacement in _ABBREV_PATTERNS:
        expanded = pattern.sub(replacement, norm)
        if expanded != norm:
            expanded_set.add(expanded)

    # Nếu không khớp pattern phức tạp, thử brand viết tắt đơn giản
    if not expanded_set:
        tokens = norm.split()
        if tokens:
            first = tokens[0]
            rest = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            if first in ABBREV_BRAND:
                full_brand = ABBREV_BRAND[first]
                expanded = f"{full_brand} {rest}".strip()
                if expanded != norm:
                    expanded_set.add(expanded)

    results.extend(sorted(expanded_set))
    return results

STORAGE_PATTERN = re.compile(r"\b(\d+)\s*(gb|tb)\b", re.IGNORECASE)
COLOR_KEYWORDS = [
    "den", "trang", "xanh", "do", "hong", "tim", "vang", "bac", "xam", "black",
    "white", "blue", "red", "pink", "purple", "gold", "silver", "gray", "grey",
    "green", "orange", "titan", "natural", "desert", "midnight", "starlight",
]


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi: bỏ dấu, lowercase, gom khoảng trắng."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_price(price_str: str) -> int:
    """Chuyển chuỗi giá VN ('12.990.000 đ') thành số nguyên."""
    if not price_str:
        return 0
    digits = re.sub(r"[^\d]", "", price_str)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _extract_storage(text: str) -> Optional[str]:
    match = STORAGE_PATTERN.search(text)
    if not match:
        return None
    value, unit = match.group(1), match.group(2).lower()
    return f"{value}{unit}"


def _extract_color(text: str) -> Optional[str]:
    tokens = set(normalize_text(text).split())
    for color in COLOR_KEYWORDS:
        if color in tokens:
            return color
    return None


def build_canonical_key(name: str, query: str) -> str:
    """
    Tạo khóa chuẩn để các sàn so khớp cùng một biến thể điện thoại.
    Dựa trên query + dung lượng/màu (nếu có trong tên sản phẩm).
    """
    norm_name = normalize_text(name)
    norm_query = normalize_text(query)

    for prefix in BRAND_PREFIXES:
        if norm_query.startswith(prefix + " "):
            norm_query = norm_query[len(prefix) + 1 :].strip()

    storage = _extract_storage(norm_name)
    query_storage = _extract_storage(norm_query)
    if query_storage:
        storage = query_storage

    color = _extract_color(norm_name)
    query_color = _extract_color(norm_query)
    if query_color:
        color = query_color

    parts = [norm_query]
    if storage:
        parts.append(storage)
    if color:
        parts.append(color)
    return " ".join(parts)


def is_phone_product(name: str, product_url: str = "") -> bool:
    """Kiểm tra sản phẩm có phải điện thoại (loại trừ phụ kiện, tablet, v.v.)."""
    norm_name = normalize_text(name)
    norm_url = normalize_text(product_url.replace("-", " ").replace("/", " "))

    for keyword in NON_PHONE_KEYWORDS:
        if keyword in norm_name:
            return False

    for hint in PHONE_URL_HINTS:
        if hint.replace("-", " ") in norm_url or hint in product_url.lower():
            return True

    phone_name_hints = ["iphone", "galaxy", "redmi", "poco", "pixel", "zenfone", "rog phone"]
    if any(h in norm_name for h in phone_name_hints):
        return True

    if norm_name.startswith("dien thoai"):
        return True

    # Mặc định coi là điện thoại nếu không khớp từ khóa loại trừ
    return True


def matches_query_exact(name: str, query: str) -> bool:
    """
    Tên sản phẩm phải chứa đầy đủ query (100% khớp, không fuzzy).
    So sánh sau khi chuẩn hóa, bỏ tiền tố thương hiệu/marketing.
    """
    norm_name = normalize_text(name)
    norm_query = normalize_text(query)

    if not norm_query:
        return False

    for prefix in BRAND_PREFIXES:
        if norm_query.startswith(prefix + " "):
            norm_query = norm_query[len(prefix) + 1 :].strip()
        if norm_name.startswith(prefix + " "):
            norm_name = norm_name[len(prefix) + 1 :].strip()

    # Query phải xuất hiện nguyên vẹn trong tên sản phẩm
    if norm_query in norm_name:
        return True

    # Hỗ trợ query có thêm dung lượng/màu: tên chứa phần model cốt lõi
    query_storage = _extract_storage(norm_query)
    query_color = _extract_color(norm_query)
    core_query = norm_query
    if query_storage:
        core_query = core_query.replace(query_storage, "").strip()
    if query_color:
        core_query = core_query.replace(query_color, "").strip()
    core_query = re.sub(r"\s+", " ", core_query).strip()

    if core_query and core_query in norm_name:
        if query_storage:
            name_storage = _extract_storage(norm_name)
            if name_storage and name_storage != query_storage:
                return False
        if query_color:
            name_color = _extract_color(norm_name)
            if name_color and name_color != query_color:
                return False
        return True

    return False


def _pick_cheapest(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    with_price = [p for p in products if p.get("_price_numeric", 0) > 0]
    if with_price:
        return min(with_price, key=lambda p: p["_price_numeric"])
    return products[0]


def _strip_internal_fields(product: Dict[str, Any]) -> Dict[str, Any]:
    result = {k: v for k, v in product.items() if not k.startswith("_")}
    result["canonical_name"] = product.get("_canonical_key", "")
    result["price_numeric"] = product.get("_price_numeric", 0)
    return result


def filter_comparable_phones(products: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """
    Lọc kết quả scrape:
    1. Chỉ giữ điện thoại
    2. Tên khớp 100% với query
    3. Mỗi sàn giữ điện thoại rẻ nhất (theo từng biến thể)
    4. Các sàn phải khớp cùng canonical key để so sánh giá

    Hỗ trợ query viết tắt: nếu không khớp với query gốc,
    tự động thử các biến thể mở rộng (vd: "ip14" → "iphone 14").
    """
    if not products:
        return []

    # Tất cả các biến thể query cần thử (gốc + mở rộng)
    queries_to_try = expand_query(query)

    candidates: List[Dict[str, Any]] = []

    for product in products:
        name = product.get("name", "")
        url = product.get("product_url", "")

        if not is_phone_product(name, url):
            continue

        # Thử từng biến thể query, dừng ở biến thể đầu tiên khớp
        matched_query = None
        for q in queries_to_try:
            if matches_query_exact(name, q):
                matched_query = q
                break

        if not matched_query:
            continue

        enriched = dict(product)
        enriched["_canonical_key"] = build_canonical_key(name, matched_query)
        enriched["_price_numeric"] = parse_price(product.get("price", ""))
        candidates.append(enriched)

    # DEBUG: log số lượng qua mỗi bước
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        "Filter debug: %d raw → %d phone-like → %d matched query → %d candidates",
        len(products),
        sum(1 for p in products if is_phone_product(p.get("name", ""), p.get("product_url", ""))),
        len(candidates),
        len(candidates),
    )

    if not candidates:
        return []

    # Nhóm theo (sàn, canonical key) → chọn rẻ nhất
    by_source_key: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_source_key[(item["source"], item["_canonical_key"])].append(item)

    cheapest_per_source_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, group in by_source_key.items():
        cheapest_per_source_key[key] = _pick_cheapest(group)

    # Đếm số sàn khớp từng canonical key
    key_sources: Dict[str, Set[str]] = defaultdict(set)
    for (source, canonical_key) in cheapest_per_source_key:
        key_sources[canonical_key].add(source)

    # Chọn canonical key xuất hiện trên nhiều sàn nhất (ưu tiên khớp query)
    query_key = build_canonical_key(query, query)
    best_key = max(
        key_sources.keys(),
        key=lambda k: (len(key_sources[k]), k == query_key, k),
    )

    results = [
        _strip_internal_fields(prod)
        for (source, canonical_key), prod in cheapest_per_source_key.items()
        if canonical_key == best_key
    ]

    # Sắp xếp theo giá tăng dần để dễ so sánh
    results.sort(key=lambda p: p.get("price_numeric") or 0)
    return results
