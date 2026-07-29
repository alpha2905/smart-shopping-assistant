"""
LSTM Price Prediction Module.

Train LSTM on price history to predict future prices.
Predictions are cached in MongoDB for instant API response.

Strategy for speed:
  1. Pre-train in background (hourly scheduler) → cache in DB
  2. API serves from cache → instant response
  3. If no cache → train quick model on-the-fly
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
from tensorflow.keras.layers import LSTM, Dense, Input
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import MinMaxScaler


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


def build_lstm_model(seq_length: int) -> Sequential:
    """Build a lightweight LSTM model for price prediction."""
    model = Sequential([
        Input(shape=(seq_length, 1)),
        LSTM(32, return_sequences=False),
        Dense(16, activation="relu"),
        Dense(1),
    ])
    model.compile(optimizer=Adam(learning_rate=0.01), loss="mse")
    return model


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
        }
        or None if not enough data.
    """
    prices_norm, scaler = prepare_time_series(price_history)
    if len(prices_norm) < 3:
        logger.warning("Not enough price data for LSTM (need ≥3, got %d)", len(prices_norm))
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

    # Try LSTM training
    try:
        model = build_lstm_model(seq_length)
        model.fit(X, y, epochs=50, batch_size=4, verbose=0)

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

        logger.info("LSTM prediction successful: %d history + %d predicted", len(history_output), len(prediction_output))
        return {
            "history": history_output,
            "predictions": prediction_output,
            "model_type": "lstm",
        }

    except Exception as e:
        logger.error("LSTM training failed: %s, falling back to linear regression", e)
        return _linear_fallback(prices_raw, dates, predict_days)


def _linear_fallback(
    prices: List[float],
    dates: List[datetime],
    predict_days: int,
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

    return {
        "history": history_output,
        "predictions": prediction_output,
        "model_type": "linear",
    }