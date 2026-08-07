# -*- coding: utf-8 -*-
"""
train_lstm_gpu.py - Huấn luyện LSTM dự báo giá bằng PyTorch trên GPU.

Vì TensorFlow >= 2.11 không hỗ trợ GPU trên Windows native,
script này dùng PyTorch (bản +cu128) để tận dụng GPU NVIDIA RTX 3050.

Cung cấp:
- build_lstm_model(seq_length)          : Xây dựng mô hình LSTM (PyTorch)
- create_sequences(data, seq_length)    : Tạo chuỗi (X, y)
- get_or_train_model(...)               : Tái sử dụng model đã lưu hoặc huấn luyện mới
- save_model(...) / load_model(...)     : Lưu / tải model + scaler + metadata

Model được lưu vào thư mục saved_models/lstm_gpu/ theo từng sản phẩm.
"""
import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

# Thư mục lưu model đã huấn luyện
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_models", "lstm_gpu")
os.makedirs(MODEL_DIR, exist_ok=True)

DEFAULT_EPOCHS = 50
DEFAULT_BATCH_SIZE = 4

# Kiểm tra GPU
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class LSTMPredictor(nn.Module):
    """Mô hình LSTM dự báo giá (tương đương kiến trúc TensorFlow)."""

    def __init__(self, seq_length: int = 3):
        super().__init__()
        self.lstm1 = nn.LSTM(input_size=1, hidden_size=64, batch_first=True)
        self.dropout1 = nn.Dropout(0.2)
        self.lstm2 = nn.LSTM(input_size=64, hidden_size=32, batch_first=True)
        self.dropout2 = nn.Dropout(0.2)
        self.fc1 = nn.Linear(32, 16)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(16, 1)

    def forward(self, x):
        out, _ = self.lstm1(x)
        out = self.dropout1(out)
        out, _ = self.lstm2(out)
        out = self.dropout2(out)
        # Lấy output cuối cùng của chuỗi
        out = out[:, -1, :]
        out = self.relu(self.fc1(out))
        out = self.fc2(out)
        return out


def build_lstm_model(seq_length: int = 3) -> LSTMPredictor:
    """Xây dựng mô hình LSTM (PyTorch)."""
    model = LSTMPredictor(seq_length).to(DEVICE)
    return model


def create_sequences(data, seq_length: int):
    """Tạo chuỗi (X, y) cho LSTM từ dữ liệu đã chuẩn hóa."""
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i : i + seq_length])
        y.append(data[i + seq_length])
    return X, y


def _model_key(product_url: str, source: str, seq_length: int) -> str:
    """Tạo khóa ổn định cho model của 1 sản phẩm."""
    raw = f"{source}|{product_url}|seq{seq_length}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _model_path(product_url: str, source: str, seq_length: int) -> str:
    return os.path.join(MODEL_DIR, f"{_model_key(product_url, source, seq_length)}.pt")


def _meta_path(product_url: str, source: str, seq_length: int) -> str:
    return os.path.join(MODEL_DIR, f"{_model_key(product_url, source, seq_length)}.json")


def _restore_scaler(scaler_data: Optional[Dict[str, Any]]):
    """Khôi phục MinMaxScaler từ metadata đã lưu."""
    if not scaler_data:
        return None
    try:
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        scaler.min_ = np.array(scaler_data["min_"], dtype=float)
        scaler.scale_ = np.array(scaler_data["scale_"], dtype=float)
        scaler.data_min_ = np.array(scaler_data["data_min_"], dtype=float)
        scaler.data_max_ = np.array(scaler_data["data_max_"], dtype=float)
        scaler.n_features_in_ = int(scaler_data.get("n_features_in_", 1))
        scaler.n_samples_seen_ = int(scaler_data.get("n_samples_seen_", 1))
        return scaler
    except Exception as e:
        logger.warning("Không khôi phục được scaler: %s", e)
        return None


