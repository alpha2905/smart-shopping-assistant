"""
LSTM Price Prediction Module.

Train LSTM on price history to predict future prices.
Predictions are cached in MongoDB for instant API response.

Features:
- LSTM & Linear Regression prediction
- MAE, RMSE, MAPE error metrics
- Direction Accuracy (tăng/giảm/ổn định)
- Forecast Verification (so sánh dự báo vs thực tế)
- Price trend classification
"""

import re
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Suppress TensorFlow verbose logs
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
tf.get_logger().setLevel("ERROR")

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Input, Dropout
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler


# ========== PRICE THRESHOLDS ==========

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


# ========== PRICE PARSING ==========

def parse_price_string(price_str: str) -> Optional[float]:
    """
    Convert price string like '20.000.000 đ' or '20,000,000đ' → 20000000.0
    Returns None if cannot parse.
    """
    if not price_str or not isinstance(price_str, str):
        return None

    # Remove 'đ', 'vnd', spaces
    cleaned = re.sub(r"[đđvndVND\s]", "", price_str)
    # Remove dots/commas used as thousand separators
    cleaned = cleaned.replace(".", "").replace(",", "")
    # Extract digits
    match = re.search(r"[\d]+", cleaned)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


# ========== METRICS ==========

def calculate_mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(y_true - y_pred)))


