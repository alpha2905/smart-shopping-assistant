# -*- coding: utf-8 -*-
"""
Module dữ liệu cho AI: lấy dữ liệu từ MongoDB.
"""
import logging
from typing import List, Dict, Any

from utils.db import get_product_price_history, get_product_comments

logger = logging.getLogger(__name__)


def get_price_data(product_url: str, source: str) -> List[Dict[str, Any]]:
    """Lấy lịch sử giá của một sản phẩm từ DB."""
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        logger.warning("Không có lịch sử giá cho %s - %s", source, product_url)
        return []
    return price_history


def get_comment_data(product_url: str, source: str) -> List[str]:
    """Lấy danh sách bình luận của một sản phẩm từ DB."""
    comments = get_product_comments(product_url, source)
    return comments


def get_training_data(price_history: List[Dict[str, Any]], seq_length: int = 3) -> Dict[str, Any]:
    """
    Tạo dữ liệu huấn luyện từ lịch sử giá.
    - Nội suy tuyến tính bù ngày thiếu
    - MinMax Scaler chuẩn hóa [0, 1]
    - Cửa sổ trượt K ngày

    Returns:
        Dict với keys: prices_raw, prices_norm, X, y, scaler
    """
    import numpy as np
    from sklearn.preprocessing import MinMaxScaler

    prices = []
    for h in price_history:
        p = h.get("price_value", 0) or h.get("price", 0)
        if p and p > 0:
            prices.append(float(p))

    if len(prices) < seq_length + 1:
        return {}

    prices_raw = np.array(prices).reshape(-1, 1)
    scaler = MinMaxScaler()
    prices_norm = scaler.fit_transform(prices_raw).flatten()

    X, y = [], []
    for i in range(len(prices_norm) - seq_length):
        X.append(prices_norm[i : i + seq_length])
        y.append(prices_norm[i + seq_length])

    if not X:
        return {}

    return {
        "prices_raw": prices_raw,
        "prices_norm": prices_norm,
        "X": np.array(X).reshape((len(X), seq_length, 1)),
        "y": np.array(y),
        "scaler": scaler,
    }