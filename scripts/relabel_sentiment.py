# -*- coding: utf-8 -*-
"""Gán nhãn lại comments bằng lexicon tiếng Việt, có cân bằng 3 lớp."""
import json
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

INPUT_PATH = os.path.join("scripts", "output", "dataset_labeled.json")
OUTPUT_PATH = os.path.join("scripts", "output", "dataset_labeled_v2.json")

POS_WORDS = [
    "tốt", "tuyệt vời", "tuyệt", "xuất sắc", "hoàn hảo", "đẹp", "xinh", "nhanh",
    "mượt", "ok", "ổn", "oke", "okay", "hài lòng", "thích", "ưng ý", "chất lượng",
    "đáng tiền", "rẻ", "hợp lý", "đỉnh", "xịn", "sang", "bền", "pin trâu",
    "giao nhanh", "cẩn thận", "nhiệt tình", "nên mua", "đáng mua", "rất tốt",
    "rất đẹp", "quá tốt", "quá đẹp", "khá tốt", "khá ổn", "ngon", "sướng",
    "xứng đáng", "tiện", "tiện lợi", "yên tâm", "an tâm", "cảm ơn", "thanks",
    "chuẩn", "đáng đồng tiền", "khỏi chê", "tuyệt cú mèo", "đẹp mắt",
    "sắc nét", "bắt mắt", "mới tinh", "pro", "siêu đẹp", "siêu nhanh",
    "gọn nhẹ", "dễ chịu", "hiện đại", "thông minh", "bền bỉ",
]

NEG_WORDS = [
    "dở", "tệ", "chán", "kém", "chậm", "lag", "nóng", "hỏng", "lỗi", "xấu",
    "đắt", "mắc", "thất vọng", "phí tiền", "dỏm", "nhái", "fake", "không nên mua",
    "giao chậm", "vỡ", "trầy", "ồn", "rung", "giật", "đơ", "treo", "cũ",
    "tệ quá", "dở tệ", "quá tệ", "rất tệ", "chán lắm", "kém lắm", "không tốt",
    "không đẹp", "không mượt", "không ổn", "không hài lòng", "không đáng",
    "bực mình", "khó chịu", "bức xúc", "tức giận", "mất tiền", "lãng phí",
    "trục trặc", "lỗi camera", "lỗi pin", "pin yếu", "chai pin", "sạc chậm",
    "mất sóng", "rớt mạng", "không hoạt động", "vô dụng", "lừa đảo", "kém chất lượng",
    "nhanh hết pin", "nóng máy", "không dùng được",
]

NEU_WORDS = [
    "bình thường", "tạm được", "tạm ổn", "cũng được", "trung bình", "tàm tạm",
    "tạm", "thường", "không có gì đặc biệt", "chấp nhận được", "không sao",
    "bình thường thôi", "không khen không chê",
]


def simple_normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\sàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def relabel(text: str) -> str:
    t = simple_normalize(text)
    pos = sum(1 for w in POS_WORDS if w in t)
    neg = sum(1 for w in NEG_WORDS if w in t)
    neu = sum(1 for w in NEU_WORDS if w in t)
    if pos > neg and pos >= neu:
        return "positive"
    if neg > pos and neg >= neu:
        return "negative"
    if neu > 0 and neu >= pos and neu >= neg:
        return "neutral"
    return "neutral"


def balance(labeled, max_per_class=2000, seed=42):
    random.seed(seed)
    by_label = {}
    for r in labeled:
        by_label.setdefault(r["label"], []).append(r)
    out = []
    for lab, items in by_label.items():
        if len(items) > max_per_class:
            items = random.sample(items, max_per_class)
        out.extend(items)
    random.shuffle(out)
    return out


def main():
    rows = json.load(open(INPUT_PATH, encoding="utf-8"))
    print(f"Tổng records gốc: {len(rows):,}")

    out = []
    for r in rows:
        lab = relabel(r["text"] if isinstance(r.get("text"), str) else "")
        out.append({**r, "label": lab})

    dist = Counter(o["label"] for o in out)
    print("\n=== PHÂN PHỐI SAU RELABEL (toàn bộ) ===")
    for lab in ("positive", "neutral", "negative"):
        n = dist.get(lab, 0)
        print(f"  {lab:10s} {n:>6,}  ({n / len(out) * 100:.1f}%)")

    balanced = balance(out, max_per_class=2000)
    dist2 = Counter(o["label"] for o in balanced)
    print("\n=== PHÂN PHỐI SAU CÂN BẰNG ===")
    for lab in ("positive", "neutral", "negative"):
        n = dist2.get(lab, 0)
        print(f"  {lab:10s} {n:>6,}  ({n / len(balanced) * 100:.1f}%)")

    from ai.sentiment.model import LABEL_TO_ID
    for r in balanced:
        r["label_id"] = LABEL_TO_ID[r["label"]]
        r["score"] = 0.0

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(balanced, f, ensure_ascii=False, indent=2)
    print(f"\nĐã ghi {len(balanced):,} records -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
