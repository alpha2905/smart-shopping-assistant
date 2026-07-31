"""
Product Quality Score (PQS) & Buy Recommendation Engine.

Kết hợp nhiều nguồn dữ liệu để đưa ra khuyến nghị mua hàng thông minh.

Các chỉ số:
1. PQS (Product Quality Score) - Điểm chất lượng tổng hợp (0-100)
2. Average Product Price - Giá trung bình, thấp nhất, cao nhất
3. Buy Recommendation - Khuyến nghị: Nên mua / Chờ / Không nên mua
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import numpy as np

from utils.price_predictor import parse_price_string, classify_price_change, get_change_label
from utils.db import get_product_price_history, get_all_products, get_latest_prices_for_query

logger = logging.getLogger(__name__)


# ========== PQS - PRODUCT QUALITY SCORE ==========

PQS_WEIGHTS = {
    "rating_avg": 0.25,        # Rating trung bình
    "sentiment_score": 0.30,   # Sentiment Score từ PhoBERT
    "seller_reputation": 0.15, # Uy tín gian hàng
    "sales_volume": 0.15,      # Số lượng bán
    "positive_feedback": 0.15, # Tỷ lệ phản hồi tích cực
}

# Uy tín mặc định cho các sàn
SELLER_REPUTATION = {
    "FPT Shop": 95,
    "Thế Giới Di Động": 92,
    "CellphoneS": 88,
    "Hoàng Hà Mobile": 85,
    "Di Động Việt": 82,
    "Viettel Store": 90,
    "Clickbuy": 78,
}

# Giá trị mặc định khi không có đủ dữ liệu
DEFAULT_SENTIMENT_SCORE = 75
DEFAULT_RATING = 4.0
DEFAULT_SALES = 100
DEFAULT_POSITIVE_FEEDBACK = 80


def calculate_pqs(
    product: Dict[str, Any],
    comments: Optional[List[str]] = None,
    sentiment_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Tính Product Quality Score (PQS) cho một sản phẩm.
    
    Args:
        product: Dict chứa thông tin sản phẩm
        comments: Danh sách bình luận (nếu có)
        sentiment_score: Điểm sentiment từ PhoBERT (nếu có)
        
    Returns:
        Dict với PQS và các thành phần
    """
    source = product.get("source", "")
    price = parse_price_string(product.get("price", ""))

    # === 1. Rating trung bình (0-10 scale, chuẩn hóa về 0-100) ===
    # Trích xuất từ comments hoặc dùng mặc định
    rating = _extract_rating(product, comments)
    rating_score = min(rating / 5.0 * 100, 100)

    # === 2. Sentiment Score (0-100) ===
    if sentiment_score is not None:
        sent_score = min(max(sentiment_score, 0), 100)
    else:
        sent_score = _calculate_sentiment_from_comments(comments) if comments else DEFAULT_SENTIMENT_SCORE

    # === 3. Uy tín gian hàng (0-100) ===
    reputation = SELLER_REPUTATION.get(source, 80)

    # === 4. Số lượng bán (0-100, normalized) ===
    sales = _extract_sales(product, comments)
    sales_score = min(sales / 5.0 * 100, 100)  # Giả sử max rating là 5 sao

    # === 5. Tỷ lệ phản hồi tích cực (0-100) ===
    positive_ratio = _calculate_positive_ratio(comments) if comments else DEFAULT_POSITIVE_FEEDBACK

    # === Tính PQS ===
    pqs = (
        PQS_WEIGHTS["rating_avg"] * rating_score +
        PQS_WEIGHTS["sentiment_score"] * sent_score +
        PQS_WEIGHTS["seller_reputation"] * reputation +
        PQS_WEIGHTS["sales_volume"] * sales_score +
        PQS_WEIGHTS["positive_feedback"] * positive_ratio
    )

    pqs = round(min(max(pqs, 0), 100), 1)

    # === Đánh giá chất lượng ===
    if pqs >= 85:
        quality_label = "🟢 Rất tốt"
    elif pqs >= 70:
        quality_label = "🟡 Tốt"
    elif pqs >= 50:
        quality_label = "🟠 Trung bình"
    else:
        quality_label = "🔴 Kém"

    return {
        "pqs": pqs,
        "quality_label": quality_label,
        "components": {
            "rating_score": round(rating_score, 1),
            "rating_raw": rating,
            "sentiment_score": round(sent_score, 1),
            "seller_reputation": reputation,
            "sales_score": round(sales_score, 1),
            "sales_raw": sales,
            "positive_feedback_ratio": round(positive_ratio, 1),
        },
        "weights": PQS_WEIGHTS,
    }


