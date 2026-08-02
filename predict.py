# ai/predict.py
import os
import logging
import numpy as np
from typing import List

# Suppress TensorFlow logs
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
import tensorflow as tf
tf.get_logger().setLevel("ERROR")

from tensorflow.keras.models import load_model

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model", "lstm_price.keras")

def get_model():
    """Loads the pre-trained Keras model."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model file not found at {MODEL_PATH}. Please train the model first.")
    logger.info(f"Loading model from {MODEL_PATH}")
    return load_model(MODEL_PATH)

def forecast_future_prices(
    model,
    prices_norm: np.ndarray,
    scaler,
    seq_length: int = 3,
    predict_days: int = 7
) -> List[float]:
    """Uses the trained model to forecast future prices."""
    last_sequence = prices_norm[-seq_length:].copy()
    predictions_norm = []

    for _ in range(predict_days):
        input_seq = last_sequence.reshape((1, seq_length, 1))
        pred_norm = model.predict(input_seq, verbose=0)[0][0]
        predictions_norm.append(pred_norm)
        last_sequence = np.append(last_sequence[1:], pred_norm)

    # Denormalize predictions
    predictions_raw = scaler.inverse_transform(np.array(predictions_norm).reshape(-1, 1)).flatten()
    return [round(float(p), 0) for p in predictions_raw]