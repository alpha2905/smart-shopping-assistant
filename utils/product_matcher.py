# -*- coding: utf-8 -*-
"""
Sử dụng Sentence-BERT và Cosine Similarity để tìm kiếm và gom cụm sản phẩm.

Quy trình:
1. Chạy `generate_and_save_embeddings()` một lần để tạo và lưu file embeddings
   cho toàn bộ sản phẩm trong DB.
   `python -m utils.product_matcher --generate`

2. Sử dụng class `ProductMatcher` để tìm kiếm và gom cụm sản phẩm theo query.
   `python -m utils.product_matcher --query "iphone 15 pro max"`
"""
import argparse
import json
import logging
import os
import sys
from typing import List, Dict, Any

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db import get_collection, parse_price, init_db, close_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Model SBERT tiếng Việt, phù hợp cho việc so sánh ngữ nghĩa câu/văn bản ngắn.
MODEL_NAME = "bkai-foundation-models/vietnamese-bi-encoder"

# Các file để lưu dữ liệu đã xử lý
EMBEDDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EMBEDDING_FILE = os.path.join(EMBEDDINGS_DIR, "product_embeddings.npy")
PRODUCT_IDS_FILE = os.path.join(EMBEDDINGS_DIR, "product_ids.json")


def generate_and_save_embeddings(batch_size: int = 32):
    """
    Lấy tất cả sản phẩm từ DB, tạo embeddings cho tên sản phẩm và lưu lại.
    Đây là bước tiền xử lý, chỉ cần chạy một lần hoặc khi dữ liệu thay đổi nhiều.
    """
    if not os.path.exists(EMBEDDINGS_DIR):
        os.makedirs(EMBEDDINGS_DIR)

    init_db()
    collection = get_collection("products")
    logger.info("Đang lấy danh sách sản phẩm từ DB...")
    products = list(collection.find({}, {"_id": 1, "name": 1}))
    close_db()

    if not products:
        logger.warning("Không tìm thấy sản phẩm nào trong DB.")
        return

    logger.info(f"Tìm thấy {len(products)} sản phẩm. Bắt đầu tạo embeddings...")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)

    product_names = [p.get("name", "") for p in products]
    product_ids = [str(p["_id"]) for p in products]

    embeddings = model.encode(
        product_names,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
    )

    logger.info(f"Đã tạo xong embeddings với shape: {embeddings.shape}")

    np.save(EMBEDDING_FILE, embeddings)
    logger.info(f"Đã lưu embeddings vào file: {EMBEDDING_FILE}")

    with open(PRODUCT_IDS_FILE, "w") as f:
        json.dump(product_ids, f)
    logger.info(f"Đã lưu product IDs vào file: {PRODUCT_IDS_FILE}")


