# -*- coding: utf-8 -*-
"""Fine-tune PhoBERT sentiment 3 nhãn từ dataset_labeled.json."""
import argparse, json, os, random, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from ai.sentiment.model import fine_tune_phobert, LABELS
from ai.sentiment.preprocess import clean_comment


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="scripts/output/dataset_labeled.json")
    ap.add_argument("--score-threshold", type=float, default=0.4)
    ap.add_argument("--max-train", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=None)
    ap.add_argument("--resume", default=None,
                    help="Path checkpoint từ Trainer save_strategy='epoch' để tiếp tục train (vd: saved_models/phobert/sentiment_3label/checkpoints/checkpoint-295)")
    args = ap.parse_args()

    rows = json.load(open(args.data, encoding="utf-8"))
    print(f"Tổng records: {len(rows):,}")

    # Phân phối score theo nhãn
    score_by_label = defaultdict(list)
    for r in rows:
        score_by_label[r["label"]].append(r["score"])
    print("\n=== PHÂN PHỐI SCORE ===")
    for lab in LABELS:
        s = sorted(score_by_label.get(lab, []))
        if s:
            q = lambda p: s[min(len(s) - 1, int(len(s) * p))]
            print(f"  {lab:10s} n={len(s):>6,}  q25={q(0.25):.3f}  median={q(0.5):.3f}  q75={q(0.75):.3f}")

    # Lọc theo score
    kept = rows if args.score_threshold <= 0 else [r for r in rows if r["score"] >= args.score_threshold]
    print(f"\nLọc score >= {args.score_threshold}: giữ {len(kept):,}/{len(rows):,}")

    # Preprocess lại (clean_comment đã fix "pro max")
    texts, labels, skipped = [], [], 0
    for r in kept:
        c = clean_comment(r["text"])
        if c and len(c.split()) >= 3:
            texts.append(c); labels.append(r["label_id"])
        else:
            skipped += 1
    print(f"Preprocess xong: {len(texts):,} mẫu (bỏ {skipped})")

    # Stratified split 85/15
    random.seed(args.seed)
    by_label = defaultdict(list)
    for i, lab in enumerate(labels):
        by_label[lab].append(i)
    train_idx, test_idx = [], []
    for lab in sorted(by_label):
        idxs = by_label[lab]; random.shuffle(idxs)
        n_test = max(1, int(len(idxs) * 0.15))
        test_idx += idxs[:n_test]; train_idx += idxs[n_test:]
    if args.max_train and len(train_idx) > args.max_train:
        train_idx = train_idx[:args.max_train]

    train_texts = [texts[i] for i in train_idx]
    train_labels = [labels[i] for i in train_idx]
    test_texts = [texts[i] for i in test_idx]
    test_labels = [labels[i] for i in test_idx]

    print("\n=== SPLIT ===")
    for title, tl in [("Train", train_labels), ("Test", test_labels)]:
        d = Counter(tl); total = len(tl) or 1
        parts = [f"{LABELS[k]}={v:,}({v/total*100:.1f}%)" for k, v in sorted(d.items())]
        print(f"  {title} (N={len(tl):,}): " + ", ".join(parts))

    print(f"\nFine-tune: {len(train_texts):,} train / {len(test_texts):,} test")
    result = fine_tune_phobert(
        texts=train_texts, labels=train_labels,
        epochs=args.epochs, batch_size=args.batch_size,
        test_texts=test_texts, test_labels=test_labels,
        output_dir=args.output,
        resume_from_checkpoint=args.resume,
    )

    print("\n=== KẾT QUẢ ===")
    for k, v in result.items():
        print(f"  {k}: {v}" if k != "classification_report" else v)


if __name__ == "__main__":
    main()