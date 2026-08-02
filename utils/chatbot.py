"""
Shopping Assistant Chatbot Engine.
Rule-based chatbot that helps users find products, compare prices, and get recommendations.
Uses existing data from MongoDB and search infrastructure.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

from utils.db import (
    get_all_products, get_latest_prices_for_query, get_product_price_history,
    get_forecasts, get_unique_queries,
)
from utils.search_filter import (
    filter_comparable_phones, parse_price, normalize_text, expand_query,
    matches_query_exact, is_phone_product, build_canonical_key,
)
from utils.recommendation_engine import (
    calculate_pqs, calculate_price_statistics, get_buy_recommendation,
    analyze_product,
)

logger = logging.getLogger(__name__)

# ========== INTENT DETECTION ==========

INTENT_PATTERNS = {
    "greeting": [
        r"\b(xin chào|chào|hello|hi|hey|chào bạn|chào bot)\b",
    ],
    "search": [
        r"\b(tìm|kiếm|tìm kiếm|có.*không|bán|giá)\s+(.+)$",
        r"\b(.+)\s+(giá\s*bao\s*nhiêu|giá\s*thế\s*nào|bằng\s*bao\s*nhiêu)\b",
    ],
    "compare": [
        r"\b(so\s*sánh|compare|khác\s*nhau|nên\s*mua)\b",
    ],
    "cheapest": [
        r"\b(rẻ\s*nhất|giá\s*rẻ|thấp\s*nhất|tiết\s*kiệm|best\s*price)\b",
    ],
    "recommend": [
        r"\b(gợi\s*ý|recommend|nên\s*mua|tư\s*vấn|sản\s*phẩm\s*nào|loại\s*nào)\b",
    ],
    "forecast": [
        r"\b(dự\s*đoán|dự\s*báo|forecast|predict|tương\s*lai|sẽ\s*giảm|sẽ\s*tăng)\b",
    ],
    "history": [
        r"\b(lịch\s*sử|giá\s*cũ|đã\s*thay\s*đổi|biến\s*động|tăng|giảm)\b",
    ],
    "help": [
        r"\b(help|trợ\s*giúp|hướng\s*dẫn|có\s*thể\s*làm\s*gì|tính\s*năng)\b",
    ],
    "thanks": [
        r"\b(cảm\s*ơn|cám\s*ơn|thanks|thank\s*you)\b",
    ],
    "goodbye": [
        r"\b(tạm\s*biệt|bye|goodbye|hẹn\s*gặp|lát\s*nữa)\b",
    ],
}

# Danh sách sản phẩm mẫu để gợi ý khi không có dữ liệu thực
POPULAR_PHONES = [
    {"name": "iPhone 16 Pro Max", "brand": "Apple"},
    {"name": "iPhone 16 Pro", "brand": "Apple"},
    {"name": "iPhone 16", "brand": "Apple"},
    {"name": "Samsung Galaxy S25 Ultra", "brand": "Samsung"},
    {"name": "Samsung Galaxy S25", "brand": "Samsung"},
    {"name": "Samsung Galaxy A56", "brand": "Samsung"},
    {"name": "Xiaomi 15 Pro", "brand": "Xiaomi"},
    {"name": "Xiaomi Redmi Note 14", "brand": "Xiaomi"},
    {"name": "OPPO Find X8 Pro", "brand": "OPPO"},
    {"name": "OPPO Reno 13", "brand": "OPPO"},
    {"name": "Vivo V50", "brand": "Vivo"},
    {"name": "Realme GT 7 Pro", "brand": "Realme"},
]


def detect_intent(message: str) -> Tuple[str, str]:
    """
    Detect user intent from message.
    Returns (intent, extracted_query).
    """
    msg_lower = message.lower().strip()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, msg_lower)
            if match:
                # Extract query from search patterns
                if intent == "search":
                    # Group 2 is the search term
                    query = match.group(2) if match.lastindex >= 2 else match.group(1)
                    # Clean up query
                    query = re.sub(r"\b(giá\s*bao\s*nhiêu|giá\s*thế\s*nào|bằng\s*bao\s*nhiêu)\s*", "", query).strip()
                    return intent, query
                return intent, match.group(0)

    # Default: treat as search if contains product-like keywords
    product_keywords = ["iphone", "samsung", "xiaomi", "oppo", "vivo", "realme",
                        "nokia", "huawei", "honor", "oneplus", "pixel", "điện thoại",
                        "galaxy", "redmi", "poco", "reno", "find"]
    if any(kw in msg_lower for kw in product_keywords):
        return "search", message.strip()

    return "unknown", message.strip()


def format_price(price_str: str) -> str:
    """Format price string for display."""
    if not price_str or price_str == "Liên hệ":
        return "Liên hệ"
    # If already formatted with dots
    if "đ" in price_str:
        return price_str
    # Try to format raw number
    try:
        num = float(re.sub(r"[^\d]", "", price_str))
        if num > 0:
            return f"{num:,.0f} đ".replace(",", ".")
    except ValueError:
        pass
    return price_str


def get_product_recommendations(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Get product recommendations from DB or suggest popular phones."""
    # Try to get from DB first
    products = get_latest_prices_for_query(query)
    if products:
        return products[:limit]

    # Try expanded queries
    expanded = expand_query(query)
    for q in expanded:
        if q != query:
            products = get_latest_prices_for_query(q)
            if products:
                return products[:limit]

    return []


