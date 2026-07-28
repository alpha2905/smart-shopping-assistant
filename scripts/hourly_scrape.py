"""
Script dùng cho GitHub Actions - scrape tất cả query đã lưu.
Chạy: python scripts/hourly_scrape.py
"""
import asyncio
import os
import sys

# Thêm thư mục gốc của project vào sys.path để import được utils, scrapers,...
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.db import init_db, get_unique_queries
from main import scrape_and_save


def main():
    init_db()
    queries = get_unique_queries()
    print(f"Found {len(queries)} queries to scrape: {queries}")
    for q in queries:
        print(f"Scraping: {q}")
        try:
            results = scrape_and_save(q)
            print(f"  -> {len(results)} products saved")
        except Exception as e:
            print(f"  -> Error: {e}")
    print("Done!")


if __name__ == "__main__":
    main()