class ProductMatcher:
    def __init__(self):
        logger.info("Khởi tạo ProductMatcher...")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(MODEL_NAME, device=self.device)

        # Tải embeddings và IDs đã được tạo trước
        self.embeddings = np.load(EMBEDDING_FILE)
        with open(PRODUCT_IDS_FILE, "r") as f:
            self.product_ids = json.load(f)

        # Tải thông tin sản phẩm vào bộ nhớ để truy cập nhanh
        init_db()
        collection = get_collection("products")
        products_list = list(collection.find({}, {"name": 1, "price": 1, "product_url": 1, "source": 1, "image_url": 1}))
        close_db()
        
        self.products_map = {str(p["_id"]): p for p in products_list}
        
        # Đảm bảo thứ tự sản phẩm khớp với embeddings
        self.ordered_products = [self.products_map[pid] for pid in self.product_ids if pid in self.products_map]
        
        logger.info(f"Đã tải {len(self.ordered_products)} sản phẩm và embeddings.")

    def _get_embedding(self, text: str) -> np.ndarray:
        """Tạo embedding cho một chuỗi văn bản."""
        return self.model.encode(text, convert_to_numpy=True)

    def find_product_groups(
        self, query: str, search_threshold: float = 0.65, group_threshold: float = 0.90
    ) -> List[List[Dict[str, Any]]]:
        """
        Tìm và gom cụm sản phẩm dựa trên query.
        - search_threshold: Ngưỡng tương đồng để một sản phẩm được coi là khớp với query.
        - group_threshold: Ngưỡng tương đồng để các sản phẩm được gom vào cùng một nhóm.
        """
        query_embedding = self._get_embedding(query).reshape(1, -1)

        # 1. Tìm tất cả sản phẩm liên quan đến query
        similarities = cosine_similarity(query_embedding, self.embeddings)[0]
        candidate_indices = np.where(similarities > search_threshold)[0]

        if len(candidate_indices) == 0:
            return []

        # 2. Gom cụm các sản phẩm giống nhau từ các sàn khác nhau
        groups = []
        grouped_indices = set()

        # Sắp xếp các ứng viên theo độ tương đồng giảm dần với query
        sorted_candidate_indices = sorted(candidate_indices, key=lambda i: similarities[i], reverse=True)

        for idx in sorted_candidate_indices:
            if idx in grouped_indices:
                continue

            current_group = [self.ordered_products[idx]]
            grouped_indices.add(idx)
            
            # Lấy embedding của sản phẩm hiện tại làm tham chiếu
            ref_embedding = self.embeddings[idx].reshape(1, -1)

            # Tìm các sản phẩm khác trong danh sách ứng viên giống với sản phẩm tham chiếu
            for other_idx in sorted_candidate_indices:
                if other_idx in grouped_indices:
                    continue
                
                other_embedding = self.embeddings[other_idx].reshape(1, -1)
                group_sim = cosine_similarity(ref_embedding, other_embedding)[0][0]

                if group_sim > group_threshold:
                    current_group.append(self.ordered_products[other_idx])
                    grouped_indices.add(other_idx)
            
            groups.append(current_group)

        return groups

    def format_groups_for_api(self, groups: List[List[Dict[str, Any]]], top_n: int = 3) -> List[Dict[str, Any]]:
        """
        Định dạng các nhóm sản phẩm thành cấu trúc JSON để trả về cho front-end.
        Sắp xếp theo giá và chỉ lấy top_n sản phẩm rẻ nhất.
        """
        formatted_groups = []
        for group in groups:
            if not group:
                continue

            offers = []
            for product in group:
                price_value = parse_price(product.get("price", "0"))
                if price_value > 0:
                    offers.append({
                        "source": product.get("source"),
                        "price": price_value,
                        "product_url": product.get("product_url"),
                    })
            
            if not offers:
                continue

            # Sắp xếp các offer theo giá tăng dần
            sorted_offers = sorted(offers, key=lambda x: x["price"])

            formatted_groups.append({
                "canonical_name": group[0].get("name"), # Lấy tên sản phẩm đầu tiên làm tên đại diện
                "image_url": group[0].get("image_url"),
                "cheapest_offers": sorted_offers[:top_n]
            })
        return formatted_groups


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tìm kiếm và gom cụm sản phẩm.")
    parser.add_argument("--generate", action="store_true", help="Chạy chế độ tạo và lưu embeddings.")
    parser.add_argument("--query", type=str, help="Query tìm kiếm sản phẩm.")
    args = parser.parse_args()

    if args.generate:
        logger.info("Chế độ: Tạo và lưu embeddings...")
        generate_and_save_embeddings()
    elif args.query:
        logger.info(f"Chế độ: Tìm kiếm với query='{args.query}'")
        matcher = ProductMatcher()
        product_groups = matcher.find_product_groups(args.query)
        api_results = matcher.format_groups_for_api(product_groups, top_n=3)
        
        print(json.dumps(api_results, indent=2, ensure_ascii=False))
    else:
        parser.print_help()