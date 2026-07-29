"""
Script dùng cho GitHub Actions - scrape tất cả query đã lưu.
Chạy: python scripts/hourly_scrape.py

Sau khi scrape xong, train LSTM cho tất cả sản phẩm có đủ price history.
"""
import asyncio
import os
import sys

# Thêm thư mục gốc của project vào sys.path để import được utils, scrapers,...
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from utils.db import (
    init_db, get_unique_queries, get_products_with_price_history,
    get_product_price_history, save_prediction,
)
from main import scrape_and_save
from utils.price_predictor import train_and_predict


def train_all_predictions():
    """Train LSTM cho tất cả sản phẩm có đủ price history (≥3 data points)."""
    logger.info("=== Training LSTM predictions for all products ===")
    try:
        products = get_products_with_price_history(min_history=3)
        if not products:
            logger.info("No products with enough price history yet, skipping LSTM training.")
            return

        logger.info(f"Found {len(products)} products to train LSTM")
        for prod in products:
            product_url = prod["product_url"]
            source = prod["source"]
            try:
                price_history = get_product_price_history(product_url, source)
                result = train_and_predict(price_history, predict_days=7)
                if result:
                    save_prediction(product_url, source, result)
                    logger.info(f"  ✓ {source}: {prod['name'][:40]} ({result['model_type']})")
                else:
                    logger.warning(f"  ✗ {source}: {prod['name'][:40]} - not enough data")
            except Exception as e:
                logger.error(f"  ✗ {source}: {prod['name'][:40]} - {e}")
        logger.info("=== LSTM training complete ===")
    except Exception as e:
        logger.error(f"Error in train_all_predictions: {e}", exc_info=True)


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

    # Train LSTM predictions after scraping
    train_all_predictions()
    print("Done!")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger(__name__)
    main()