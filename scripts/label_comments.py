# -*- coding: utf-8 -*-
"""Gán nhãn 3 lớp (positive/neutral/negative) cho comments bằng PhoBERT pipeline."""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from ai.sentiment.model import get_sentiment_pipeline, LABELS, LABEL_TO_ID, ID_TO_LABEL
from ai.sentiment.preprocess import clean_comment
from ai.sentiment.infer import LABEL_MAP

INPUT_PATH = os.path.join("scripts", "output", "train_comments.json")
OUTPUT_PATH = os.path.join("scripts", "output", "dataset_labeled.json")
BATCH_SIZE = 32


def normalize_label(label: str) -> str:
    """Chuẩn hóa nhãn về positive/neutral/negative."""
    if label in LABEL_MAP:
        return LABEL_MAP[label]
    lower = label.lower()
    if lower in ("positive", "tích cực"):
        return "positive"
    if lower in ("negative", "tiêu cực"):
        return "negative"
    return "neutral"


def main():
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        records = json.load(f)
    logger.info("Đã tải %d comments từ %s", len(records), INPUT_PATH)

    print("Đang tải PhoBERT pipeline...")
    pipeline = get_sentiment_pipeline()

    labeled = []
    texts = [r["text"] for r in records]

    # Preprocess đợt nhỏ để tránh mất gốc
    cleaned_all = []
    for t in texts:
        c = clean_comment(t)
        cleaned_all.append(c if c else t)
    logger.info("Hoàn tất preprocess %d comments", len(cleaned_all))

    # Chạy pipeline theo batch
    for i in range(0, len(cleaned_all), BATCH_SIZE):
        batch = cleaned_all[i:i + BATCH_SIZE]
        batch_records = records[i:i + BATCH_SIZE]

        try:
            # Truncation để tránh lỗi index out of bounds với comment > 258 token
            results = pipeline(batch, truncation=True, max_length=256)
        except Exception as e:
            logger.error("Lỗi pipeline tại batch %d: %s", i, e)
            results = [None] * len(batch)

        for rec, res in zip(batch_records, results):
            if res is None:
                continue
            if isinstance(res, list):
                best = max(res, key=lambda x: x.get("score", 0))
                label_raw = best.get("label", "neutral")
                score = best.get("score", 0.0)
            else:
                label_raw = res.get("label", "neutral")
                score = res.get("score", 0.0)

            label = normalize_label(label_raw)
            labeled.append({
                "text": rec["text"],
                "text_cleaned": cleaned_all[len(labeled)],
                "label": label,
                "label_id": LABEL_TO_ID[label],
                "score": round(float(score), 4),
                "source": rec.get("source", ""),
                "product_name": rec.get("product_name", ""),
                "query": rec.get("query", ""),
            })

        if (i // BATCH_SIZE) % 10 == 0:
            logger.info("Đã gán nhãn %d/%d", len(labeled), len(records))

    os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(labeled, f, ensure_ascii=False, indent=2)
    logger.info("Đã ghi %d records -> %s", len(labeled), OUTPUT_PATH)

    # Thống kê
    dist = {}
    for d in labeled:
        dist[d["label"]] = dist.get(d["label"], 0) + 1
    print("\n=== PHAN PHOI NHAN ===")
    for lab in LABELS:
        n = dist.get(lab, 0)
        pct = n / len(labeled) * 100 if labeled else 0
        print(f"  {lab:10s} {n:>6,}  ({pct:.1f}%)")
    print(f"  Tong: {len(labeled):,}")
    print("======================")


if __name__ == "__main__":
    main()