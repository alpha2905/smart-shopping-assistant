# ai/dataset.py
import logging
from typing import List, Dict, Any
from utils.db import get_product_price_history

logger = logging.getLogger(__name__)

def get_price_data(product_url: str, source: str) -> List[Dict[str, Any]]:
    """
    Fetches price history for a specific product from the database.
    """
    logger.info(f"Fetching price history for {source} - {product_url}")
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        logger.warning("No price history found.")
        return []
    return price_history