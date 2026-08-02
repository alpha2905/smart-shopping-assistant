"""
Price Trend Classification Module.

Features:
- Price trend classification
"""

import logging

logger = logging.getLogger(__name__)

PRICE_CHANGE_THRESHOLDS = {
    "drop_strong": -0.05,    # Giảm mạnh >= 5%
    "drop_light": -0.01,     # Giảm nhẹ 1-5%
    "stable": 0.01,          # Ổn định ±1%
    "rise_light": 0.05,      # Tăng nhẹ 1-5%
    "rise_strong": 0.05,     # Tăng mạnh >= 5%
}

def classify_price_change(change_pct: float) -> str:
    """
    Phân loại mức tăng/giảm giá dựa trên phần trăm thay đổi.
    
    Args:
        change_pct: Phần trăm thay đổi giá (số thập phân, VD: -0.07 = giảm 7%)
        
    Returns:
        str: "drop_strong" | "drop_light" | "stable" | "rise_light" | "rise_strong"
    """
    if change_pct <= PRICE_CHANGE_THRESHOLDS["drop_strong"]:
        return "drop_strong"
    elif change_pct <= PRICE_CHANGE_THRESHOLDS["drop_light"]:
        return "drop_light"
    elif change_pct <= PRICE_CHANGE_THRESHOLDS["stable"]:
        return "stable"
    elif change_pct <= PRICE_CHANGE_THRESHOLDS["rise_light"]:
        return "rise_light"
    else:
        return "rise_strong"

def get_change_label(vn: str) -> str:
    """Map change type to Vietnamese label."""
    labels = {
        "drop_strong": "Giảm mạnh",
        "drop_light": "Giảm nhẹ",
        "stable": "Ổn định",
        "rise_light": "Tăng nhẹ",
        "rise_strong": "Tăng mạnh",
    }
    return labels.get(vn, "Không xác định")