"""
Utils package.

Dùng lazy import (PEP 562) để tránh kéo theo các dependency nặng
(playwright, pydantic, ...) khi chỉ cần import một module con như utils.db.
"""
from typing import Any

__all__ = [
    "BrowserManager",
    "init_db", "save_search_results", "get_unique_queries", "close_db",
    "get_product_price_history", "get_products_with_price_history",
    "save_prediction", "get_prediction", "get_latest_prices_for_query",
    "Exporter",
    "train_and_predict",
    "filter_comparable_phones",
    "calculate_pqs", "calculate_price_statistics", "get_buy_recommendation",
    "analyze_product", "analyze_products_batch",
]


def __getattr__(name: str) -> Any:
    if name == "BrowserManager":
        from utils.browser import BrowserManager
        return BrowserManager
    if name in (
        "init_db", "save_search_results", "get_unique_queries", "close_db",
        "get_product_price_history", "get_products_with_price_history",
        "get_latest_prices_for_query",
    ):
        from utils.db import (
            init_db, save_search_results, get_unique_queries, close_db,
            get_product_price_history, get_products_with_price_history,
            get_latest_prices_for_query,
        )
        return {
            "init_db": init_db,
            "save_search_results": save_search_results,
            "get_unique_queries": get_unique_queries,
            "close_db": close_db,
            "get_product_price_history": get_product_price_history,
            "get_products_with_price_history": get_products_with_price_history,
            "get_latest_prices_for_query": get_latest_prices_for_query,
        }[name]
    if name == "Exporter":
        from utils.exporter import Exporter
        return Exporter
    if name == "filter_comparable_phones":
        from utils.search_filter import filter_comparable_phones
        return filter_comparable_phones
    if name in (
        "calculate_pqs", "calculate_price_statistics", "get_buy_recommendation",
        "analyze_product", "analyze_products_batch",
    ):
        from utils.recommendation_engine import (
            calculate_pqs, calculate_price_statistics, get_buy_recommendation,
            analyze_product, analyze_products_batch,
        )
        return {
            "calculate_pqs": calculate_pqs,
            "calculate_price_statistics": calculate_price_statistics,
            "get_buy_recommendation": get_buy_recommendation,
            "analyze_product": analyze_product,
            "analyze_products_batch": analyze_products_batch,
        }[name]
    raise AttributeError(f"module 'utils' has no attribute '{name}'")