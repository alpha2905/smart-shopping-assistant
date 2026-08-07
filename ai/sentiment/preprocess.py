# -*- coding: utf-8 -*-
"""
Tiền xử lý văn bản bình luận tiếng Việt cho PhoBERT.
Chuẩn hóa từ lóng, teencode và tách từ tiếng Việt.
"""
import logging
import os
import re
from typing import List

logger = logging.getLogger(__name__)

# Từ điển teencode / từ lóng thường gặp trong TMĐT
TEENCODE_MAP = {
    "k": "không", "ko": "không", "khong": "không", "hok": "không", "hem": "không",
    "kh": "không", "k0": "không",
    "dc": "được", "dk": "được", "duoc": "được",
    "bt": "bình thường", "binh thuong": "bình thường",
    "ok": "tốt", "oke": "tốt", "okela": "tốt", "okay": "tốt",
    "xau": "xấu", "tot": "tốt", "dep": "đẹp",
    "nhanh": "nhanh", "cham": "chậm",
    "re": "rẻ", "dat": "đắt", "mac": "mắc",
    "ngon": "ngon", "dở": "dở",
    "ship": "giao hàng", "giao": "giao hàng",
    "bh": "bảo hành", "baohanh": "bảo hành",
    "sp": "sản phẩm", "sanpham": "sản phẩm",
    "dt": "điện thoại", "dienthoai": "điện thoại",
    "man": "màn hình", "manhinh": "màn hình",
    "cam": "camera",
    "xịn": "xịn", "xin": "xịn",
    "vl": "quá", "vcl": "quá", "cc": "quá",
    "thik": "thích", "thich": "thích", "iu": "yêu",
    "mua": "mua", "ban": "bán", "gia": "giá",
    "tragop": "trả góp", "tra gop": "trả góp",
    "km": "khuyến mãi", "khuyenmai": "khuyến mãi",
    "freeship": "miễn phí giao hàng",
    "sale": "giảm giá", "giamgia": "giảm giá",
    "chinhhang": "chính hãng", "chinh hang": "chính hãng",
    "xachtay": "xách tay", "xach tay": "xách tay",
    "like": "thích", "luv": "yêu",
    "tks": "cảm ơn", "thanks": "cảm ơn", "thank": "cảm ơn",
    "cuc": "cực", "rat": "rất",
    "qua": "quá", "lam": "lắm",
}

# Từ lóng / cụm từ thường gặp
SLANG_MAP = {
    "xịn sò": "xịn", "xịn xò": "xịn", "ngon lành": "ngon",
    "chất lượng cao": "chất lượng", "hàng chính hãng": "chính hãng",
    "hàng xách tay": "xách tay", "hàng mới": "mới", "hàng cũ": "cũ",
    "giá tốt": "rẻ", "giá rẻ": "rẻ", "giá hời": "rẻ",
    "mua ngay": "mua", "đáng mua": "đáng mua", "nên mua": "nên mua",
    "không nên mua": "không nên mua", "đừng mua": "không nên mua",
    "pin trâu": "pin tốt", "pin yếu": "pin yếu", "pin nhanh hết": "pin yếu",
    "máy nóng": "nóng máy", "nóng máy": "nóng máy",
    "chạy mượt": "mượt", "mượt mà": "mượt", "lag": "chậm", "giật lag": "chậm",
    "bền bỉ": "bền", "dễ vỡ": "dễ vỡ",
    "giao nhanh": "giao hàng nhanh", "giao hàng nhanh": "giao hàng nhanh",
    "giao chậm": "giao hàng chậm", "giao hàng chậm": "giao hàng chậm",
    "đóng gói kỹ": "đóng gói tốt", "đóng gói tốt": "đóng gói tốt",
    "đóng gói sơ sài": "đóng gói kém", "đóng gói kém": "đóng gói kém",
    "bảo hành tốt": "bảo hành tốt", "bảo hành kém": "bảo hành kém",
    "dịch vụ tốt": "dịch vụ tốt", "dịch vụ kém": "dịch vụ kém",
    "nhân viên nhiệt tình": "nhân viên tốt", "nhân viên thân thiện": "nhân viên tốt",
    "nhân viên lơ là": "nhân viên kém",
    "tư vấn nhiệt tình": "tư vấn tốt", "tư vấn kém": "tư vấn kém",
    "giá cả hợp lý": "giá hợp lý", "giá hợp lý": "giá hợp lý",
    "giá cả phải chăng": "giá rẻ", "giá phải chăng": "giá rẻ",
    "giá cả đắt": "giá đắt", "giá đắt": "giá đắt",
    "giá cả mắc": "giá mắc", "giá mắc": "giá mắc",
    "chất lượng kém": "chất lượng kém", "chất lượng xấu": "chất lượng kém",
    "chất lượng tốt": "chất lượng tốt", "chất lượng tuyệt vời": "chất lượng tốt",
    "chất lượng xuất sắc": "chất lượng tốt", "chất lượng trung bình": "chất lượng trung bình",
    "chất lượng khá": "chất lượng tốt", "chất lượng tạm": "chất lượng trung bình",
}