def format_product_card(product: Dict[str, Any], index: int = 1) -> str:
    """Format a single product as a card text."""
    name = product.get("name", "Không tên")
    price = format_price(product.get("price", ""))
    source = product.get("source", "")
    url = product.get("product_url", "")
    return (
        f"  {index}. *{name}*\n"
        f"     💰 Giá: {price}\n"
        f"     🏪 {source}\n"
        f"     🔗 {url}\n"
    )


def handle_greeting() -> str:
    """Handle greeting intent."""
    return (
        "👋 *Xin chào!* Tôi là trợ lý mua sắm thông minh.\n\n"
        "Tôi có thể giúp bạn:\n"
        "🔍 *Tìm kiếm* sản phẩm từ 7 cửa hàng công nghệ\n"
        "💰 *So sánh giá* giữa các cửa hàng\n"
        "📊 *Dự báo giá* bằng AI (LSTM)\n"
        "💡 *Gợi ý* sản phẩm phù hợp\n\n"
        "Hãy thử hỏi:\n"
        "• \"Tìm iPhone 16 Pro Max\"\n"
        "• \"So sánh Samsung S25 và iPhone 16\"\n"
        "• \"Điện thoại nào giá rẻ nhất?\"\n"
        "• \"Dự báo giá iPhone 15\""
    )


def handle_help() -> str:
    """Handle help intent."""
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
        "💡 *Gợi ý:*\n"
        "  \"Gợi ý điện thoại tầm 10 triệu\"\n"
        "  \"Nên mua điện thoại nào?\""
    )


def handle_search(query: str) -> str:
    """Handle search intent - find products matching query."""
    if not query:
        return "Bạn muốn tìm sản phẩm gì? Hãy nhập tên sản phẩm nhé! 😊"

    # Try to get products from DB
    products = get_product_recommendations(query)

    if products:
        response = f"🔍 *Kết quả tìm kiếm cho \"{query}\":*\n\n"
        for i, p in enumerate(products[:5], 1):
            response += format_product_card(p, i)
        response += f"\n📌 Tìm thấy {len(products)} sản phẩm."
        response += "\n💡 Bạn muốn so sánh giá hay xem dự báo giá không?"
        return response

    # No results in DB - suggest popular phones
    response = f"🔍 *Tìm kiếm \"{query}\":*\n\n"
    response += "Hiện chưa có dữ liệu cho sản phẩm này trong cơ sở dữ liệu. 😅\n\n"
    response += "💡 *Bạn có thể thử:*\n"
    response += "• Tìm kiếm trên thanh công cụ để scrape dữ liệu mới\n"
    response += "• Thử các sản phẩm phổ biến:\n"

    # Suggest popular phones
    for i, phone in enumerate(POPULAR_PHONES[:5], 1):
        response += f"  {i}. {phone['name']}\n"

    response += "\nHoặc gõ tên sản phẩm bạn quan tâm!"
    return response