def _extract_rating(product: Dict[str, Any], comments: Optional[List[str]] = None) -> float:
    """Trích xuất rating từ product data hoặc comments."""
    # Try từ product fields
    for field in ["rating", "star", "rate", "score"]:
        val = product.get(field)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return DEFAULT_RATING


def _extract_sales(product: Dict[str, Any], comments: Optional[List[str]] = None) -> int:
    """Trích xuất số lượng bán."""
    for field in ["sold", "sales", "quantity_sold", "sold_count", "da_ban"]:
        val = product.get(field)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    # Fallback: dựa trên số comments
    if comments:
        return max(len(comments), 1)
    return DEFAULT_SALES


def _calculate_sentiment_from_comments(comments: List[str]) -> float:
    """
    Tính sentiment score từ comments.
    Tạm thời dùng rule-based, sau này có thể tích hợp PhoBERT.
    """
    if not comments:
        return DEFAULT_SENTIMENT_SCORE

    positive_words = ["tốt", "đẹp", "chính hãng", "nhanh", "ưng ý", "hài lòng",
                      "chất lượng", "xuất sắc", "tuyệt vời", "đáng mua",
                      "ok", "ổn", "ngon", "mượt", "xịn"]
    negative_words = ["lỗi", "hỏng", "tệ", "dở", "kém", "thất vọng",
                      "không nên mua", "trầy xước", "cũ", "giả",
                      "nóng", "pin yếu", "bảo hành", "chậm"]

    total_score = 0
    for comment in comments:
        comment_lower = comment.lower()
        pos_count = sum(1 for w in positive_words if w in comment_lower)
        neg_count = sum(1 for w in negative_words if w in comment_lower)
        # Score từ 0-100 cho mỗi comment
        score = 50 + (pos_count * 15) - (neg_count * 20)
        score = max(0, min(100, score))
        total_score += score

    avg_score = total_score / len(comments)
    return avg_score


def _calculate_positive_ratio(comments: List[str]) -> float:
    """Tính tỷ lệ bình luận tích cực."""
    if not comments:
        return DEFAULT_POSITIVE_FEEDBACK

    positive_words = ["tốt", "đẹp", "chính hãng", "nhanh", "ưng ý", "hài lòng",
                      "chất lượng", "tuyệt vời", "đáng mua", "ok", "ổn"]
    negative_words = ["lỗi", "hỏng", "tệ", "kém", "thất vọng", "không nên"]

    positive_count = 0
    for comment in comments:
        comment_lower = comment.lower()
        pos = sum(1 for w in positive_words if w in comment_lower)
        neg = sum(1 for w in negative_words if w in comment_lower)
        if pos > neg:
            positive_count += 1

    return (positive_count / len(comments)) * 100


# ========== AVERAGE PRODUCT PRICE ==========

