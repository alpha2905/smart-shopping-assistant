# scripts/hourly_scrape.py
import os
import subprocess
import sys
import logging

# Thêm thư mục gốc vào path để import database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import các hàm init collection từ file database.py của bạn
from utils.db import (
    init_cellphones_collection, init_tgdd_collection, init_fpt_collection,
    init_hoangha_collection, init_didongviet_collection, init_viettelstore_collection,
    init_clickbuy_collection, init_mobilecity_collection
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Danh sách các file cào cần chạy (đảm bảo tên file trùng khớp với thư mục scripts của bạn)
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
    """Gọi lần lượt các hàm khởi tạo index cho từng collection"""
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
        logger.warning(f"⚠️ Lưu ý khi init collection (có thể đã tồn tại): {e}")

def run_hourly_scrape():
    logger.info("🚀 Bắt đầu quy trình cào giá hàng giờ cho 8 sàn...")
    
    # Khởi tạo indexes (chạy 1 lần đầu tiên là đủ, nếu lỗi cũng không sao)
    init_all_collections_manually()

    # Duyệt qua từng file trong thư mục scripts và thực thi
    for file_name in CRAWLER_FILES:
        # Đường dẫn đầy đủ tới file cào
        file_path = os.path.join("scripts", file_name)
        
        # Kiểm tra xem file có tồn tại không trước khi chạy
        if not os.path.exists(file_path):
            logger.warning(f"⚠️ Không tìm thấy file: {file_path}, bỏ qua...")
            continue

        logger.info(f"👉 Đang chạy: {file_name}...")
        
        try:
            # Dùng subprocess để gọi file .py ngoài, giống như chạy trên terminal
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                check=False # Đặt check=False để nếu 1 file lỗi, vẫn chạy tiếp các file sau
            )
            
            # In ra output nếu thành công
            if result.returncode == 0:
                logger.info(f"✅ {file_name} chạy thành công.\nOutput:\n{result.stdout}")
            else:
                # In ra lỗi nếu file chạy thất bại
                logger.error(f"❌ {file_name} chạy thất bại với mã lỗi {result.returncode}.\nSTDERR:\n{result.stderr}")
                
        except Exception as e:
            logger.error(f"❌ Lỗi không xác định khi chạy {file_name}: {e}")

    logger.info("🎉 Hoàn tất quy trình cào giá cho tất cả 8 sàn!")

if __name__ == "__main__":
    run_hourly_scrape()