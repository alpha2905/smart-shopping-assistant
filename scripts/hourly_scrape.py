# scripts/hourly_scrape.py
import os
import subprocess
import sys
import logging

# Thêm thư mục gốc vào path để import database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.db import init_all_collections

logging.basicConfig(level=logging.INFO)
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

def run_hourly_scrape():
    logger.info("🚀 Bắt đầu quy trình cào giá hàng giờ cho 8 sàn...")
    
    # Khởi tạo indexes cho Mongo (chạy 1 lần là đủ)
    init_all_collections()

    # Duyệt qua từng file và thực thi
    for file_name in CRAWLER_FILES:
        file_path = os.path.join("scripts", file_name)
        logger.info(f"👉 Đang chạy: {file_name}...")
        
        try:
            # Dùng subprocess để gọi file .py ngoài, giống như chạy trên terminal
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"✅ {file_name} chạy thành công.\nOutput:\n{result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Lỗi khi chạy {file_name}.\nSTDERR:\n{e.stderr}")
        except Exception as e:
            logger.error(f"❌ Lỗi không xác định với {file_name}: {e}")

    logger.info("🎉 Hoàn tất quy trình cào giá cho tất cả 8 sàn!")

if __name__ == "__main__":
    run_hourly_scrape()