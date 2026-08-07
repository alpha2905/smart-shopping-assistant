# -*- coding: utf-8 -*-
"""
Service phân tích cảm xúc sản phẩm: Preprocess → PhoBERT → RQS → Lưu DB.
"""
import logging
from typing import List, Dict, Any

from utils.db import get_product_comments, save_sentiment_result
from ai.sentiment.model import get_sentiment_pipeline, LABELS
from ai.sentiment.preprocess import preprocess_comments
from ai.sentiment.infer import analyze_sentiments, calculate_rqs

logger = logging.getLogger(__name__)

# Khởi tạo pipeline một lần
try:
    sentiment_pipeline = get_sentiment_pipeline()
except Exception as e:
    sentiment_pipeline = None
    logger.error("Sentiment pipeline không khởi tạo được: %s", e)


def analyze_and_save_product_sentiment(product_url: str, source: str) -> Dict[str, Any]:
    """
    Pipeline đầy đủ: Lấy bình luận → Tiền xử lý → Phân tích → Tính RQS → Lưu DB.

    Returns:
        Dict kết quả sentiment + RQS trung bình
    """
    if not sentiment_pipeline:
        raise RuntimeError("Sentiment pipeline không khả dụng.")

    # 1. Lấy bình luận từ DB
    comments = get_product_comments(product_url, source)
    if not comments:
        return {"message": "Không có bình luận cho sản phẩm này."}

    logger.info("Đã lấy %d bình luận cho %s - %s", len(comments), source, product_url)

    # 2. Tiền xử lý (chuẩn hóa teencode, từ lóng, tách từ)
    processed_comments = preprocess_comments(comments)
    if not processed_comments:
        return {"message": "Không có bình luận hợp lệ sau tiền xử lý."}

    logger.info("Còn %d bình luận sau tiền xử lý", len(processed_comments))

    # 3. Phân tích cảm xúc (3 nhãn)
    analysis_result = analyze_sentiments(sentiment_pipeline, processed_comments)

    # 4. Tính RQS trung bình dựa trên sentiment của từng bình luận
    try:
        raw_results = sentiment_pipeline(processed_comments)
        rqs_list = []
        for res in raw_results:
            if isinstance(res, list):
                best = max(res, key=lambda x: x.get("score", 0))
                label = best.get("label", "neutral")
            else:
                label = res.get("label", "neutral")

            label_lower = label.lower()
            if "pos" in label_lower or label_lower in ("positive", "tích cực"):
                norm_label = "positive"
            elif "neg" in label_lower or label_lower in ("negative", "tiêu cực"):
                norm_label = "negative"
            else:
                norm_label = "neutral"

            for comment, sent_label in zip(processed_comments, [norm_label] * len(processed_comments)):
                rqs_list.append(calculate_rqs(comment, sent_label))
                break  # chỉ tính 1 lần mỗi comment

        avg_rqs = round(sum(rqs_list) / len(rqs_list), 2) if rqs_list else 0.0
        analysis_result["avg_rqs"] = avg_rqs
        analysis_result["rqs_stars"] = "⭐" * max(1, round(avg_rqs)) if avg_rqs > 0 else "—"
    except Exception as e:
        logger.warning("Không tính được RQS: %s", e)
        analysis_result["avg_rqs"] = 0.0
        analysis_result["rqs_stars"] = "—"

    # 5. Lưu kết quả vào DB collection 'sentiments'
    save_sentiment_result(product_url, source, analysis_result)

    return analysis_result


def get_product_sentiment(product_url: str, source: str) -> Dict[str, Any]:
    """Lấy kết quả sentiment đã lưu trong DB."""
    from utils.db import get_sentiment_result
    return get_sentiment_result(product_url, source) or {"message": "Chưa có kết quả sentiment."}