def handle_compare(message: str) -> str:
    """Handle compare intent - compare two products."""
    # Extract product names
    # Patterns: "so sánh A và B", "A vs B", "A hay B"
    patterns = [
        r"so\s*sánh\s+(.+?)\s+(?:và|vs|với)\s+(.+)",
        r"(.+?)\s+(?:vs|v\.s)\s+(.+)",
        r"(.+?)\s+(?:hay|hoặc)\s+(.+)",
    ]

    product_a, product_b = None, None
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            product_a = match.group(1).strip()
            product_b = match.group(2).strip()
            break

    if not product_a or not product_b:
        return (
            "Để so sánh sản phẩm, bạn hãy nói:\n"
            "• \"So sánh iPhone 16 và Samsung S25\"\n"
            "• \"iPhone 16 vs Samsung S24\"\n"
            "• \"Nên mua iPhone hay Samsung?\""
        )

    # Get products for both
    products_a = get_product_recommendations(product_a)
    products_b = get_product_recommendations(product_b)

    response = f"⚖️ *So sánh: {product_a} vs {product_b}*\n\n"

    if products_a:
        response += f"📱 *{product_a}*\n"
        best_a = min(products_a, key=lambda p: parse_price(p.get("price", "")))
        response += f"  💰 Giá rẻ nhất: {format_price(best_a.get('price', ''))}\n"
        response += f"  🏪 Tại: {best_a.get('source', '')}\n"
        response += f"  📊 Số cửa hàng: {len(products_a)}\n\n"
    else:
        response += f"📱 *{product_a}*: Chưa có dữ liệu\n\n"

    if products_b:
        response += f"📱 *{product_b}*\n"
        best_b = min(products_b, key=lambda p: parse_price(p.get("price", "")))
        response += f"  💰 Giá rẻ nhất: {format_price(best_b.get('price', ''))}\n"
        response += f"  🏪 Tại: {best_b.get('source', '')}\n"
        response += f"  📊 Số cửa hàng: {len(products_b)}\n\n"
    else:
        response += f"📱 *{product_b}*: Chưa có dữ liệu\n\n"

    # Price comparison if both have data
    if products_a and products_b:
        price_a = parse_price(best_a.get("price", ""))
        price_b = parse_price(best_b.get("price", ""))
        if price_a > 0 and price_b > 0:
            diff = abs(price_a - price_b)
            cheaper = product_a if price_a < price_b else product_b
            response += f"📊 *Kết luận:*\n"
            response += f"  • {cheaper} rẻ hơn {format_price(str(diff))}\n"
            if price_a < price_b:
                response += f"  • Tiết kiệm {((price_b - price_a) / price_b * 100):.1f}% so với {product_b}\n"
            else:
                response += f"  • Tiết kiệm {((price_a - price_b) / price_a * 100):.1f}% so với {product_a}\n"

    response += "\n💡 Bạn muốn xem chi tiết sản phẩm nào không?"
    return response


def handle_cheapest(message: str) -> str:
    """Handle cheapest price intent."""
    # Extract product name
    query = re.sub(r"\b(rẻ\s*nhất|giá\s*rẻ|thấp\s*nhất|tiết\s*kiệm|best\s*price)\b", "", message, flags=re.IGNORECASE).strip()

    if not query:
        # Show all products sorted by price
        all_products = get_all_products()
        if all_products:
            # Sort by price
            with_price = [p for p in all_products if parse_price(p.get("price", "")) > 0]
            with_price.sort(key=lambda p: parse_price(p.get("price", "")))

            response = "💰 *Top sản phẩm giá rẻ nhất:*\n\n"
            for i, p in enumerate(with_price[:10], 1):
                response += format_product_card(p, i)
            return response
        return "Hiện chưa có dữ liệu sản phẩm nào. Hãy tìm kiếm sản phẩm trước nhé! 😊"

    # Find cheapest for specific product
    products = get_product_recommendations(query)
    if products:
        with_price = [p for p in products if parse_price(p.get("price", "")) > 0]
        if with_price:
            cheapest = min(with_price, key=lambda p: parse_price(p.get("price", "")))
            response = f"💰 *Giá rẻ nhất cho \"{query}\":*\n\n"
            response += format_product_card(cheapest)
            response += f"\n📊 Tổng cộng {len(with_price)} cửa hàng bán sản phẩm này."
            return response

    return f"Hiện chưa có dữ liệu giá cho \"{query}\". Hãy thử tìm kiếm sản phẩm trước! 😊"


