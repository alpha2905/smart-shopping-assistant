# scripts/hourly_scrape.py
import os
import subprocess
import sys
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Thêm thư mục gốc vào path để import được utils/db.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import tất cả các hàm khởi tạo collection từ utils/db.py
from utils.db import (
    init_cellphones_collection, init_tgdd_collection, init_fpt_collection,
    init_hoangha_collection, init_didongviet_collection, init_viettelstore_collection,
    init_clickbuy_collection, init_mobilecity_collection
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Danh sách các file cào cần chạy
CRAWLER_FILES = [
    "crawl_cellphones_all.py",
    "crawl_tgdd_all.py",
    "crawl_fpt_all.py",
    "crawl_hoangha_all.py",
    "crawl_didongviet_all.py",
    "crawl_viettelstore_all.py",
    "crawl_clickbuy_all.py",
    "crawl_mobilecity_all.py",
]

def init_all_collections_manually():
    """Gọi lần lượt các hàm init collection có sẵn trong utils/db.py"""
    try:
        logger.info("🛠️ Đang khởi tạo indexes cho các collection...")
        init_cellphones_collection()
        init_tgdd_collection()
        init_fpt_collection()
        init_hoangha_collection()
        init_didongviet_collection()
        init_viettelstore_collection()
        init_clickbuy_collection()
        init_mobilecity_collection()
        logger.info("✅ Hoàn tất khởi tạo indexes cho tất cả collection.")
    except Exception as e:
        logger.warning(f"⚠️ Lưu ý khi init collection (có thể đã có index): {e}")

def run_single_crawler(file_name: str) -> dict:
    """Hàm chạy 1 file scraper riêng lẻ - Dùng cho đa luồng"""
    file_path = os.path.join("scripts", file_name)
    result_info = {
        "file": file_name,
        "success": False,
        "output": "",
        "error": ""
    }

    if not os.path.exists(file_path):
        result_info["error"] = "File không tồn tại"
        return result_info

    try:
        logger.info(f"👉 [Thread] Đang chạy: {file_name}...")
        start_time = time.time()
        
        result = subprocess.run(
            [sys.executable, file_path],
            capture_output=True,
            text=True,
            check=False
        )
        
        duration = time.time() - start_time
        
        if result.returncode == 0:
            result_info["success"] = True
            result_info["output"] = f"Thời gian chạy: {duration:.2f}s\n{result.stdout}"
        else:
            result_info["error"] = f"Thời gian chạy: {duration:.2f}s\nMã lỗi: {result.returncode}\n{result.stderr}"

    except Exception as e:
        result_info["error"] = str(e)

    return result_info

def run_hourly_scrape():
    logger.info("🚀 Bắt đầu quy trình cào giá hàng giờ cho 8 sàn (ĐA LUỒNG)...")
    
    # Khởi tạo indexes cho các collection
    init_all_collections_manually()

    # Số luồng tối đa chạy đồng thời 
    # (Khuyên dùng 2 để tránh GitHub Actions hết RAM nếu dùng Playwright/Selenium)
    MAX_WORKERS = 2

    logger.info(f"⏳ Sẽ chạy tối đa {MAX_WORKERS} luồng cùng lúc để tránh quá tải RAM...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Gửi tất cả các tác vụ vào pool
        future_to_file = {
            executor.submit(run_single_crawler, file_name): file_name 
            for file_name in CRAWLER_FILES
        }

        # Lấy kết quả khi từng luồng hoàn thành
        for future in as_completed(future_to_file):
            result = future.result()
            
            if result["success"]:
                logger.info(f"✅ {result['file']} chạy THÀNH CÔNG.\nOutput:\n{result['output']}")
            else:
                logger.error(f"❌ {result['file']} chạy THẤT BẠI.\nLỗi:\n{result['error']}")

    logger.info("🎉 Hoàn tất quy trình cào giá cho tất cả 8 sàn!")

if __name__ == "__main__":
    run_hourly_scrape()