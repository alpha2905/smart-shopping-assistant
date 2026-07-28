import json
import csv
import os
from typing import List
from models.product import Product, SearchResult
from datetime import datetime


class Exporter:
    """Export search results to various formats."""

    @staticmethod
    def export_json(results: List[Product], query: str, output_dir: str = "output") -> str:
        """Export results to a JSON file."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/results_{query.replace(' ', '_')}_{timestamp}.json"

        search_result = SearchResult(
            query=query,
            results=results,
            total_count=len(results)
        )

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(search_result.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

        return filename

    @staticmethod
    def export_csv(results: List[Product], query: str, output_dir: str = "output") -> str:
        """Export results to a CSV file."""
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/results_{query.replace(' ', '_')}_{timestamp}.csv"

        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["STT", "Tên sản phẩm", "Giá", "Hình ảnh", "Link", "Nguồn", "Bình luận"])
            for idx, product in enumerate(results, 1):
                comments_str = " | ".join(product.comments[:5]) if product.comments else ""
                writer.writerow([
                    idx,
                    product.name,
                    product.price,
                    product.image_url,
                    product.product_url,
                    product.source,
                    comments_str
                ])

        return filename

    @staticmethod
    def print_summary(results: List[Product], query: str) -> None:
        """Print a formatted summary of results to console."""
        from collections import Counter

        print(f"\n{'='*80}")
        print(f"  KẾT QUẢ TÌM KIẾM: {query}")
        print(f"{'='*80}")

        source_counts = Counter(p.source for p in results)
        print(f"\n  Tổng số sản phẩm tìm thấy: {len(results)}")
        print(f"\n  Phân bố theo nguồn:")
        for source, count in source_counts.most_common():
            print(f"    - {source}: {count} sản phẩm")

        print(f"\n  Danh sách sản phẩm:")
        print(f"  {'-'*80}")
        for idx, product in enumerate(results[:20], 1):
            print(f"  {idx}. {product.name}")
            print(f"     Giá: {product.price}")
            print(f"     Nguồn: {product.source}")
            print(f"     Link: {product.product_url}")
            if product.comments:
                print(f"     Bình luận: {len(product.comments)} bình luận")
            print()

        if len(results) > 20:
            print(f"  ... và {len(results) - 20} sản phẩm khác")
        print(f"{'='*80}\n")
