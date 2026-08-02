# ai/train_lstm.py
import os
import logging
import numpy as np
from typing import Tuple, Dict, Any

# Suppress TensorFlow logs
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
tf.get_logger().setLevel("ERROR")

from tensorflow.keras.models import Sequential, save_model
from tensorflow.keras.layers import LSTM, Dense, Input, Dropout
from tensorflow.keras.optimizers import Adam

from ai.preprocess import create_sequences
from ai.evaluate import calculate_mae, calculate_rmse, calculate_mape

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "lstm_price.keras")

def build_lstm_model(seq_length: int) -> Sequential:
    """Builds the LSTM model architecture."""
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

def train_and_save_model(
    prices_norm: np.ndarray,
    prices_raw: np.ndarray,
    scaler,
    seq_length: int = 3
) -> Dict[str, Any]:
    """Trains the LSTM model, saves it, and returns training metrics."""
    X, y = create_sequences(prices_norm, seq_length)
    if len(X) == 0:
        raise ValueError("Not enough data to create sequences for training.")

    X = X.reshape((X.shape[0], seq_length, 1))

    model = build_lstm_model(seq_length)
    model.fit(X, y, epochs=50, batch_size=4, verbose=0)

    # Save the trained model
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    save_model(model, MODEL_PATH)
    logger.info(f"Model trained and saved to {MODEL_PATH}")

    # Calculate and return training metrics
    y_pred_train_norm = model.predict(X, verbose=0)
    y_pred_train_raw = scaler.inverse_transform(y_pred_train_norm)
    y_true_raw = prices_raw[seq_length:]

    return {
        "mae": calculate_mae(y_true_raw, y_pred_train_raw),
        "rmse": calculate_rmse(y_true_raw, y_pred_train_raw),
        "mape": calculate_mape(y_true_raw, y_pred_train_raw),
    }