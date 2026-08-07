# -*- coding: utf-8 -*-
"""
Phân tích cảm xúc bình luận bằng PhoBERT (3 nhãn) và tính RQS.
"""
import logging
import re
from typing import List, Dict, Any
from collections import Counter

logger = logging.getLogger(__name__)

# Nhãn chuẩn hóa
LABEL_MAP = {"POS": "positive", "NEU": "neutral", "NEG": "negative"}


def analyze_sentiments(pipeline, comments: List[str]) -> Dict[str, Any]:
    """
    Phân tích danh sách bình luận bằng PhoBERT pipeline.
    Hỗ trợ cả pipeline top_k=None (trả về list) và pipeline thường.

    Returns:
        Dict với tỷ lệ positive/neutral/negative, sentiment_score, comment_count
    """
    if not comments:
        return {
            "positive": 0.0, "neutral": 0.0, "negative": 0.0,
            "sentiment": "neutral", "sentiment_score": 0.5,
            "comment_count": 0,
        }

    try:
        results = pipeline(comments)
    except Exception as e:
        logger.error(f"Lỗi khi chạy sentiment pipeline: {e}", exc_info=True)
        return {}

    sentiments = []
    scores = []

    for res in results:
        # Trường hợp pipeline top_k=None: res là list [{label, score}, ...]
        if isinstance(res, list):
            best = max(res, key=lambda x: x.get("score", 0))
            label = best.get("label", "neutral")
            score = best.get("score", 0.0)
        else:
            label = res.get("label", "neutral")
            score = res.get("score", 0.0)

        # Chuẩn hóa nhãn
        if label in LABEL_MAP:
            norm_label = LABEL_MAP[label]
        elif label.lower() in ("positive", "tích cực"):
            norm_label = "positive"
        elif label.lower() in ("negative", "tiêu cực"):
            norm_label = "negative"
        else:
            norm_label = "neutral"

        sentiments.append(norm_label)
        scores.append(float(score))

    counts = Counter(sentiments)
    total = len(sentiments)

    positive_pct = counts.get("positive", 0) / total
    neutral_pct = counts.get("neutral", 0) / total
    negative_pct = counts.get("negative", 0) / total

    # Sentiment score 0-1 (positive=1, neutral=0.5, negative=0)
    sentiment_score = (positive_pct * 1.0) + (neutral_pct * 0.5) + (negative_pct * 0.0)

    return {
        "positive": round(positive_pct, 4),
        "neutral": round(neutral_pct, 4),
        "negative": round(negative_pct, 4),
        "sentiment": counts.most_common(1)[0][0] if counts else "neutral",
        "sentiment_score": round(sentiment_score, 4),
        "comment_count": total,
    }


def calculate_rqs(comment: str, sentiment_label: str = "neutral") -> float:
    """
    Tính Review Quality Score (RQS) 1-5 cho từng bình luận.

    RQS kết hợp:
    - Sentiment score (0-1)
    - Độ dài bình luận (mức độ chi tiết)
    - Mức độ hữu ích (có từ khóa cụ thể về sản phẩm)

    Returns:
        RQS từ 1.0 đến 5.0
    """
    if not comment or not comment.strip():
        return 1.0

    # 1. Sentiment base (1-5)
    sent_base = {"positive": 4.0, "neutral": 3.0, "negative": 2.0}.get(sentiment_label, 3.0)

    # 2. Độ dài bình luận (0-1 điểm cộng)
    word_count = len(comment.split())
    if word_count >= 20:
        length_bonus = 1.0
    elif word_count >= 10:
        length_bonus = 0.7
    elif word_count >= 5:
        length_bonus = 0.4
    else:
        length_bonus = 0.1

    # 3. Mức độ hữu ích - có từ khóa cụ thể
    useful_keywords = [
        "pin", "màn hình", "camera", "hiệu năng", "giao hàng", "đóng gói",
        "bảo hành", "giá", "màu", "bộ nhớ", "ram", "nhiệt độ", "nóng",
        "mượt", "chậm", "nhanh", "đẹp", "xấu", "chất lượng",
    ]
    useful_count = sum(1 for kw in useful_keywords if kw in comment.lower())
    usefulness = min(useful_count * 0.2, 1.0)  # tối đa 1.0

    # Tổng hợp RQS: base + length_bonus*0.5 + usefulness*0.5
    rqs = sent_base + (length_bonus * 0.5) + (usefulness * 0.5)
    rqs = max(1.0, min(5.0, rqs))
    return round(rqs, 1)


def analyze_comment_rqs(comment: str, sentiment_label: str = "neutral") -> Dict[str, Any]:
    """Phân tích 1 bình luận và tính RQS."""
    rqs = calculate_rqs(comment, sentiment_label)
    word_count = len(comment.split())
    return {
        "comment": comment[:200],
        "sentiment": sentiment_label,
        "rqs": rqs,
        "word_count": word_count,
        "quality": "Rất tốt" if rqs >= 4.5 else ("Tốt" if rqs >= 4.0 else (
            "Khá" if rqs >= 3.0 else "Kém")),
    }