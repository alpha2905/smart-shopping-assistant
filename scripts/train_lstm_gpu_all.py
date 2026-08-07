# -*- coding: utf-8 -*-
"""
train_lstm_gpu_all.py - Huấn luyện và đánh giá LSTM (PyTorch GPU) trên toàn bộ sản phẩm.

Sử dụng GPU NVIDIA (CUDA) thông qua PyTorch để huấn luyện nhanh hơn.

Các chỉ số đánh giá (tính trên TẬP TEST hold-out, không phải tập train):
- MAE  (Mean Absolute Error)          - Sai số tuyệt đối trung bình
- RMSE (Root Mean Squared Error)      - Sai số toàn phương trung bình
- MAPE (Mean Absolute Percentage Error) - Sai số phần trăm tuyệt đối trung bình
- Direction Accuracy                  - Tỷ lệ dự báo đúng hướng tăng/giảm/ổn định

Phân loại mức tăng/giảm giá (utils.price_predictor):
- Giảm mạnh  >= 5%
- Giảm nhẹ   1% - 5%
- Ổn định    ±1%
- Tăng nhẹ   1% - 5%
- Tăng mạnh  >= 5%

Cách chạy:
    python scripts/train_lstm_gpu_all.py
    python scripts/train_lstm_gpu_all.py --min-history 5 --epochs 50
    python scripts/train_lstm_gpu_all.py --limit 20   # chỉ đánh giá 20 sản phẩm đầu
"""
import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json

# Thêm thư mục gốc vào sys.path để import được utils
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fix Windows console encoding cho tiếng Việt
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np
import torch

from utils.db import init_db, close_db, parse_price, get_collection
from utils.price_predictor import classify_price_change, get_change_label
from train_lstm_gpu import get_or_train_model, create_sequences, DEVICE
from ai.evaluate import calculate_mae, calculate_rmse, calculate_mape

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SEQ_LENGTH = 3
PREDICT_DAYS = 7
TEST_SPLIT_RATIO = 0.2