def calculate_price_statistics(product_url: str, source: str) -> Optional[Dict[str, Any]]:
    """
    Tính toán thống kê giá cho một sản phẩm.
    
    Returns:
        {
            "min_price": 28500000,
            "max_price": 32000000,
            "avg_price": 29700000,
            "current_price": 28900000,
            "price_count": 5,
            "current_vs_avg": "below",  # below | above | equal
            "current_vs_min": "above",
            "volatility": 0.05,  # Biến động giá (std/mean)
            "price_range": 3500000,  # Khoảng giá max-min
            "history": [{price, date}, ...],
        }
    """
    history = get_product_price_history(product_url, source)
    if not history or len(history) < 2:
        return None

    prices = []
    for h in history:
        p = parse_price_string(h.get("price", ""))
        if p and p > 0:
            prices.append(p)

    if len(prices) < 2:
        return None

    prices_arr = np.array(prices)
    current_price = prices[-1]
    avg_price = float(np.mean(prices_arr))
    min_price = float(np.min(prices_arr))
    max_price = float(np.max(prices_arr))
    std_price = float(np.std(prices_arr))

    # Phân loại giá hiện tại so với trung bình
    if avg_price > 0:
        diff_pct = (current_price - avg_price) / avg_price
        if diff_pct < -0.02:
            current_vs_avg = "below"
        elif diff_pct > 0.02:
            current_vs_avg = "above"
        else:
            current_vs_avg = "equal"
    else:
        current_vs_avg = "equal"

    # Biến động giá
    volatility = std_price / avg_price if avg_price > 0 else 0

    return {
        "min_price": round(min_price, 0),
        "max_price": round(max_price, 0),
        "avg_price": round(avg_price, 0),
        "current_price": round(current_price, 0),
        "price_count": len(prices),
        "current_vs_avg": current_vs_avg,
        "volatility": round(volatility, 4),
        "price_range": round(max_price - min_price, 0),
        "price_std": round(std_price, 0),
    }


# ========== BUY RECOMMENDATION ENGINE ==========

