"""
RAG Retriever - Truy xuất dữ liệu sản phẩm, giá, bình luận từ MongoDB
để cung cấp ngữ cảnh cho chatbot.
"""
import logging
from typing import List, Dict, Any, Optional
from collections import Counter

from utils.db import (
    get_latest_prices_for_query, get_product_price_history,
    get_forecasts, get_all_products, get_unique_queries,
    get_product_comments,
)
from utils.search_filter import (
    parse_price, normalize_text, expand_query, matches_query_exact,
)

logger = logging.getLogger(__name__)

MAX_CONTEXT_PRODUCTS = 5
MAX_CONTEXT_COMMENTS = 10


class RAGRetriever:
    """
    Truy xuất ngữ cảnh liên quan đến câu hỏi của người dùng.
    Kết hợp nhiều nguồn: sản phẩm, giá, lịch sử giá, dự báo, bình luận.
    """

    def __init__(self):
        self._query_cache: Dict[str, List[Dict[str, Any]]] = {}

    # ─── Truy xuất sản phẩm ────────────────────────────────────────────
    def retrieve_products(self, query: str, limit: int = MAX_CONTEXT_PRODUCTS) -> List[Dict[str, Any]]:
        """Truy xuất sản phẩm khớp với query từ DB."""
        if query in self._query_cache:
            return self._query_cache[query][:limit]

        # Thử query gốc trước
        products = get_latest_prices_for_query(query)
        if not products:
            # Thử các biến thể mở rộng (viết tắt)
            for q in expand_query(query):
                if q != query:
                    products = get_latest_prices_for_query(q)
                    if products:
                        break

        # Nếu vẫn không có, tìm trong tất cả sản phẩm
        if not products:
            products = self._search_all_products(query)

        self._query_cache[query] = products
        return products[:limit]

    def _search_all_products(self, query: str) -> List[Dict[str, Any]]:
        """Tìm kiếm trong toàn bộ sản phẩm đã lưu."""
        all_products = get_all_products()
        norm_query = normalize_text(query)
        matched = []
        for p in all_products:
            if matches_query_exact(p.get("name", ""), query):
                matched.append(p)
        return matched

    # ─── Truy xuất chi tiết sản phẩm ───────────────────────────────────
    def retrieve_product_detail(self, product_url: str, source: str) -> Dict[str, Any]:
        """Truy xuất chi tiết 1 sản phẩm: lịch sử giá + dự báo + bình luận."""
        detail = {
            "product_url": product_url,
            "source": source,
            "price_history": [],
            "forecasts": [],
            "comments": [],
        }

        history = get_product_price_history(product_url, source)
        if history:
            detail["price_history"] = history

        forecasts = get_forecasts(product_url, source)
        if forecasts:
            detail["forecasts"] = forecasts

        comments = get_product_comments(product_url, source)
        if comments:
            detail["comments"] = comments[:MAX_CONTEXT_COMMENTS]

        return detail

    # ─── Truy xuất thống kê giá ────────────────────────────────────────
    def retrieve_price_stats(self, product_url: str, source: str) -> Optional[Dict[str, Any]]:
        """Tính thống kê giá cho 1 sản phẩm."""
        history = get_product_price_history(product_url, source)
        if not history or len(history) < 2:
            return None

        prices = []
        for h in history:
            p = h.get("price_value", parse_price(h.get("price", "")))
            if p and p > 0:
                prices.append(float(p))

        if len(prices) < 2:
            return None

        return {
            "current_price": prices[-1],
            "min_price": min(prices),
            "max_price": max(prices),
            "avg_price": sum(prices) / len(prices),
            "price_count": len(prices),
            "trend": "up" if prices[-1] > prices[0] else ("down" if prices[-1] < prices[0] else "stable"),
        }

    # ─── Truy xuất sentiment từ bình luận ──────────────────────────────
    def retrieve_sentiment(self, comments: List[str]) -> Dict[str, Any]:
        """Phân tích sentiment cơ bản từ bình luận (rule-based fallback)."""
        if not comments:
            return {"positive": 0, "neutral": 0, "negative": 0, "sentiment": "neutral"}

        positive_words = ["tốt", "đẹp", "chính hãng", "nhanh", "ưng ý", "hài lòng",
                          "chất lượng", "tuyệt vời", "đáng mua", "ok", "ổn", "xịn"]
        negative_words = ["lỗi", "hỏng", "tệ", "kém", "thất vọng", "không nên",
                          "trầy xước", "cũ", "giả", "nóng", "chậm"]

        pos_count = 0
        neg_count = 0
        for c in comments:
            c_lower = c.lower()
            if any(w in c_lower for w in positive_words):
                pos_count += 1
            elif any(w in c_lower for w in negative_words):
                neg_count += 1

        total = len(comments)
        neutral_count = total - pos_count - neg_count
        sentiment = "positive" if pos_count > neg_count else ("negative" if neg_count > pos_count else "neutral")

        return {
            "positive": round(pos_count / total, 2),
            "neutral": round(neutral_count / total, 2),
            "negative": round(neg_count / total, 2),
            "sentiment": sentiment,
        }

    # ─── Truy xuất ngữ cảnh tổng hợp ───────────────────────────────────
    def retrieve_context(self, query: str) -> Dict[str, Any]:
        """
        Truy xuất toàn bộ ngữ cảnh liên quan đến query.
        Trả về dict chứa products, price_stats, forecasts, sentiment.
        """
        context = {
            "query": query,
            "products": [],
            "product_details": [],
            "price_stats": [],
            "forecasts": [],
            "sentiment": [],
        }

        products = self.retrieve_products(query)
        context["products"] = products

        for p in products:
            product_url = p.get("product_url", "")
            source = p.get("source", "")
            if not product_url or not source:
                continue

            detail = self.retrieve_product_detail(product_url, source)
            context["product_details"].append(detail)

            stats = self.retrieve_price_stats(product_url, source)
            if stats:
                context["price_stats"].append({
                    "name": p.get("name", ""),
                    "source": source,
                    **stats,
                })

            if detail["forecasts"]:
                context["forecasts"].append({
                    "name": p.get("name", ""),
                    "source": source,
                    "forecasts": detail["forecasts"],
                })

            if detail["comments"]:
                sent = self.retrieve_sentiment(detail["comments"])
                context["sentiment"].append({
                    "name": p.get("name", ""),
                    "source": source,
                    **sent,
                })

        return context