def save_model(
    model,
    scaler,
    data_hash: str,
    product_url: str,
    source: str,
    seq_length: int,
    epochs: int,
    history_count: int,
) -> str:
    """Lưu model + scaler + metadata xuống đĩa."""
    path = _model_path(product_url, source, seq_length)
    torch.save(model.state_dict(), path)
    meta = {
        "product_url": product_url,
        "source": source,
        "seq_length": seq_length,
        "epochs": epochs,
        "history_count": history_count,
        "data_hash": data_hash,
        "saved_at": datetime.utcnow().isoformat(),
        "device": str(DEVICE),
        "scaler": {
            "min_": scaler.min_.tolist(),
            "scale_": scaler.scale_.tolist(),
            "data_min_": scaler.data_min_.tolist(),
            "data_max_": scaler.data_max_.tolist(),
            "n_features_in_": int(scaler.n_features_in_),
            "n_samples_seen_": int(scaler.n_samples_seen_),
        },
    }
    with open(_meta_path(product_url, source, seq_length), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info("Đã lưu model LSTM GPU (%d epochs) cho %s - %s", epochs, source, product_url[:50])
    return path


def load_model(product_url: str, source: str, seq_length: int) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """Tải model + metadata đã lưu. Trả về (model, meta) hoặc None."""
    path = _model_path(product_url, source, seq_length)
    meta_path = _meta_path(product_url, source, seq_length)
    if not os.path.exists(path) or not os.path.exists(meta_path):
        return None
    try:
        model = build_lstm_model(seq_length)
        model.load_state_dict(torch.load(path, map_location=DEVICE))
        model.eval()
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return model, meta
    except Exception as e:
        logger.warning("Không tải được model đã lưu %s - %s: %s", source, product_url[:50], e)
        return None


def get_or_train_model(
    prices_raw: np.ndarray,
    product_url: str,
    source: str,
    seq_length: int = 3,
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force_retrain: bool = False,
) -> Tuple[Optional[Any], Optional[Any], int]:
    """
    Tái sử dụng model đã lưu nếu dữ liệu không đổi, ngược lại huấn luyện mới.

    Returns:
        (model, scaler, epochs_đã_huấn_luyện) hoặc (None, None, 0) nếu không đủ dữ liệu.
    """
    from sklearn.preprocessing import MinMaxScaler

    scaler = MinMaxScaler()
    prices_norm = scaler.fit_transform(prices_raw).flatten()
    data_hash = hashlib.sha256(prices_norm.tobytes()).hexdigest()

    if not force_retrain:
        loaded = load_model(product_url, source, seq_length)
        if loaded is not None:
            model, meta = loaded
            if meta.get("data_hash") == data_hash:
                saved_scaler = _restore_scaler(meta.get("scaler"))
                if saved_scaler is not None:
                    trained_epochs = int(meta.get("epochs", 0))
                    logger.info(
                        "Tái sử dụng model GPU đã lưu (%d epochs) cho %s - %s",
                        trained_epochs, source, product_url[:50],
                    )
                    return model, saved_scaler, trained_epochs
            logger.info(
                "Dữ liệu đã thay đổi, huấn luyện lại từ đầu cho %s - %s",
                source, product_url[:50],
            )

    X, y = create_sequences(prices_norm, seq_length)
    if not X:
        return None, None, 0

    X = np.array(X).reshape((len(X), seq_length, 1)).astype(np.float32)
    y = np.array(y).reshape(-1, 1).astype(np.float32)

    model = build_lstm_model(seq_length)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    criterion = nn.MSELoss()

    X_tensor = torch.from_numpy(X).to(DEVICE)
    y_tensor = torch.from_numpy(y).to(DEVICE)

    model.train()
    n_samples = len(X_tensor)
    for epoch in range(epochs):
        # Shuffle và chia batch
        perm = torch.randperm(n_samples)
        total_loss = 0.0
        n_batches = 0
        for i in range(0, n_samples, batch_size):
            idx = perm[i : i + batch_size]
            xb = X_tensor[idx]
            yb = y_tensor[idx]

            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            n_batches += 1
        if (epoch + 1) % 10 == 0:
            logger.info("  Epoch %d/%d - loss: %.6f", epoch + 1, epochs, total_loss / n_batches)

    model.eval()
    save_model(model, scaler, data_hash, product_url, source, seq_length, epochs, len(prices_raw))
    return model, scaler, epochs