def get_buy_recommendation(
    product: Dict[str, Any],
    pqs_result: Optional[Dict[str, Any]] = None,
    price_stats: Optional[Dict[str, Any]] = None,
    forecast_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Đưa ra khuyến nghị mua hàng dựa trên tổng hợp nhiều chỉ số.
    
    Args:
        product: Thông tin sản phẩm
        pqs_result: Kết quả PQS
        price_stats: Thống kê giá
        forecast_result: Kết quả dự báo LSTM
        
    Returns:
        {
            "recommendation": "buy_now" | "wait" | "not_recommended",
            "recommendation_label": "Nên mua ngay" | "Nên chờ" | "Không khuyến nghị",
            "reason": "...",
            "confidence": 0.85,  # Độ tin cậy 0-1
            "factors": {
                "price_good": True,
                "quality_good": True,
                "forecast_bad": False,
            }
        }
    """
    factors = {}
    reasons = []
    score = 0  # Điểm tổng hợp
    max_score = 0

    # === Factor 1: Price ===
    max_score += 30
    if price_stats:
        if price_stats.get("current_vs_avg") == "below":
            factors["price_good"] = True
            score += 30
            reasons.append("💰 Giá hiện tại thấp hơn mức trung bình")
        elif price_stats.get("current_vs_avg") == "above":
            factors["price_good"] = False
            score += 10
            reasons.append("💰 Giá hiện tại cao hơn mức trung bình")
        else:
            factors["price_good"] = True
            score += 20
            reasons.append("💰 Giá hiện tại ở mức trung bình")
    else:
        factors["price_good"] = True
        score += 15
        reasons.append("💰 Chưa có đủ dữ liệu giá để đánh giá")

    # === Factor 2: Quality ===
    max_score += 35
    if pqs_result:
        pqs = pqs_result.get("pqs", 0)
        if pqs >= 85:
            factors["quality_good"] = True
            score += 35
            reasons.append(f"⭐ Chất lượng sản phẩm rất tốt (PQS: {pqs}/100)")
        elif pqs >= 70:
            factors["quality_good"] = True
            score += 25
            reasons.append(f"⭐ Chất lượng sản phẩm tốt (PQS: {pqs}/100)")
        elif pqs >= 50:
            factors["quality_good"] = False
            score += 15
            reasons.append(f"⚠️ Chất lượng sản phẩm trung bình (PQS: {pqs}/100)")
        else:
            factors["quality_good"] = False
            score += 5
            reasons.append(f"❌ Chất lượng sản phẩm kém (PQS: {pqs}/100)")
    else:
        factors["quality_good"] = True
        score += 17
        reasons.append("⭐ Chưa có đánh giá chất lượng")

    # === Factor 3: Forecast ===
    max_score += 35
    if forecast_result:
        predictions = forecast_result.get("predictions", [])
        if predictions:
            first_pred = predictions[0].get("price", 0)
            last_pred = predictions[-1].get("price", 0)
            if first_pred > 0:
                forecast_change = (last_pred - first_pred) / first_pred
                if forecast_change < -0.03:
                    # Dự báo giảm -> nên chờ
                    factors["forecast_bad"] = False
                    score += 30
                    reasons.append(f"📊 Dự báo giá sẽ giảm {abs(forecast_change)*100:.1f}% - nên chờ thêm")
                elif forecast_change > 0.03:
                    # Dự báo tăng -> nên mua ngay
                    factors["forecast_bad"] = True
                    score += 35
                    reasons.append(f"📊 Dự báo giá sẽ tăng {forecast_change*100:.1f}% - nên mua ngay")
                else:
                    factors["forecast_bad"] = True
                    score += 25
                    reasons.append("📊 Dự báo giá ổn định")
            else:
                factors["forecast_bad"] = True
                score += 17
                reasons.append("📊 Chưa có dự báo giá")
        else:
            factors["forecast_bad"] = True
            score += 17
            reasons.append("📊 Chưa có dự báo giá")
    else:
        factors["forecast_bad"] = True
        score += 17
        reasons.append("📊 Chưa có dự báo giá")

    # === Calculate confidence ===
    confidence = round(score / max_score, 2) if max_score > 0 else 0

    # === Final recommendation ===
    if confidence >= 0.75 and factors.get("quality_good", True) and factors.get("price_good", True):
        recommendation = "buy_now"
        recommendation_label = "Nên mua ngay"
    elif confidence >= 0.50:
        recommendation = "wait"
        recommendation_label = "Nên chờ"
    else:
        recommendation = "not_recommended"
        recommendation_label = "Không khuyến nghị"

    # Pick top 3 reasons
    reasons = reasons[:3]

    return {
        "recommendation": recommendation,
        "recommendation_label": recommendation_label,
        "reasons": reasons,
        "confidence": confidence,
        "score": score,
        "max_score": max_score,
        "factors": factors,
    }


# ========== MAIN PROCESS ==========

def analyze_product(
    product: Dict[str, Any],
    comments: Optional[List[str]] = None,
    sentiment_score: Optional[float] = None,
    forecast_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Phân tích tổng thể một sản phẩm.
    Kết hợp PQS, Price Statistics, Buy Recommendation.
    """
    product_url = product.get("product_url", "")
    source = product.get("source", "")

    # Nếu không truyền comments, lấy từ product data (đã lưu trong DB)
    if comments is None:
        comments = product.get("comments", [])

    # 1. Tính PQS
    pqs_result = calculate_pqs(product, comments, sentiment_score)

    # 2. Tính thống kê giá
    price_stats = calculate_price_statistics(product_url, source)

    # 3. Khuyến nghị mua hàng
    recommendation = get_buy_recommendation(
        product, pqs_result, price_stats, forecast_result
    )

    return {
        "product_name": product.get("name", ""),
        "product_url": product_url,
        "source": source,
        "pqs": pqs_result,
        "price_statistics": price_stats,
        "recommendation": recommendation,
    }


def analyze_products_batch(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Phân tích hàng loạt sản phẩm, trả về danh sách đã sắp xếp theo PQS.
    Truyền comments từ product data (đã lưu trong DB) vào analyze_product.
    """
    results = []
    for product in products:
        try:
            comments = product.get("comments", [])
            analysis = analyze_product(product, comments=comments)
            results.append(analysis)
        except Exception as e:
            logger.error(f"Error analyzing product {product.get('name', '')}: {e}")
            continue

    # Sắp xếp theo PQS giảm dần
    results.sort(key=lambda x: x.get("pqs", {}).get("pqs", 0), reverse=True)
    return results