def calculate_direction_accuracy(actual_prices: List[float], predicted_prices: List[float]) -> float:
    """
    Tính tỷ lệ dự báo đúng hướng (tăng/giảm/ổn định).
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


def train_lstm_for_product(
    price_history: List[Dict[str, Any]],
    product_url: str,
    source: str,
    predict_days: int = PREDICT_DAYS,
    seq_length: int = SEQ_LENGTH,
    epochs: int = 50,
    batch_size: int = 4,
    force_retrain: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Huấn luyện LSTM (GPU) cho 1 sản phẩm, đánh giá trên tập test hold-out
    và trả về dự báo tương lai.

    - Tách chuỗi giá thành train (80%) / test (20%).
    - Huấn luyện model CHỈ trên tập train.
    - Tính MAE/RMSE/MAPE/Direction Accuracy trên tập test (dữ liệu chưa từng thấy).
    - Dự báo tương lai dựa trên toàn bộ dữ liệu.

    Trả về None nếu không đủ dữ liệu.
    """
    # Lấy chuỗi giá hợp lệ (> 0), GỘP các snapshot liên tiếp cùng giá.
    # utils/db.py push snapshot giá kể cả khi không đổi → nếu không gộp, chuỗi
    # bất biến khiến MinMaxScaler suy biến (mọi giá -> 0), LSTM dự đoán đúng
    # hằng số đó → MAE/RMSE/MAPE ra 0.00 GIẢ TẠO.
    prices = []
    last_p = None
    for h in price_history:
        p = h.get("price_value", parse_price(h.get("price", "")))
        if p and p > 0:
            p = float(p)
            if p != last_p:
                prices.append(p)
                last_p = p

    # Giá không hề đổi trong toàn bộ lịch sử → không có gì để học → bỏ qua.
    if len(prices) < 2 or len(set(prices)) < 2:
        logger.debug("[%s] Giá không đổi/không đủ biến động, bỏ qua (tránh MAE=0 giả tạo)", source)
        return None

    # Cần đủ dữ liệu để tách train/test: mỗi tập cần ít nhất seq_length + 1 điểm
    MIN_TRAIN_SIZE = seq_length + 1
    MIN_TEST_SIZE = seq_length + 1
    if len(prices) < MIN_TRAIN_SIZE + MIN_TEST_SIZE:
        logger.debug(
            "[%s] Không đủ dữ liệu để tách train/test (có %d, cần %d)",
            source, len(prices), MIN_TRAIN_SIZE + MIN_TEST_SIZE
        )
        return None

    # --- 1. Tách dữ liệu Train-Test (hold-out) ---
    split_index = int(len(prices) * (1 - TEST_SPLIT_RATIO))
    # Đảm bảo tập test có đủ dữ liệu
    if len(prices) - split_index < MIN_TEST_SIZE:
        split_index = len(prices) - MIN_TEST_SIZE
    # Đảm bảo tập train có đủ dữ liệu
    if split_index < MIN_TRAIN_SIZE:
        logger.debug(
            "[%s] Không đủ dữ liệu train sau khi tách (có %d, cần %d)",
            source, split_index, MIN_TRAIN_SIZE
        )
        return None

    train_prices = prices[:split_index]
    test_prices = prices[split_index:]

    train_prices_raw = np.array(train_prices).reshape(-1, 1)
    test_prices_raw = np.array(test_prices).reshape(-1, 1)

    # --- 2. Huấn luyện model CHỈ trên tập train ---
    # get_or_train_model fit scaler trên dữ liệu train và cache model theo data_hash của train
    model, scaler, trained_epochs = get_or_train_model(
        train_prices_raw,
        product_url=product_url,
        source=source,
        seq_length=seq_length,
        epochs=epochs,
        batch_size=batch_size,
        force_retrain=force_retrain,
    )
    if model is None or scaler is None:
        return None

    # --- 3. Đánh giá model trên tập test (dữ liệu chưa từng thấy) ---
    # Chuẩn hóa toàn bộ dữ liệu bằng scaler đã fit trên tập train (tránh data leakage)
    full_prices_raw = np.array(prices).reshape(-1, 1)
    full_prices_norm = scaler.transform(full_prices_raw).flatten()

    # Lấy seq_length điểm cuối của tập train để tạo sequence đầu tiên cho tập test
    test_input_start_index = split_index - seq_length
    test_input_data = full_prices_norm[test_input_start_index:]

    X_test, y_test_norm = create_sequences(test_input_data, seq_length)
    if not X_test:
        return None

    X_test = np.array(X_test).reshape((len(X_test), seq_length, 1)).astype(np.float32)

    # Dự đoán trên tập test
    model.eval()
    with torch.no_grad():
        X_test_tensor = torch.from_numpy(X_test).to(DEVICE)
        y_pred_test_norm = model(X_test_tensor).cpu().numpy()

    # Chuyển về giá trị gốc để tính sai số
    y_pred_test_raw = scaler.inverse_transform(y_pred_test_norm)
    y_true_test_raw = test_prices_raw

    # Tính toán các chỉ số trên tập TEST
    mae = calculate_mae(y_true_test_raw, y_pred_test_raw)
    rmse = calculate_rmse(y_true_test_raw, y_pred_test_raw)
    mape = calculate_mape(y_true_test_raw, y_pred_test_raw)
    direction_accuracy = calculate_direction_accuracy(
        y_true_test_raw.flatten().tolist(),
        y_pred_test_raw.flatten().tolist(),
    )

    # --- 4. Dự báo tương lai (predict_days) dựa trên toàn bộ dữ liệu ---
    last_sequence = full_prices_norm[-seq_length:].copy()
    predictions_norm = []
    with torch.no_grad():
        for _ in range(predict_days):
            input_seq = torch.from_numpy(last_sequence.reshape(1, seq_length, 1).astype(np.float32)).to(DEVICE)
            pred_norm = model(input_seq).cpu().numpy()[0][0]
            predictions_norm.append(pred_norm)
            last_sequence = np.append(last_sequence[1:], pred_norm)

    predictions_raw = scaler.inverse_transform(np.array(predictions_norm).reshape(-1, 1)).flatten()

    # Phân loại xu hướng dự báo (so với giá hiện tại)
    current_price = prices[-1]
    forecast_price = round(float(predictions_raw[-1]), 0)
    change_pct = (forecast_price - current_price) / current_price if current_price > 0 else 0.0
    change_class = classify_price_change(change_pct)
    change_label = get_change_label(change_class)

    today = datetime.utcnow().date()
    forecasts = [
        {"date": today + timedelta(days=i + 1), "price": round(float(p), 0)}
        for i, p in enumerate(predictions_raw)
    ]

    return {
        "forecasts": forecasts,
        "metrics": {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "mape": round(mape, 2),
            "direction_accuracy": direction_accuracy,
            "history_count": len(prices),
            "train_size": len(train_prices),
            "test_size": len(test_prices),
            "current_price": round(current_price, 0),
            "forecast_price": forecast_price,
            "change_pct": round(change_pct * 100, 2),
            "change_class": change_class,
            "change_label": change_label,
            "trained_epochs": trained_epochs,
        },
    }


