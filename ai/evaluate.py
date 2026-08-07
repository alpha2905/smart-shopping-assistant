# -*- coding: utf-8 -*-
"""
Đánh giá độ chính xác của mô hình dự báo giá LSTM.
MAE, RMSE, MAPE, Direction Accuracy và kiểm chứng dự báo với giá thực tế.
"""
import logging
from datetime import datetime
from typing import List, Dict, Any

import numpy as np

from utils.db import get_unverified_forecasts, get_product_price_history, mark_forecasts_as_verified

logger = logging.getLogger(__name__)


def calculate_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error - Sai số tuyệt đối trung bình."""
    return float(np.mean(np.abs(y_true - y_pred)))


def calculate_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error - Sai số toàn phương trung bình."""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Percentage Error - Sai số phần trăm tuyệt đối trung bình."""
    mask = y_true != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def calculate_direction_accuracy(actual_prices: List[float], predicted_prices: List[float]) -> float:
    """
    Độ chính xác dự báo đúng hướng (tăng/giảm/ổn định).
    So sánh hướng thay đổi giữa các điểm liên tiếp.
    """
    if len(actual_prices) < 2 or len(predicted_prices) < 2:
        return 0.0

    correct = 0
    total = 0
    for i in range(1, min(len(actual_prices), len(predicted_prices))):
        actual_change = actual_prices[i] - actual_prices[i - 1]
        predicted_change = predicted_prices[i] - predicted_prices[i - 1]

        actual_direction = "stable" if abs(actual_change) == 0 else ("rise" if actual_change > 0 else "drop")
        predicted_direction = "stable" if abs(predicted_change) == 0 else ("rise" if predicted_change > 0 else "drop")

        if actual_direction == predicted_direction:
            correct += 1
        total += 1

    return round(correct / total, 4) if total > 0 else 0.0


def evaluate_model_performance() -> Dict[str, Any]:
    """
    Kiểm chứng dự báo: Lấy các forecast chưa kiểm chứng,
    so sánh với giá thực tế, đánh dấu đã kiểm chứng.
    """
    unverified = get_unverified_forecasts()
    if not unverified:
        logger.info("Không có forecast nào cần kiểm chứng.")
        return {"message": "Không có forecast nào cần kiểm chứng."}

    logger.info("Tìm thấy %d forecast để kiểm chứng.", len(unverified))

    all_actuals, all_preds = [], []
    verified_ids = []

    for forecast in unverified:
        product_url = forecast["product_url"]
        source = forecast["source"]
        predict_date = forecast["predict_date"].date()

        history = get_product_price_history(product_url, source)
        actual_price = None
        for entry in history:
            if entry["scraped_at"].date() >= predict_date:
                actual_price = entry.get("price_value")
                if actual_price and actual_price > 0:
                    break

        if actual_price:
            all_actuals.append(actual_price)
            all_preds.append(forecast["forecast_price"])
            verified_ids.append(forecast["_id"])
        else:
            logger.debug("Không tìm thấy giá thực tế cho forecast %s - %s", source, product_url)

    if verified_ids:
        mark_forecasts_as_verified(verified_ids)
        logger.info("Đã đánh dấu %d forecasts là đã kiểm chứng.", len(verified_ids))

    if not all_actuals:
        return {"message": "Không tìm thấy giá thực tế cho các forecast."}

    y_true = np.array(all_actuals)
    y_pred = np.array(all_preds)

    return {
        "evaluation_count": len(y_true),
        "mae": calculate_mae(y_true, y_pred),
        "rmse": calculate_rmse(y_true, y_pred),
        "mape": calculate_mape(y_true, y_pred),
        "direction_accuracy": calculate_direction_accuracy(all_actuals, all_preds),
        "evaluated_at": datetime.utcnow().isoformat(),
    }