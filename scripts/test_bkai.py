# -*- coding: utf-8 -*-
"""Test nhanh model sentiment tiếng Việt đã train sẵn."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL = "wonrax/phobert-base-vietnamese-sentiment"
print(f"Đang tải {MODEL}...")
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL)
print("Nhãn:", model.config.id2label)
print()

import torch
tests = [
    "Tuyệt vời",
    "Sản phẩm dùng rất tốt, pin trâu, hàng chính hãng",
    "Sao ko phải là bản VN/A mà lại là ZP/A, thất vọng",
    "Máy nóng quá, pin tụt nhanh, không đáng mua",
    "Nghe gọi bình thường, không có gì đặc biệt",
]
for t in tests:
    inputs = tok(t, return_tensors="pt", truncation=True, max_length=256)
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)[0]
    pred = model.config.id2label[int(probs.argmax())]
    print(f"[{pred}] (" + "/".join(f"{p:.3f}" for p in probs) + f") | {t}")