def handle_forecast(message: str) -> str:
    """Handle price forecast intent."""
    # Extract product name
    query = re.sub(r"\b(dự\s*đoán|dự\s*báo|forecast|predict|tương\s*lai|sẽ\s*giảm|sẽ\s*tăng)\b", "", message, flags=re.IGNORECASE).strip()

    if not query:
        return "Bạn muốn dự báo giá cho sản phẩm nào? Ví dụ: \"Dự báo giá iPhone 15\""

    # Get products
    products = get_product_recommendations(query)
    if not products:
        return f"Hiện chưa có dữ liệu cho \"{query}\" để dự báo. Hãy tìm kiếm sản phẩm trước! 😊"

    # Get price history and prediction for first product
    product = products[0]
    product_url = product.get("product_url", "")
    source = product.get("source", "")

    if not product_url or not source:
        return "Không thể lấy thông tin chi tiết sản phẩm để dự báo."

    # Check for forecasts
    forecasts = get_forecasts(product_url, source)
    history = get_product_price_history(product_url, source)

    response = f"📊 *Dự báo giá: {product.get('name', query)}*\n\n"

    if history:
        response += f"📈 *Lịch sử giá:* {len(history)} mốc thời gian\n"
        # Show price trend
        prices = []
        for h in history:
            p = parse_price(h.get("price", ""))
            if p > 0:
                prices.append(p)
        if len(prices) >= 2:
            first_price = prices[0]
            last_price = prices[-1]
            change = last_price - first_price
            change_pct = (change / first_price) * 100
            if change > 0:
                response += f"  📈 Giá đã tăng {format_price(str(abs(change)))} ({change_pct:.1f}%)\n"
            elif change < 0:
                response += f"  📉 Giá đã giảm {format_price(str(abs(change)))} ({abs(change_pct):.1f}%)\n"
            else:
                response += f"  ➡️ Giá ổn định\n"

    if forecasts:
        preds = forecasts
        if preds:
            response += f"\n🔮 *Dự báo 7 ngày tới:*\n"
            for p in preds[:7]:
                date_obj = p.get("predict_date")
                date_str = date_obj.strftime("%d/%m/%Y") if date_obj else "N/A"
                price_str = format_price(str(int(p.get("forecast_price", 0))))
                response += f"  • {date_str}: {price_str}\n"

            # Trend analysis
            current_price = 0
            if history:
                last_history_price = parse_price(history[-1].get("price", ""))
                if last_history_price > 0:
                    current_price = last_history_price
            
            last_pred_price = preds[-1].get("forecast_price", 0)

            if current_price > 0 and last_pred_price > 0:
                if last_pred_price > current_price * 1.01: # Increase if > 1% change
                    response += f"\n📈 *Xu hướng:* Giá có thể tăng trong tuần tới."
                elif last_pred_price < current_price * 0.99: # Decrease if > 1% change
                    response += f"\n📉 *Xu hướng:* Giá có thể giảm trong tuần tới."
                else:
                    response += f"\n➡️ *Xu hướng:* Giá có thể sẽ ổn định."
            else:
                response += "\n(Chưa đủ dữ liệu để xác định xu hướng)"
    else:
        response += "\n⏳ Hiện chưa có dự báo cho sản phẩm này. Bạn có thể tạo dự báo qua API."

    return response


def handle_recommend(message: str) -> str:
    """Handle recommendation intent."""
    # Check if user mentioned a budget
    budget_match = re.search(r"(\d+)\s*(triệu|tr|m)", message, re.IGNORECASE)
    budget = None
    if budget_match:
        budget = int(budget_match.group(1)) * 1_000_000

    response = "💡 *Gợi ý sản phẩm cho bạn:*\n\n"

    if budget:
        response += f"Với ngân sách {budget:,} đ, bạn có thể tham khảo:\n\n".replace(",", ".")

    # Get all products and filter by budget
    all_products = get_all_products()
    if all_products:
        with_price = [p for p in all_products if parse_price(p.get("price", "")) > 0]
        if budget:
            filtered = [p for p in with_price if parse_price(p.get("price", "")) <= budget]
            if filtered:
                filtered.sort(key=lambda p: parse_price(p.get("price", "")))
                for i, p in enumerate(filtered[:5], 1):
                    response += format_product_card(p, i)
            else:
                response += "Không tìm thấy sản phẩm trong tầm giá này.\n\n"
                # Suggest cheapest
                with_price.sort(key=lambda p: parse_price(p.get("price", "")))
                response += "Sản phẩm giá rẻ nhất hiện có:\n"
                for i, p in enumerate(with_price[:3], 1):
                    response += format_product_card(p, i)
        else:
            # Show popular products
            response += "Các sản phẩm phổ biến:\n\n"
            for i, phone in enumerate(POPULAR_PHONES[:5], 1):
                # Check if we have data for this phone
                data = get_latest_prices_for_query(phone["name"])
                if data:
                    cheapest = min(data, key=lambda p: parse_price(p.get("price", "")))
                    response += f"  {i}. *{phone['name']}* - {format_price(cheapest.get('price', ''))}\n"
                else:
                    response += f"  {i}. *{phone['name']}* (Chưa có dữ liệu giá)\n"
    else:
        response += "Các sản phẩm phổ biến:\n\n"
        for i, phone in enumerate(POPULAR_PHONES[:5], 1):
            response += f"  {i}. *{phone['name']}*\n"

    response += "\n💡 Bạn muốn tìm sản phẩm cụ thể nào không?"
    return response


