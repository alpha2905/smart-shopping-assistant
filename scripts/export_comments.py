# -*- coding: utf-8 -*-
"""Trích xuất bình luận (comments) từ MongoDB để train PhoBERT.

Mặc định chỉ đọc collection 'products' (nguồn dữ liệu chính được tích lũy
qua save_search_results / crawl-to-products). Muốn gộp thêm comments từ các
collection riêng của từng sàn (tgdd, fpt, ...), dùng --all-collections.
"""
import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows console mặc định dùng cp1252 -> ép UTF-8 để in tiếng Việt
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from utils.db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Mặc định: chỉ lấy comments từ collection 'products' (đúng pipeline train PhoBERT
# từ dữ liệu sản phẩm đã cào). Mở rộng bằng --all-collections.
PRODUCT_COLLECTIONS = ["products"]
ALL_COLLECTIONS = [
    "products", "tgdd", "fpt", "cellphones", "hoangha",
    "didongviet", "viettelstore", "clickbuy", "mobilecity",
]


def _to_text(comment) -> str:
    """Chuẩn hoá 1 comment thành chuỗi (hỗ trợ string lẫn dict)."""
    if comment is None:
        return ""
    if isinstance(comment, str):
        return comment.strip()
    if isinstance(comment, dict):
        for key in ("text", "content", "comment", "body", "message"):
            if comment.get(key):
                return str(comment[key]).strip()
        if len(comment) == 1:
            return str(next(iter(comment.values()))).strip()
        return ""
    return str(comment).strip()


def export_comments(
    output_path: str,
    min_length: int = 2,
    dedupe: bool = True,
    all_collections: bool = False,
) -> int:
    db = get_db()
    records, seen = [], set()

    colls = ALL_COLLECTIONS if all_collections else PRODUCT_COLLECTIONS
    for coll_name in colls:
        col = db[coll_name]
        logger.info("Quét '%s' (%d docs)...", coll_name, col.count_documents({}))
        batch = 0
        for doc in col.find({}):
            comments = doc.get("comments") or []
            if not comments:
                continue
            for c in comments:
                text = _to_text(c)
                if len(text) < min_length:
                    continue
                key = text.lower()
                if dedupe and key in seen:
                    continue
                seen.add(key)
                records.append({
                    "text": text,
                    "source": doc.get("source", coll_name),
                    "product_name": doc.get("name", ""),
                    "product_url": doc.get("product_url", ""),
                    "query": doc.get("query", ""),
                })
                batch += 1
        logger.info("  -> %d comments tu '%s'", batch, coll_name)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    logger.info("Tong cong %d comments -> %s", len(records), output_path)
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Export comments tu MongoDB de train PhoBERT")
    parser.add_argument("--output", default=os.path.join("scripts", "output", "train_comments.json"))
    parser.add_argument("--min-length", type=int, default=2)
    parser.add_argument("--no-dedupe", action="store_true")
    parser.add_argument(
        "--all-collections",
        action="store_true",
        help="Quét thêm comments từ các collection riêng của từng sàn (tgdd, fpt, ...). "
             "Mặc định chỉ đọc collection 'products'.",
    )
    args = parser.parse_args()

    count = export_comments(
        args.output,
        args.min_length,
        not args.no_dedupe,
        all_collections=args.all_collections,
    )

    with open(args.output, "r", encoding="utf-8") as f:
        records = json.load(f)
    sources = {}
    for r in records:
        sources[r["source"]] = sources.get(r["source"], 0) + 1

    print("\n=== THONG KE ===")
    print(f"Tong comments: {count}")
    print(f"Trung binh: {sum(len(r['text']) for r in records) / max(count, 1):.1f} ky tu/comment")
    for src, n in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {src:20s} {n:>6,}")
    print("================")


if __name__ == "__main__":
    main()