# -*- coding: utf-8 -*-
"""
Mô-đun dự báo giá bằng LSTM.
"""
import os
import logging
import numpy as np
from typing import List, Optional, Tuple, Any, Dict

logger = logging.getLogger(__name__)

# Đường dẫn model mặc định (nếu dùng model tổng)
DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "saved_models",
    "lstm",
)


def build_lstm_model(seq_length: int = 3):
    """
    Xây dựng mô hình Stacked LSTM theo đề cương:
    - 2 lớp ẩn (64, 32 units)
    - Dropout (0.2) chống quá khớp
    - Optimizer Adam, loss MSE
    """
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Input, Dropout
    from tensorflow.keras.optimizers import Adam

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


def create_sequences(data, seq_length: int):
    """Tạo chuỗi (X, y) cho LSTM từ dữ liệu đã chuẩn hóa."""
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i : i + seq_length])
        y.append(data[i + seq_length])
    return X, y


def get_model():
    """Tải model đã huấn luyện trước (fallback)."""
    from tensorflow.keras.models import load_model

    if not os.path.exists(DEFAULT_MODEL_PATH):
        raise FileNotFoundError(f"Model không tồn tại tại {DEFAULT_MODEL_PATH}")
    logger.info("Đang tải model LSTM từ %s", DEFAULT_MODEL_PATH)
    return load_model(DEFAULT_MODEL_PATH)


def forecast_future_prices(
    model,
    prices_norm: np.ndarray,
    scaler,
    seq_length: int = 3,
    predict_days: int = 7,
) -> List[float]:
    """
    Dự báo giá tương lai bằng mô hình LSTM đã huấn luyện.
    Dùng cửa sổ trượt để dự báo nhiều ngày liên tiếp.
    """
    last_sequence = prices_norm[-seq_length:].copy()
    predictions_norm = []

    for _ in range(predict_days):
        input_seq = last_sequence.reshape((1, seq_length, 1))
        pred_norm = model.predict(input_seq, verbose=0)[0][0]
        predictions_norm.append(pred_norm)
        last_sequence = np.append(last_sequence[1:], pred_norm)

    predictions_raw = scaler.inverse_transform(
        np.array(predictions_norm).reshape(-1, 1)
    ).flatten()
    return [round(float(p), 0) for p in predictions_raw]


def train_and_forecast(
    prices: List[float],
    seq_length: int = 3,
    predict_days: int = 7,
    epochs: int = 50,
) -> Optional[Dict[str, Any]]:
    """
    Huấn luyện LSTM nhanh và dự báo giá.

    Returns:
        Dict {"forecasts": [...], "metrics": {...}} hoặc None nếu thiếu dữ liệu
    """
    from sklearn.preprocessing import MinMaxScaler

    if len(prices) < seq_length + 1:
        return None

    prices_raw = np.array(prices).reshape(-1, 1)
    scaler = MinMaxScaler()
    prices_norm = scaler.fit_transform(prices_raw).flatten()

    X, y = create_sequences(prices_norm, seq_length)
    if not X:
        return None

    X = np.array(X).reshape((len(X), seq_length, 1))
    y = np.array(y)

    model = build_lstm_model(seq_length)
    model.fit(X, y, epochs=epochs, batch_size=4, verbose=0)

    forecasts = forecast_future_prices(model, prices_norm, scaler, seq_length, predict_days)

    # Đánh giá trên tập train
    y_pred_norm = model.predict(X, verbose=0)
    y_pred_raw = scaler.inverse_transform(y_pred_norm)
    y_true_raw = prices_raw[seq_length:]
    mae = float(np.mean(np.abs(y_true_raw - y_pred_raw)))
    rmse = float(np.sqrt(np.mean((y_true_raw - y_pred_raw) ** 2)))
    mask = y_true_raw != 0
    mape = float(np.mean(np.abs((y_true_raw[mask] - y_pred_raw[mask]) / y_true_raw[mask])) * 100) if np.any(mask) else 0.0

    return {
        "forecasts": forecasts,
        "metrics": {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "mape": round(mape, 2),
        },
    }