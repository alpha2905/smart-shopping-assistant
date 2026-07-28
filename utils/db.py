"""
MongoDB module for storing products with embedded price history.

Single collection "products":
  - Mỗi document là một sản phẩm
  - price_history là mảng embedded, append-only
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://22050040_db_user:Accnam55@giasanpham.uqyaw1p.mongodb.net/?appName=GiaSanPham",
)
MONGO_DB = os.environ.get("MONGO_DB", "price_tracker")

_client: MongoClient = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
        logger.info("Connected to MongoDB at %s", MONGO_URI)
    return _client


def get_db():
    return get_client()[MONGO_DB]


def get_collection():
    return get_db()["products"]


def init_db() -> None:
    """Create indexes if they don't exist."""
    col = get_collection()
    col.create_index([("product_url", ASCENDING), ("source", ASCENDING)], unique=True)
    col.create_index([("query", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    # Index trên mảng price_history.scraped_at để query nhanh
    col.create_index([("price_history.scraped_at", DESCENDING)])
    logger.info("MongoDB indexes initialized in database '%s'", MONGO_DB)


def save_search_results(query: str, products: List[Dict[str, Any]]) -> None:
    """
    Upsert product, push price into price_history array (append-only).
    """
    col = get_collection()
    now = datetime.utcnow()

    for prod in products:
        product_url = prod.get("product_url", "")
        source = prod.get("source", "")
        name = prod.get("name", "")
        image_url = prod.get("image_url", "")
        price = prod.get("price", "")

        if not product_url or not source:
            continue

        col.update_one(
            {"product_url": product_url, "source": source},
            {
                "$set": {
                    "name": name,
                    "image_url": image_url,
                    "query": query,
                    "last_scraped_at": now,
                },
                "$push": {
                    "price_history": {
                        "price": price,
                        "scraped_at": now,
                    }
                },
            },
            upsert=True,
        )

    logger.info(
        "Saved %d products for query '%s' (%d new price entries)",
        len(products),
        query,
        len(products),
    )


def get_product_price_history(
    product_url: str, source: str
) -> List[Dict[str, Any]]:
    """Return all historical prices for a product, oldest first."""
    col = get_collection()
    doc = col.find_one(
        {"product_url": product_url, "source": source},
        {"price_history": 1, "_id": 0},
    )
    if not doc or "price_history" not in doc:
        return []
    return sorted(doc["price_history"], key=lambda x: x["scraped_at"])


def get_all_products() -> List[Dict[str, Any]]:
    """Return latest snapshot of all tracked products with their current price."""
    col = get_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "source": doc.get("source", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "query": doc.get("query", ""),
            "last_scraped_at": doc.get("last_scraped_at"),
            "price": latest_price.get("price", ""),
            "scraped_at": latest_price.get("scraped_at"),
        })
    results.sort(key=lambda x: (x.get("query", ""), x.get("source", ""), x.get("name", "")))
    return results


def get_latest_prices_for_query(query: str) -> List[Dict[str, Any]]:
    """Return products whose last-scraped query matches (latest price only)."""
    col = get_collection()
    results = []
    for doc in col.find({"query": query}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "source": doc.get("source", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "query": doc.get("query", ""),
            "last_scraped_at": doc.get("last_scraped_at"),
            "price": latest_price.get("price", ""),
            "scraped_at": latest_price.get("scraped_at"),
        })
    results.sort(key=lambda x: (x.get("source", ""), x.get("name", "")))
    return results


def get_unique_queries() -> List[str]:
    """Return all distinct query strings ever searched."""
    col = get_collection()
    return col.distinct("query")


def close_db() -> None:
    """Close the MongoDB connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")