# Emoji / ký tự đặc biệt cần loại bỏ
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

# URL pattern
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")

# Số điện thoại pattern
PHONE_PATTERN = re.compile(r"\b\d{10,11}\b")

# Ký tự lặp (vd: "đẹpppp" -> "đẹp")
REPEAT_PATTERN = re.compile(r"(.)\1{2,}")


def _normalize_teencode(text: str) -> str:
    """Chuẩn hóa teencode: thay từ viết tắt bằng từ đầy đủ."""
    words = text.split()
    normalized = []
    for word in words:
        lower = word.lower()
        if lower in TEENCODE_MAP:
            normalized.append(TEENCODE_MAP[lower])
        else:
            normalized.append(word)
    return " ".join(normalized)


def _normalize_slang(text: str) -> str:
    """Chuẩn hóa từ lóng: thay cụm từ lóng bằng cụm chuẩn."""
    result = text
    for slang, standard in SLANG_MAP.items():
        result = re.sub(rf"\b{re.escape(slang)}\b", standard, result, flags=re.IGNORECASE)
    return result


def _remove_noise(text: str) -> str:
    """Loại bỏ nhiễu: emoji, URL, số điện thoại, ký tự lặp."""
    text = EMOJI_PATTERN.sub(" ", text)
    text = URL_PATTERN.sub(" ", text)
    text = PHONE_PATTERN.sub(" ", text)
    text = REPEAT_PATTERN.sub(r"\1\1", text)
    return text


def _try_vncorenlp(text: str) -> str:
    """
    Tách từ tiếng Việt bằng VnCoreNLP (nếu đã cài).
    Nếu chưa cài, trả về text gốc (fallback).
    """
    try:
        from vncorenlp import VnCoreNLP

        # Đường dẫn jar mặc định - người dùng có thể đặt biến môi trường
        jar_path = os.environ.get("VNCORENLP_JAR", "VnCoreNLP-1.1.1.jar")
        annotator = VnCoreNLP(jar_path, annotators="wseg", max_heap_size="-Xmx2g")
        words = annotator.tokenize(text)
        return " ".join("_".join(sent) for sent in words)
    except Exception as e:
        logger.debug("VnCoreNLP không khả dụng, dùng fallback: %s", e)
        return text


def clean_comment(comment: str) -> str:
    """
    Làm sạch 1 bình luận:
    1. Loại bỏ nhiễu (emoji, URL, số điện thoại, ký tự lặp)
    2. Chuẩn hóa teencode
    3. Chuẩn hóa từ lóng
    4. Tách từ tiếng Việt (VnCoreNLP nếu có)
    """
    if not comment:
        return ""

    text = str(comment).strip()
    text = _remove_noise(text)
    text = _normalize_teencode(text)
    text = _normalize_slang(text)
    text = " ".join(text.split())

    # Tách từ tiếng Việt (chỉ khi text đủ dài)
    if len(text.split()) >= 3:
        text = _try_vncorenlp(text)

    return text


def preprocess_comments(comments: List[str]) -> List[str]:
    """
    Tiền xử lý danh sách bình luận.
    Loại bỏ bình luận quá ngắn (< 3 từ) hoặc rỗng sau khi làm sạch.
    """
    processed = []
    for c in comments:
        cleaned = clean_comment(c)
        if cleaned and len(cleaned.split()) >= 3:
            processed.append(cleaned)
    return processed