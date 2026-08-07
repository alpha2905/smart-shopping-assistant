# -*- coding: utf-8 -*-
"""
Mô hình PhoBERT phân loại cảm xúc 3 nhãn (Tích cực, Tiêu cực, Trung lập).
Hỗ trợ fine-tune trên tập dữ liệu tùy chỉnh.
"""
import logging
import os
from typing import List, Dict, Any, Optional

import torch

from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
    pipeline,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "vinai/phobert-base-v2"
LABELS = ["negative", "neutral", "positive"]
LABEL_TO_ID = {label: idx for idx, label in enumerate(LABELS)}
ID_TO_LABEL = {idx: label for label, idx in LABEL_TO_ID.items()}

# Thư mục lưu model đã fine-tune
FINETUNED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "saved_models",
    "phobert",
)
FINETUNED_MODEL_PATH = os.path.join(FINETUNED_DIR, "sentiment_3label")


def get_sentiment_pipeline():
    """
    Khởi tạo PhoBERT sentiment pipeline.
    Ưu tiên model đã fine-tune (3 nhãn), fallback model gốc.
    """
    try:
        model_path = FINETUNED_MODEL_PATH
        if os.path.isdir(model_path):
            logger.info(f"Đang tải PhoBERT fine-tuned 3 nhãn từ {model_path}...")
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_path,
                num_labels=len(LABELS),
                id2label=ID_TO_LABEL,
                label2id=LABEL_TO_ID,
            )
            logger.info("PhoBERT fine-tuned 3 nhãn loaded thành công.")
        else:
            logger.info(f"Đang tải PhoBERT gốc: {MODEL_NAME}...")
            tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            model = AutoModelForSequenceClassification.from_pretrained(
                MODEL_NAME,
                num_labels=len(LABELS),
                id2label=ID_TO_LABEL,
                label2id=LABEL_TO_ID,
            )
            # Thay thế classification head cho 3 nhãn
            model.config.num_labels = len(LABELS)
            model.config.id2label = ID_TO_LABEL
            model.config.label2id = LABEL_TO_ID
            logger.info("PhoBERT gốc loaded, đã cấu hình 3 nhãn phân loại.")

        sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,  # Trả về tất cả xác suất
        )
        logger.info("Sentiment pipeline sẵn sàng.")
        return sentiment_pipeline
    except Exception as e:
        logger.error(f"Không tải được PhoBERT model: {e}", exc_info=True)
        raise


def fine_tune_phobert(
    texts: List[str],
    labels: List[int],
    output_dir: Optional[str] = None,
    epochs: int = 3,
    batch_size: int = 16,
    test_texts: Optional[List[str]] = None,
    test_labels: Optional[List[int]] = None,
    resume_from_checkpoint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fine-tune PhoBERT cho phân loại cảm xúc 3 nhãn.

    Args:
        texts: Danh sách văn bản huấn luyện
        labels: Nhãn tương ứng (0=negative, 1=neutral, 2=positive)
        output_dir: Thư mục lưu model (mặc định: saved_models/phobert/sentiment_3label)
        epochs: Số epoch huấn luyện
        batch_size: Kích thước batch
        test_texts/test_labels: Tập đánh giá (tùy chọn)
        resume_from_checkpoint: Path checkpoint (từ Trainer save_strategy="epoch") nếu muốn tiếp tục train

    Returns:
        Dict chứa metrics đánh giá (accuracy, precision, recall, f1)
    """
    import numpy as np
    from sklearn.metrics import (
        accuracy_score, precision_recall_fscore_support, classification_report,
    )
    from transformers import DataCollatorWithPadding
    from datasets import Dataset

    save_path = output_dir or FINETUNED_MODEL_PATH
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    logger.info("Bắt đầu fine-tune PhoBERT: %d mẫu, %d epochs", len(texts), epochs)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=len(LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )

    def tokenize_fn(examples):
        # max_length 128 thay vì 256: giảm VRAM ~1/2, đủ cho bình luận ngắn tiếng Việt
        return tokenizer(examples["text"], truncation=True, padding=False, max_length=128)

    train_data = Dataset.from_dict({"text": texts, "label": labels})
    train_data = train_data.map(tokenize_fn, batched=True)

    train_args = TrainingArguments(
        output_dir=os.path.join(save_path, "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        eval_strategy="no",
        # Lưu checkpoint SAU MỖI EPOCH để không mất công train lại nếu bị gián đoạn
        save_strategy="epoch",
        save_total_limit=3,
        logging_dir=os.path.join(save_path, "logs"),
        logging_steps=50,
        learning_rate=2e-5,
        weight_decay=0.01,
        warmup_ratio=0.1,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=train_args,
        train_dataset=train_data,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
    )

    trainer.train(resume_from_checkpoint=resume_from_checkpoint)
    # Giải phóng VRAM trước khi tạo pipeline đánh giá (tránh CUDA OOM)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Lưu model + tokenizer
    model.save_pretrained(save_path)
    tokenizer.save_pretrained(save_path)
    logger.info("Đã lưu model fine-tuned tại: %s", save_path)

    # Đánh giá nếu có tập test
    result: Dict[str, Any] = {"saved_path": save_path}
    if test_texts and test_labels:
        # Chạy đánh giá trên CPU để tránh OOM (model fine-tune đang chiếm VRAM)
        pred_pipeline = pipeline(
            "sentiment-analysis", model=model, tokenizer=tokenizer,
            top_k=None, device=-1,
        )
        predictions = []
        for text in test_texts:
            res = pred_pipeline(text)[0]
            # res là list [{label, score}, ...]
            label_score = max(res, key=lambda x: x["score"])
            pred_label = LABEL_TO_ID[label_score["label"]]
            predictions.append(pred_label)

        acc = accuracy_score(test_labels, predictions)
        precision, recall, f1, _ = precision_recall_fscore_support(
            test_labels, predictions, average="weighted", zero_division=0
        )
        result["accuracy"] = round(acc, 4)
        result["precision"] = round(precision, 4)
        result["recall"] = round(recall, 4)
        result["f1"] = round(f1, 4)
        result["classification_report"] = classification_report(
            test_labels, predictions, target_names=LABELS, zero_division=0
        )
        logger.info(
            "Kết quả fine-tune: Accuracy=%.4f, Precision=%.4f, Recall=%.4f, F1=%.4f",
            acc, precision, recall, f1,
        )

    return result