"""
RAG Generator - Tạo câu trả lời từ ngữ cảnh đã truy xuất.
Kết hợp template-based generation với dữ liệu thực từ MongoDB.
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

from utils.search_filter import parse_price

logger = logging.getLogger(__name__)


def _format_price(price: float) -> str:
    """Định dạng giá số -> chuỗi VNĐ."""
    if not price or price <= 0:
        return "Liên hệ"
    return f"{int(price):,}đ".replace(",", ".")


def _format_date(date_obj) -> str:
    """Định dạng ngày."""
    if isinstance(date_obj, datetime):
        return date_obj.strftime("%d/%m/%Y")
    return str(date_obj)[:10]


class RAGGenerator:
    """
    Tạo câu trả lời dựa trên ngữ cảnh truy xuất được.
    """

    def generate_search_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời tìm kiếm sản phẩm."""
        query = context.get("query", "")
        products = context.get("products", [])

        if not products:
            return (
                f"🔍 *Kết quả tìm kiếm cho \"{query}\":*\n\n"
                "Hiện chưa có dữ liệu cho sản phẩm này trong cơ sở dữ liệu. 😅\n\n"
                "💡 *Bạn có thể thử:*\n"
                "• Tìm kiếm trên thanh công cụ để scrape dữ liệu mới\n"
                "• Thử các sản phẩm phổ biến như iPhone, Samsung Galaxy, Xiaomi"
            )

        response = f"🔍 *Kết quả tìm kiếm cho \"{query}\":*\n\n"
        for i, p in enumerate(products[:5], 1):
            name = p.get("name", "Không tên")
            price = _format_price(parse_price(p.get("price", "")))
            source = p.get("source", "")
            url = p.get("product_url", "")
            response += f"  {i}. *{name}*\n"
            response += f"     💰 Giá: {price}\n"
            response += f"     🏪 {source}\n"
            response += f"     🔗 {url}\n\n"

        response += f"📌 Tìm thấy {len(products)} sản phẩm."
        response += "\n💡 Bạn muốn so sánh giá hay xem dự báo giá không?"
        return response

    def generate_price_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời về giá sản phẩm."""
        query = context.get("query", "")
        products = context.get("products", [])
        price_stats = context.get("price_stats", [])

        if not products:
            return f"Hiện chưa có dữ liệu giá cho \"{query}\". Hãy tìm kiếm sản phẩm trước! 😊"

        response = f"💰 *Giá sản phẩm \"{query}\":*\n\n"

        # Nhóm theo sản phẩm
        for p in products[:5]:
            name = p.get("name", "")
            price = _format_price(parse_price(p.get("price", "")))
            source = p.get("source", "")
            response += f"  • *{name}*\n"
            response += f"    💰 {price} ({source})\n"

        # Thêm thống kê giá nếu có
        if price_stats:
            response += "\n📊 *Thống kê giá:*\n"
            for stat in price_stats[:3]:
                response += f"  • {stat.get('name', '')} ({stat.get('source', '')}):\n"
                response += f"    - Hiện tại: {_format_price(stat.get('current_price', 0))}\n"
                response += f"    - Thấp nhất: {_format_price(stat.get('min_price', 0))}\n"
                response += f"    - Cao nhất: {_format_price(stat.get('max_price', 0))}\n"
                response += f"    - Trung bình: {_format_price(stat.get('avg_price', 0))}\n"

        return response

    def generate_forecast_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời dự báo giá."""
        query = context.get("query", "")
        forecasts = context.get("forecasts", [])

        if not forecasts:
            return (
                f"📊 *Dự báo giá cho \"{query}\":*\n\n"
                "Hiện chưa có dự báo cho sản phẩm này. "
                "Bạn có thể tạo dự báo qua API hoặc tìm kiếm sản phẩm trước! 😊"
            )

        response = f"📊 *Dự báo giá cho \"{query}\":*\n\n"
        for f in forecasts[:3]:
            name = f.get("name", "")
            source = f.get("source", "")
            response += f"  • *{name}* ({source}):\n"
            for pred in f.get("forecasts", [])[:7]:
                date_str = _format_date(pred.get("predict_date"))
                price = _format_price(pred.get("forecast_price", 0))
                response += f"    - {date_str}: {price}\n"

        return response

    def generate_sentiment_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời về cảm xúc người dùng."""
        query = context.get("query", "")
        sentiment = context.get("sentiment", [])

        if not sentiment:
            return (
                f"💬 *Đánh giá cảm xúc cho \"{query}\":*\n\n"
                "Hiện chưa có bình luận để phân tích. "
                "Hãy tìm kiếm sản phẩm để cào bình luận trước! 😊"
            )

        response = f"💬 *Đánh giá cảm xúc cho \"{query}\":*\n\n"
        for s in sentiment[:3]:
            name = s.get("name", "")
            source = s.get("source", "")
            pos = s.get("positive", 0)
            neu = s.get("neutral", 0)
            neg = s.get("negative", 0)
            label = s.get("sentiment", "neutral")
            emoji = "🟢" if label == "positive" else ("🔴" if label == "negative" else "🟡")
            response += f"  {emoji} *{name}* ({source}):\n"
            response += f"    - Tích cực: {pos*100:.0f}%\n"
            response += f"    - Trung lập: {neu*100:.0f}%\n"
            response += f"    - Tiêu cực: {neg*100:.0f}%\n"

        return response

    def generate_compare_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời so sánh giá."""
        products = context.get("products", [])
        if not products:
            return "Hiện chưa có dữ liệu để so sánh. Hãy tìm kiếm sản phẩm trước! 😊"

        response = "⚖️ *So sánh giá giữa các cửa hàng:*\n\n"
        with_price = [p for p in products if parse_price(p.get("price", "")) > 0]
        if with_price:
            with_price.sort(key=lambda p: parse_price(p.get("price", "")))
            cheapest = with_price[0]
            response += f"🏆 *Giá rẻ nhất:* {cheapest.get('name', '')}\n"
            response += f"   💰 {_format_price(parse_price(cheapest.get('price', '')))} tại {cheapest.get('source', '')}\n\n"

            response += "📋 *Bảng giá:*\n"
            for i, p in enumerate(with_price[:5], 1):
                response += f"  {i}. {p.get('name', '')} - {_format_price(parse_price(p.get('price', '')))} ({p.get('source', '')})\n"

            if len(with_price) > 1:
                diff = parse_price(with_price[-1].get("price", "")) - parse_price(with_price[0].get("price", ""))
                if diff > 0:
                    response += f"\n💡 Chênh lệch cao nhất: {_format_price(diff)}"
        else:
            response += "Chưa có sản phẩm nào có giá hợp lệ để so sánh."

        return response

    def generate_recommendation_response(self, context: Dict[str, Any]) -> str:
        """Tạo câu trả lời gợi ý sản phẩm."""
        products = context.get("products", [])
        if not products:
            return (
                "💡 *Gợi ý sản phẩm:*\n\n"
                "Hiện chưa có dữ liệu sản phẩm. Hãy tìm kiếm sản phẩm trước để có gợi ý tốt nhất! 😊"
            )

        response = "💡 *Gợi ý sản phẩm cho bạn:*\n\n"
        with_price = [p for p in products if parse_price(p.get("price", "")) > 0]
        if with_price:
            with_price.sort(key=lambda p: parse_price(p.get("price", "")))
            response += "Sản phẩm giá tốt nhất:\n"
            for i, p in enumerate(with_price[:5], 1):
                response += f"  {i}. *{p.get('name', '')}*\n"
                response += f"     💰 {_format_price(parse_price(p.get('price', '')))} ({p.get('source', '')})\n"
        else:
            response += "Chưa có sản phẩm nào có giá hợp lệ."

        return response

    def generate_greeting(self) -> str:
        """Tạo câu chào."""
        return (
            "👋 *Xin chào!* Tôi là trợ lý mua sắm thông minh.\n\n"
            "Tôi có thể giúp bạn:\n"
            "🔍 *Tìm kiếm* sản phẩm từ 8 cửa hàng công nghệ\n"
            "💰 *So sánh giá* giữa các cửa hàng\n"
            "📊 *Dự báo giá* bằng AI (LSTM)\n"
            "💬 *Phân tích cảm xúc* bình luận (PhoBERT)\n"
            "💡 *Gợi ý* sản phẩm phù hợp\n\n"
            "Hãy thử hỏi:\n"
            "• \"Tìm iPhone 16 Pro Max\"\n"
            "• \"So sánh Samsung S25 và iPhone 16\"\n"
            "• \"Điện thoại nào giá rẻ nhất?\"\n"
            "• \"Dự báo giá iPhone 15\""
        )

    def generate_help(self) -> str:
        """Tạo câu trợ giúp."""
        return (
            "📖 *Hướng dẫn sử dụng Chatbot*\n\n"
            "Tôi hỗ trợ các lệnh sau:\n\n"
            "🔍 *Tìm kiếm sản phẩm:*\n"
            "  \"Tìm iPhone 16 Pro Max\"\n"
            "  \"Giá Samsung S24 bao nhiêu?\"\n\n"
            "⚖️ *So sánh sản phẩm:*\n"
            "  \"So sánh iPhone 16 và Samsung S25\"\n"
            "  \"Nên mua iPhone hay Samsung?\"\n\n"
            "💰 *Tìm giá rẻ nhất:*\n"
            "  \"iPhone 16 Pro Max giá rẻ nhất\"\n"
            "  \"Điện thoại nào đang giảm giá?\"\n\n"
            "📊 *Dự báo giá:*\n"
            "  \"Dự báo giá iPhone 15 tuần tới\"\n"
            "  \"Giá Samsung S24 sẽ tăng hay giảm?\"\n\n"
            "💬 *Phân tích cảm xúc:*\n"
            "  \"Đánh giá iPhone 16 thế nào?\"\n"
            "  \"Bình luận về Samsung S25 ra sao?\"\n\n"
            "💡 *Gợi ý:*\n"
            "  \"Gợi ý điện thoại tầm 10 triệu\"\n"
            "  \"Nên mua điện thoại nào?\""
        )