def calculate_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def calculate_mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Mean Absolute Percentage Error (%).
    Tránh division by zero.
    """
    mask = y_true != 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def calculate_direction_accuracy(
    actual_prices: List[float],
    predicted_prices: List[float],
) -> Dict[str, Any]:
    """
    Tính Direction Accuracy: tỷ lệ dự báo đúng hướng (tăng/giảm/ổn định).
    
    Returns:
        {
            "accuracy": 0.84,          # Tỷ lệ đúng (0-1)
            "correct": 84,
            "total": 100,
            "by_direction": {
                "rise": {"correct": 40, "total": 45},
                "drop": {"correct": 35, "total": 40},
                "stable": {"correct": 9, "total": 15},
            }
        }
    """
    if len(actual_prices) < 2 or len(predicted_prices) < 2:
        return {"accuracy": 0, "correct": 0, "total": 0, "by_direction": {}}

    correct = 0
    total = 0
    by_direction = {}

    for i in range(1, min(len(actual_prices), len(predicted_prices))):
        actual_change = actual_prices[i] - actual_prices[i - 1]
        predicted_change = predicted_prices[i] - predicted_prices[i - 1]

        actual_direction = "stable" if abs(actual_change) < 0.01 * actual_prices[i - 1] else ("rise" if actual_change > 0 else "drop")
        predicted_direction = "stable" if abs(predicted_change) < 0.01 * predicted_prices[i - 1] else ("rise" if predicted_change > 0 else "drop")

        if actual_direction not in by_direction:
            by_direction[actual_direction] = {"correct": 0, "total": 0}
        by_direction[actual_direction]["total"] += 1

        if actual_direction == predicted_direction:
            correct += 1
            by_direction[actual_direction]["correct"] += 1

        total += 1

    return {
        "accuracy": round(correct / total, 4) if total > 0 else 0,
        "correct": correct,
        "total": total,
        "by_direction": by_direction,
    }


# ========== TIME SERIES PREPARATION ==========

def prepare_time_series(
    price_history: List[Dict[str, Any]],
) -> Tuple[np.ndarray, MinMaxScaler]:
    """
    Convert price_history list → normalized numpy array.
    Returns (prices_normalized, scaler).
    """
    prices = []
    for entry in price_history:
        price = parse_price_string(entry.get("price", ""))
        if price is not None and price > 0:
            prices.append(price)

    if len(prices) < 3:
        return np.array([]), None

    prices_array = np.array(prices).reshape(-1, 1).astype(np.float32)
    scaler = MinMaxScaler(feature_range=(0, 1))
    prices_normalized = scaler.fit_transform(prices_array).flatten()
    return prices_normalized, scaler


def create_sequences(data: np.ndarray, seq_length: int = 3) -> Tuple[np.ndarray, np.ndarray]:
    """
    Create sliding window sequences for LSTM.
    X[i] = data[i:i+seq_length], y[i] = data[i+seq_length]
    """
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i : i + seq_length])
        y.append(data[i + seq_length])
    return np.array(X), np.array(y)


# ========== MODEL BUILDING ==========

def build_lstm_model(seq_length: int) -> Sequential:
    """Build an improved LSTM model for price prediction."""
    model = Sequential([
        Input(shape=(seq_length, 1)),
        LSTM(64, return_sequences=True),
        Dropout(0.2),
        LSTM(32, return_sequences=False),
        Dropout(0.2),
        Dense(16, activation="relu"),
        Dense(1),
    ])
    model.compile(optimizer=Adam(learning_rate=0.01), loss="mse")
    return model


# ========== FORECAST VERIFICATION ==========

def verify_forecast(
    product_url: str,
    source: str,
    predicted_price: float,
    actual_price: float,
    predicted_date: datetime,
) -> Dict[str, Any]:
    """
    Kiểm chứng dự báo: so sánh giá dự báo với giá thực tế.
    
    Args:
        product_url: URL sản phẩm
        source: Nguồn dữ liệu
        predicted_price: Giá đã dự báo
        actual_price: Giá thực tế
        predicted_date: Ngày dự báo
        
    Returns:
        Dict với kết quả kiểm chứng
    """
    if actual_price <= 0 or predicted_price <= 0:
        return {"verified": False, "error": "Invalid price values"}

    error = abs(predicted_price - actual_price)
    mape = (error / actual_price) * 100 if actual_price > 0 else 0

    return {
        "verified": True,
        "product_url": product_url,
        "source": source,
        "predicted_date": predicted_date.isoformat(),
        "predicted_price": round(predicted_price, 0),
        "actual_price": round(actual_price, 0),
        "error": round(error, 0),
        "mape": round(mape, 2),
        "is_accurate": mape < 10,  # Dự báo đúng nếu sai số < 10%
    }


# ========== TRAINING & PREDICTION ==========

def train_and_predict(
    price_history: List[Dict[str, Any]],
    predict_days: int = 7,
) -> Optional[Dict[str, Any]]:
    """
    Train LSTM on price history and predict future prices.

    Args:
        price_history: List of {price, scraped_at} dicts
        predict_days: Number of future data points to predict

    Returns:
        {
            "history": [{price, date}, ...],
            "predictions": [{price, date}, ...],
            "model_type": "lstm" | "linear",
            "metrics": {
                "mae": ...,
                "rmse": ...,
                "mape": ...,
                "direction_accuracy": {...},
            },
            "price_analysis": {
                "min_price": ...,
                "max_price": ...,
                "avg_price": ...,
                "current_price": ...,
                "current_vs_avg": "below" | "above" | "equal",
                "change_pct": ...,
                "change_label": ...,
                "trend": "uptrend" | "downtrend" | "stable",
            },
        }
        or None if not enough data.
    """
    prices_norm, scaler = prepare_time_series(price_history)
    if len(prices_norm) < 3:
        logger.warning("Not enough price data for LSTM (need >=3, got %d)", len(prices_norm))
        return None

    seq_length = min(3, len(prices_norm) - 1)
    X, y = create_sequences(prices_norm, seq_length)

    if len(X) == 0:
        return None

    # Reshape for LSTM: (samples, timesteps, features)
    X = X.reshape((X.shape[0], seq_length, 1))

    # Parse dates from price_history
    dates = []
    prices_raw = []
    for entry in price_history:
        price = parse_price_string(entry.get("price", ""))
        if price is not None and price > 0:
            prices_raw.append(price)
            scraped_at = entry.get("scraped_at")
            if isinstance(scraped_at, datetime):
                dates.append(scraped_at)
            elif isinstance(scraped_at, str):
                try:
                    dates.append(datetime.fromisoformat(scraped_at.replace("Z", "+00:00")))
                except Exception:
                    dates.append(datetime.utcnow())
            else:
                dates.append(datetime.utcnow())

    # Build history output
    history_output = [
        {"price": prices_raw[i], "date": dates[i].isoformat()}
        for i in range(len(prices_raw))
    ]

    # === Price Analysis ===
    current_price = prices_raw[-1] if prices_raw else 0
    avg_price = float(np.mean(prices_raw)) if prices_raw else 0
    min_price = float(np.min(prices_raw)) if prices_raw else 0
    max_price = float(np.max(prices_raw)) if prices_raw else 0

    if avg_price > 0:
        current_vs_avg_pct = (current_price - avg_price) / avg_price
        if current_vs_avg_pct < -0.02:
            current_vs_avg = "below"
        elif current_vs_avg_pct > 0.02:
            current_vs_avg = "above"
        else:
            current_vs_avg = "equal"
    else:
        current_vs_avg = "equal"

    # Price trend from history
    if len(prices_raw) >= 2:
        total_change = (prices_raw[-1] - prices_raw[0]) / prices_raw[0]
        change_label = classify_price_change(total_change)
        if total_change > 0.02:
            trend = "uptrend"
        elif total_change < -0.02:
            trend = "downtrend"
        else:
            trend = "stable"
    else:
        total_change = 0
        change_label = "stable"
        trend = "stable"

    price_analysis = {
        "min_price": round(min_price, 0),
        "max_price": round(max_price, 0),
        "avg_price": round(avg_price, 0),
        "current_price": round(current_price, 0),
        "current_vs_avg": current_vs_avg,
        "change_pct": round(total_change * 100, 2),
        "change_label": get_change_label(change_label),
        "trend": trend,
    }

    # Try LSTM training
    try:
        model = build_lstm_model(seq_length)
        model.fit(X, y, epochs=50, batch_size=4, verbose=0)

        # === Calculate training metrics ===
        y_pred_train = model.predict(X, verbose=0).flatten()
        y_true_train = y

        # Denormalize for metrics
        y_true_denorm = scaler.inverse_transform(y_true_train.reshape(-1, 1)).flatten()
        y_pred_denorm = scaler.inverse_transform(y_pred_train.reshape(-1, 1)).flatten()

        mae = calculate_mae(y_true_denorm, y_pred_denorm)
        rmse = calculate_rmse(y_true_denorm, y_pred_denorm)
        mape = calculate_mape(y_true_denorm, y_pred_denorm)
        direction_acc = calculate_direction_accuracy(
            y_true_denorm.tolist(), y_pred_denorm.tolist()
        )

        metrics = {
            "mae": round(mae, 0),
            "rmse": round(rmse, 0),
            "mape": round(mape, 2),
            "direction_accuracy": direction_acc,
        }

        # Predict future
        predictions_norm = []
        last_sequence = prices_norm[-seq_length:].copy()

        for _ in range(predict_days):
            input_seq = last_sequence[-seq_length:].reshape((1, seq_length, 1))
            pred_norm = model.predict(input_seq, verbose=0)[0][0]
            predictions_norm.append(pred_norm)
            last_sequence = np.append(last_sequence, pred_norm)

        # Denormalize predictions
        predictions = scaler.inverse_transform(
            np.array(predictions_norm).reshape(-1, 1)
        ).flatten()

        # Generate future dates (1 day interval)
        last_date = dates[-1] if dates else datetime.utcnow()
        prediction_output = []
        for i, pred in enumerate(predictions):
            future_date = last_date + timedelta(days=i + 1)
            prediction_output.append({
                "price": round(float(pred), 0),
                "date": future_date.isoformat(),
            })

        # === Future trend analysis ===
        if predictions_norm:
            future_change = (predictions[-1] - current_price) / current_price if current_price > 0 else 0
            future_label = classify_price_change(future_change)
            price_analysis["forecast_change_pct"] = round(future_change * 100, 2)
            price_analysis["forecast_label"] = get_change_label(future_label)

        logger.info(
            "LSTM prediction: %d history -> %d predicted (MAE=%.0f, RMSE=%.0f, MAPE=%.1f%%, DirAcc=%.1f%%)",
            len(history_output), len(prediction_output), mae, rmse, mape,
            direction_acc.get("accuracy", 0) * 100,
        )
        return {
            "history": history_output,
            "predictions": prediction_output,
            "model_type": "lstm",
            "metrics": metrics,
            "price_analysis": price_analysis,
        }

    except Exception as e:
        logger.error("LSTM training failed: %s, falling back to linear regression", e)
        return _linear_fallback(prices_raw, dates, predict_days, price_analysis)


def _linear_fallback(
    prices: List[float],
    dates: List[datetime],
    predict_days: int,
    price_analysis: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Simple linear regression fallback when LSTM fails."""
    if len(prices) < 2:
        return None

    # Simple linear regression: y = a*x + b
    x = np.arange(len(prices)).reshape(-1, 1).astype(np.float32)
    y = np.array(prices).astype(np.float32)

    from sklearn.linear_model import LinearRegression
    reg = LinearRegression()
    reg.fit(x, y)

    # Calculate training metrics
    y_pred_train = reg.predict(x)
    mae = calculate_mae(y, y_pred_train)
    rmse = calculate_rmse(y, y_pred_train)
    mape = calculate_mape(y, y_pred_train)
    direction_acc = calculate_direction_accuracy(y.tolist(), y_pred_train.tolist())

    metrics = {
        "mae": round(mae, 0),
        "rmse": round(rmse, 0),
        "mape": round(mape, 2),
        "direction_accuracy": direction_acc,
    }

    # Predict future
    future_x = np.arange(len(prices), len(prices) + predict_days).reshape(-1, 1)
    future_prices = reg.predict(future_x)

    history_output = [
        {"price": prices[i], "date": dates[i].isoformat()}
        for i in range(len(prices))
    ]

    last_date = dates[-1] if dates else datetime.utcnow()
    prediction_output = []
    for i, pred in enumerate(future_prices):
        future_date = last_date + timedelta(days=i + 1)
        prediction_output.append({
            "price": round(float(pred), 0),
            "date": future_date.isoformat(),
        })

    # Future trend
    if price_analysis and future_prices is not None:
        current_price = prices[-1] if prices else 0
        if current_price > 0 and len(future_prices) > 0:
            future_change = (future_prices[-1] - current_price) / current_price
            future_label = classify_price_change(future_change)
            price_analysis["forecast_change_pct"] = round(future_change * 100, 2)
            price_analysis["forecast_label"] = get_change_label(future_label)

    result = {
        "history": history_output,
        "predictions": prediction_output,
        "model_type": "linear",
        "metrics": metrics,
    }
    if price_analysis:
        result["price_analysis"] = price_analysis

    return result