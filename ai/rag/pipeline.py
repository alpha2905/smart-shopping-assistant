# -*- coding: utf-8 -*-
"""
RAG Pipeline - Kết nối Retriever và Generator.
Xử lý câu hỏi người dùng, truy xuất ngữ cảnh, tạo câu trả lời.
"""
import logging
import re
from typing import Dict, Any, Tuple

from ai.rag.retriever import RAGRetriever
from ai.rag.generator import RAGGenerator

logger = logging.getLogger(__name__)

# Pattern nhận diện intent
INTENT_PATTERNS = {
    "greeting": [r"\b(xin chào|chào|hello|hi|hey|chào bạn|chào bot)\b"],
    "search": [r"\b(tìm|kiếm|tìm kiếm|có.*không|bán)\s+(.+)$"],
    "price": [r"\b(giá|bao nhiêu|bằng bao nhiêu|thế nào)\b"],
    "compare": [r"\b(so sánh|compare|khác nhau|nên mua)\b"],
    "cheapest": [r"\b(rẻ nhất|giá rẻ|thấp nhất|tiết kiệm|best price)\b"],
    "forecast": [r"\b(dự đoán|dự báo|forecast|predict|tương lai|sẽ giảm|sẽ tăng)\b"],
    "sentiment": [r"\b(đánh giá|bình luận|cảm xúc|sentiment|review|nhận xét)\b"],
    "recommend": [r"\b(gợi ý|recommend|tư vấn|sản phẩm nào|loại nào)\b"],
    "help": [r"\b(help|trợ giúp|hướng dẫn|có thể làm gì|tính năng)\b"],
    "thanks": [r"\b(cảm ơn|cám ơn|thanks|thank you)\b"],
    "goodbye": [r"\b(tạm biệt|bye|goodbye|hẹn gặp|lát nữa)\b"],
}


class RAGPipeline:
    """
    Pipeline RAG hoàn chỉnh cho Smart Shopping Assistant.
    Flow: Nhận câu hỏi → Nhận diện intent → Truy xuất ngữ cảnh → Tạo câu trả lời.
    """

    def __init__(self):
        self.retriever = RAGRetriever()
        self.generator = RAGGenerator()

    def detect_intent(self, message: str) -> Tuple[str, str]:
        """Nhận diện intent và trích xuất query từ câu hỏi."""
        msg_lower = message.lower().strip()

        # Ưu tiên kiểm tra greeting/help/thanks/goodbye trước
        for intent in ("greeting", "help", "thanks", "goodbye"):
            for pattern in INTENT_PATTERNS[intent]:
                if re.search(pattern, msg_lower):
                    return intent, ""

        # Kiểm tra các intent cần query
        for intent in ("forecast", "sentiment", "recommend", "cheapest", "price", "compare", "search"):
            for pattern in INTENT_PATTERNS[intent]:
                match = re.search(pattern, msg_lower)
                if match:
                    # Trích xuất query
                    if match.lastindex and match.lastindex >= 2:
                        query = match.group(match.lastindex).strip()
                    else:
                        query = match.group(0).strip()

                    # Làm sạch query
                    query = re.sub(r"\b(với giá|giá bao nhiêu|giá thế nào|bằng bao nhiêu)\b", "", query)
                    query = re.sub(r"\b(dự đoán|dự báo|forecast|predict|tương lai)\b", "", query)
                    query = re.sub(r"\b(đánh giá|bình luận|cảm xúc|sentiment|review|nhận xét)\b", "", query)
                    query = re.sub(r"\b(gợi ý|recommend|tư vấn)\b", "", query)
                    query = re.sub(r"\b(rẻ nhất|giá rẻ|thấp nhất|tiết kiệm)\b", "", query)
                    query = re.sub(r"\b(so sánh)\b", "", query)
                    query = re.sub(r"\s+", " ", query).strip()

                    # Nếu query rỗng (vd: "gợi ý điện thoại"), dùng message gốc
                    if not query:
                        query = message.strip()
                    return intent, query

        # Fallback: nếu có từ khóa sản phẩm → search
        product_keywords = ["iphone", "samsung", "xiaomi", "oppo", "vivo", "realme",
                            "nokia", "huawei", "honor", "điện thoại", "galaxy",
                            "redmi", "poco", "reno", "find"]
        if any(kw in msg_lower for kw in product_keywords):
            return "search", message.strip()

        return "unknown", message.strip()

    def process(self, message: str) -> Dict[str, Any]:
        """
        Xử lý câu hỏi người dùng qua RAG pipeline.

        Returns:
            Dict {"text": câu trả lời, "intent": intent, "query": query}
        """
        intent, query = self.detect_intent(message)
        logger.info("RAG pipeline: intent=%s, query='%s'", intent, query)

        try:
            text = self._route(intent, query, message)
        except Exception as e:
            logger.error("Lỗi RAG pipeline: %s", e, exc_info=True)
            text = (
                "❌ *Có lỗi xảy ra.*\n\n"
                "Xin lỗi, tôi đang gặp sự cố kỹ thuật. Vui lòng thử lại sau! 🙏"
            )

        return {
            "text": text,
            "intent": intent,
            "query": query if intent in ("search", "price", "forecast", "sentiment", "recommend", "cheapest", "compare") else None,
        }

    def _route(self, intent: str, query: str, message: str) -> str:
        """Điều hướng đến generator phù hợp."""
        if intent == "greeting":
            return self.generator.generate_greeting()
        if intent == "help":
            return self.generator.generate_help()
        if intent == "thanks":
            return "😊 *Cảm ơn bạn!* Rất vui được giúp đỡ. Chúc bạn mua sắm vui vẻ! 🎉"
        if intent == "goodbye":
            return "👋 *Tạm biệt!* Cảm ơn bạn đã sử dụng trợ lý mua sắm. Hẹn gặp lại! 😊"

        # Truy xuất ngữ cảnh cho các intent cần dữ liệu
        context = self.retriever.retrieve_context(query)

        if intent == "search":
            return self.generator.generate_search_response(context)
        if intent == "price":
            return self.generator.generate_price_response(context)
        if intent == "cheapest":
            return self.generator.generate_price_response(context)
        if intent == "compare":
            return self.generator.generate_compare_response(context)
        if intent == "forecast":
            return self.generator.generate_forecast_response(context)
        if intent == "sentiment":
            return self.generator.generate_sentiment_response(context)
        if intent == "recommend":
            return self.generator.generate_recommendation_response(context)

        # unknown → thử search
        return self.generator.generate_search_response(context)


# Singleton để tái sử dụng trong toàn app
_rag_pipeline: RAGPipeline = None


def get_rag_pipeline() -> RAGPipeline:
    """Lấy RAG pipeline singleton."""
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = RAGPipeline()
    return _rag_pipeline


def get_chat_response_rag(message: str) -> Dict[str, Any]:
    """Entry point cho chatbot sử dụng RAG pipeline."""
    pipeline = get_rag_pipeline()
    return pipeline.process(message)