def get_products_with_history_from_products_collection(min_history: int = 3) -> List[Dict[str, Any]]:
    """Lấy các sản phẩm có lịch sử giá (>= min_history) từ collection 'products'."""
    col = get_collection()
    results = []
    for doc in col.find({
        "price_history": {"$exists": True},
        "$expr": {"$gte": [{"$size": "$price_history"}, min_history]}
    }):
        price_history = doc.get("price_history", [])
        results.append({
            "product_url": doc.get("product_url", ""),
            "source": doc.get("source", ""),
            "name": doc.get("name", ""),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("price_history_count", 0), reverse=True)
    return results


def get_price_history_from_products_collection(product_url: str, source: str) -> List[Dict[str, Any]]:
    """Lấy lịch sử giá của 1 sản phẩm từ collection 'products'."""
    col = get_collection()
    doc = col.find_one(
        {"product_url": product_url, "source": source},
        {"price_history": 1, "_id": 0},
    )
    if not doc or "price_history" not in doc:
        return []
    return sorted(doc["price_history"], key=lambda x: x["scraped_at"])


def evaluate_all_products(
    min_history: int = 3,
    predict_days: int = PREDICT_DAYS,
    epochs: int = 50,
    limit: Optional[int] = None,
    force_retrain: bool = False,
) -> Dict[str, Any]:
    """Huấn luyện và đánh giá LSTM GPU trên toàn bộ sản phẩm."""
    if not torch.cuda.is_available():
        logger.warning("⚠️ CUDA không khả dụng! Đang chạy trên CPU. Kiểm tra cài đặt PyTorch +cu128.")
    else:
        logger.info("✅ GPU: %s", torch.cuda.get_device_name(0))

    logger.info("Đang lấy danh sách sản phẩm có lịch sử giá (>= %d điểm) từ collection 'products'...", min_history)
    products = get_products_with_history_from_products_collection(min_history=min_history)
    logger.info("Tìm thấy %d sản phẩm có lịch sử giá.", len(products))

    if limit:
        products = products[:limit]
        logger.info("Giới hạn huấn luyện %d sản phẩm.", limit)

    results = []
    errors = 0
    skipped = 0

    for idx, prod in enumerate(products, 1):
        product_url = prod.get("product_url", "")
        source = prod.get("source", "")
        name = prod.get("name", "")

        try:
            price_history = get_price_history_from_products_collection(product_url, source)
            if not price_history:
                skipped += 1
                continue

            result = train_lstm_for_product(
                price_history,
                product_url=product_url,
                source=source,
                seq_length=SEQ_LENGTH,
                predict_days=predict_days,
                epochs=epochs,
                force_retrain=force_retrain,
            )
            if result is None:
                skipped += 1
                continue

            results.append({
                "product_url": product_url,
                "source": source,
                "name": name,
                **result["metrics"],
                "forecasts": result["forecasts"],
            })
            logger.info(
                "[%d/%d] %s - %s | MAE=%.2f RMSE=%.2f MAPE=%.2f%% | %s (%.2f%%)",
                idx, len(products), source, name[:40],
                result["metrics"]["mae"], result["metrics"]["rmse"],
                result["metrics"]["mape"],
                result["metrics"]["change_label"], result["metrics"]["change_pct"],
            )
        except Exception as e:
            errors += 1
            logger.error("Lỗi khi xử lý %s - %s: %s", source, product_url[:50], e)

    # Tổng hợp kết quả
    if not results:
        return {
            "total_products": len(products),
            "evaluated": 0,
            "skipped": skipped,
            "errors": errors,
            "message": "Không có sản phẩm nào đủ dữ liệu để đánh giá.",
        }

    mae_list = [r["mae"] for r in results]
    rmse_list = [r["rmse"] for r in results]
    mape_list = [r["mape"] for r in results]
    dir_acc_list = [r["direction_accuracy"] for r in results]

    # Phân bố xu hướng dự báo
    change_distribution = {}
    for r in results:
        label = r["change_label"]
        change_distribution[label] = change_distribution.get(label, 0) + 1

    return {
        "total_products": len(products),
        "evaluated": len(results),
        "skipped": skipped,
        "errors": errors,
        "device": str(DEVICE),
        "evaluated_at": datetime.utcnow().isoformat(),
        "overall_metrics": {
            "mae_avg": round(float(np.mean(mae_list)), 2),
            "mae_median": round(float(np.median(mae_list)), 2),
            "rmse_avg": round(float(np.mean(rmse_list)), 2),
            "rmse_median": round(float(np.median(rmse_list)), 2),
            "mape_avg": round(float(np.mean(mape_list)), 2),
            "mape_median": round(float(np.median(mape_list)), 2),
            "direction_accuracy_avg": round(float(np.mean(dir_acc_list)), 4),
        },
        "change_distribution": change_distribution,
        "products": results,
    }


def print_report(report: Dict[str, Any]) -> None:
    """In báo cáo đánh giá ra console."""
    print("\n" + "=" * 70)
    print("BÁO CÁO ĐÁNH GIÁ LSTM (PYTORCH GPU) TRÊN TOÀN BỘ SẢN PHẨM")
    print("=" * 70)
    print(f"Tổng sản phẩm có lịch sử giá : {report.get('total_products')}")
    print(f"Sản phẩm đã đánh giá        : {report.get('evaluated')}")
    print(f"Sản phẩm bỏ qua (thiếu dữ liệu): {report.get('skipped')}")
    print(f"Sản phẩm lỗi                : {report.get('errors')}")
    print(f"Thời điểm đánh giá          : {report.get('evaluated_at')}")
    print(f"Thiết bị huấn luyện         : {report.get('device')}")

    if "overall_metrics" not in report:
        print("\n" + report.get("message", "Không có dữ liệu."))
        return

    print("\n" + "-" * 70)
    print("CHỈ SỐ SAI SỐ TỔNG HỢP (trung bình trên toàn bộ sản phẩm)")
    print("-" * 70)
    om = report["overall_metrics"]
    print(f"  MAE  trung bình : {om['mae_avg']:>12,.2f} VNĐ   (median: {om['mae_median']:,.2f})")
    print(f"  RMSE trung bình : {om['rmse_avg']:>12,.2f} VNĐ   (median: {om['rmse_median']:,.2f})")
    print(f"  MAPE trung bình : {om['mape_avg']:>12,.2f} %     (median: {om['mape_median']:.2f}%)")
    print(f"  Direction Accuracy trung bình: {om['direction_accuracy_avg'] * 100:.2f} %")

    print("\n" + "-" * 70)
    print("PHÂN BỐ XU HƯỚNG DỰ BÁO GIÁ")
    print("-" * 70)
    for label, count in sorted(report["change_distribution"].items(), key=lambda x: -x[1]):
        pct = count / report["evaluated"] * 100
        print(f"  {label:<12}: {count:>4} sản phẩm ({pct:.1f}%)")

    print("\n" + "-" * 70)
    print("CHI TIẾT TỪNG SẢN PHẨM")
    print("-" * 70)
    header = f"{'STT':<4} {'Sàn':<18} {'Sản phẩm':<30} {'MAE':>10} {'RMSE':>10} {'MAPE%':>8} {'DirAcc%':>8} {'Xu hướng':<12}"
    print(header)
    print("-" * 70)
    for i, r in enumerate(report["products"], 1):
        name = (r.get("name") or "")[:28]
        print(
            f"{i:<4} {r.get('source','')[:16]:<18} {name:<30} "
            f"{r['mae']:>10,.0f} {r['rmse']:>10,.0f} {r['mape']:>8.2f} "
            f"{r['direction_accuracy']*100:>8.2f} {r['change_label']:<12}"
        )

    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Huấn luyện và đánh giá LSTM (PyTorch GPU) trên toàn bộ sản phẩm.")
    parser.add_argument("--min-history", type=int, default=3, help="Số điểm lịch sử giá tối thiểu (mặc định: 3)")
    parser.add_argument("--predict-days", type=int, default=PREDICT_DAYS, help=f"Số ngày dự báo (mặc định: {PREDICT_DAYS})")
    parser.add_argument("--epochs", type=int, default=50, help="Số epochs huấn luyện (mặc định: 50)")
    parser.add_argument("--limit", type=int, default=None, help="Giới hạn số sản phẩm đánh giá")
    parser.add_argument("--force-retrain", action="store_true", help="Buộc huấn luyện lại từ đầu")
    parser.add_argument("--json", type=str, default=None, help="Đường dẫn file JSON để lưu kết quả chi tiết")
    args = parser.parse_args()

    init_db()
    try:
        report = evaluate_all_products(
            min_history=args.min_history,
            predict_days=args.predict_days,
            epochs=args.epochs,
            limit=args.limit,
            force_retrain=args.force_retrain,
        )
        print_report(report)

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, default=str)
            logger.info("Đã lưu kết quả chi tiết vào %s", args.json)
    finally:
        close_db()


if __name__ == "__main__":
    main()