def handle_history(message: str) -> str:
    """Handle price history intent."""
    query = re.sub(r"\b(lịch\s*sử|giá\s*cũ|đã\s*thay\s*đổi|biến\s*động|tăng|giảm)\b", "", message, flags=re.IGNORECASE).strip()

    if not query:
        return "Bạn muốn xem lịch sử giá cho sản phẩm nào? Ví dụ: \"Lịch sử giá iPhone 15\""

    products = get_product_recommendations(query)
    if not products:
        return f"Hiện chưa có dữ liệu cho \"{query}\"."

    product = products[0]
    history = get_product_price_history(
        product.get("product_url", ""),
        product.get("source", "")
    )

    if not history or len(history) < 2:
        return f"\"{product.get('name', query)}\" chưa có đủ lịch sử giá để hiển thị."

    response = f"📈 *Lịch sử giá: {product.get('name', query)}*\n"
    response += f"🏪 {product.get('source', '')}\n\n"

    # Show price changes
    prices = []
    for h in history:
        p = parse_price(h.get("price", ""))
        if p > 0:
            prices.append({"price": p, "date": h.get("scraped_at", "")})

    if len(prices) >= 2:
        response += f"📊 *Thống kê:*\n"
        response += f"  • Giá đầu: {format_price(str(int(prices[0]['price'])))}\n"
        response += f"  • Giá hiện tại: {format_price(str(int(prices[-1]['price'])))}\n"
        response += f"  • Cao nhất: {format_price(str(int(max(p['price'] for p in prices))))}\n"
        response += f"  • Thấp nhất: {format_price(str(int(min(p['price'] for p in prices))))}\n"
        response += f"  • Số lần cập nhật: {len(prices)}\n"

        # Show last 5 entries
        response += f"\n📋 *5 lần cập nhật gần nhất:*\n"
        for h in history[-5:]:
            date = h.get("scraped_at", "")
            if isinstance(date, datetime):
                date = date.strftime("%d/%m/%Y")
            elif isinstance(date, str):
                date = date[:10]
            price = format_price(h.get("price", ""))
            response += f"  • {date}: {price}\n"

    return response


def handle_thanks() -> str:
    """Handle thanks intent."""
    return (
        "😊 *Cảm ơn bạn!*\n\n"
        "Rất vui được giúp đỡ bạn. Nếu cần thêm thông tin gì, "
        "đừng ngần ngại hỏi tôi nhé!\n\n"
        "Chúc bạn mua sắm vui vẻ! 🎉"
    )


def handle_goodbye() -> str:
    """Handle goodbye intent."""
    return (
        "👋 *Tạm biệt!*\n\n"
        "Cảm ơn bạn đã sử dụng trợ lý mua sắm.\n"
        "Hẹn gặp lại bạn lần sau! 😊\n\n"
        "💡 Gõ \"help\" nếu cần hỗ trợ thêm."
    )


def handle_unknown(message: str) -> str:
    """Handle unknown intent - try to search anyway."""
    # Try treating as search
    if len(message) > 2:
        return handle_search(message)

    return (
        "🤔 *Xin lỗi, tôi chưa hiểu ý bạn.*\n\n"
        "Bạn có thể thử:\n"
        "• \"Tìm iPhone 16\"\n"
        "• \"So sánh Samsung và iPhone\"\n"
        "• \"Giá rẻ nhất\"\n"
        "• \"Dự báo giá\"\n"
        "• Gõ \"help\" để xem hướng dẫn"
    )


def get_chat_response(message: str) -> Dict[str, Any]:
    """
    Main entry point for chatbot.
    Returns response dict with text and optional product data.
    """
    intent, query = detect_intent(message)

    logger.info(f"Chatbot intent={intent}, query='{query}', message='{message[:50]}'")

    # Route to appropriate handler
    handlers = {
        "greeting": handle_greeting,
        "help": handle_help,
        "search": lambda: handle_search(query),
        "compare": lambda: handle_compare(message),
        "cheapest": lambda: handle_cheapest(message),
        "forecast": lambda: handle_forecast(message),
        "recommend": lambda: handle_recommend(message),
        "history": lambda: handle_history(message),
        "thanks": handle_thanks,
        "goodbye": handle_goodbye,
        "unknown": lambda: handle_unknown(message),
    }

    handler = handlers.get(intent, handlers["unknown"])
    try:
        text = handler()
    except Exception as e:
        logger.error(f"Chatbot error: {e}", exc_info=True)
        text = (
            "❌ *Có lỗi xảy ra.*\n\n"
            "Xin lỗi, tôi đang gặp sự cố kỹ thuật. "
            "Vui lòng thử lại sau! 🙏"
        )

    return {
        "text": text,
        "intent": intent,
        "query": query if intent == "search" else None,
    }