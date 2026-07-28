"""
MongoDB module for storing products and price history.

Two collections:
  - products: one doc per (product_url, source), upserted each scrape
  - price_history: one doc per scrape event per product (append-only)
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any

from dotenv import load_dotenv
import pymongo
from pymongo import MongoClient, ASCENDING, DESCENDING

# Load .env file at module level
load_dotenv()

logger = logging.getLogger(__name__)

# MongoDB Atlas URI (set in .env or environment variable)
# Default: the user's Atlas cluster
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


def get_products_collection():
    return get_db()["products"]


def get_price_history_collection():
    return get_db()["price_history"]


def init_db() -> None:
    """Create indexes if they don't exist."""
    db = get_db()

    # products collection: unique compound index on (product_url, source)
    products_col = db["products"]
    products_col.create_index([("product_url", ASCENDING), ("source", ASCENDING)], unique=True)
    products_col.create_index([("query", ASCENDING)])
    products_col.create_index([("last_scraped_at", DESCENDING)])

    # price_history collection: index for fast lookups
    history_col = db["price_history"]
    history_col.create_index([("product_url", ASCENDING), ("source", ASCENDING), ("scraped_at", ASCENDING)])
    history_col.create_index([("scraped_at", ASCENDING)])

    logger.info("MongoDB indexes initialized in database '%s'", MONGO_DB)


def save_search_results(query: str, products: List[Dict[str, Any]]) -> None:
    """
    Upsert products and append price history.
    Called after every scrape batch.
    """
    products_col = get_products_collection()
    history_col = get_price_history_collection()
    now = datetime.utcnow()

    for prod in products:
        product_url = prod.get("product_url", "")
        source = prod.get("source", "")
        name = prod.get("name", "")
        image_url = prod.get("image_url", "")
        price = prod.get("price", "")

        if not product_url or not source:
            continue

        # Upsert product
        products_col.update_one(
            {"product_url": product_url, "source": source},
            {"$set": {
                "name": name,
                "image_url": image_url,
                "query": query,
                "last_scraped_at": now,
            }},
            upsert=True,
        )

        # Append price history (never delete old prices)
        history_col.insert_one({
            "product_url": product_url,
            "source": source,
            "price": price,
            "scraped_at": now,
        })

    logger.info(
        "Saved %d products for query '%s' (%d new price rows)",
        len(products),
        query,
        len(products),
    )


def get_product_price_history(
    product_url: str, source: str
) -> List[Dict[str, Any]]:
    """Return all historical prices for a product, oldest first."""
    history_col = get_price_history_collection()
    cursor = history_col.find(
        {"product_url": product_url, "source": source},
        {"price": 1, "scraped_at": 1, "_id": 0},
    ).sort("scraped_at", ASCENDING)
    return list(cursor)


def get_all_products() -> List[Dict[str, Any]]:
    """Return latest snapshot of all tracked products with their current price."""
    products_col = get_products_collection()
    history_col = get_price_history_collection()

    results = []
    for prod in products_col.find({}):
        # Find the most recent price history entry for this product
        latest_price = history_col.find_one(
            {"product_url": prod["product_url"], "source": prod["source"]},
            sort=[("scraped_at", DESCENDING)],
        )
        doc = {
            "product_url": prod.get("product_url", ""),
            "source": prod.get("source", ""),
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "query": prod.get("query", ""),
            "last_scraped_at": prod.get("last_scraped_at"),
            "price": latest_price["price"] if latest_price else "",
            "scraped_at": latest_price["scraped_at"] if latest_price else None,
        }
        results.append(doc)

    results.sort(key=lambda x: (x.get("query", ""), x.get("source", ""), x.get("name", "")))
    return results


def get_latest_prices_for_query(query: str) -> List[Dict[str, Any]]:
    """Return products whose last-scraped query matches (latest price only)."""
    products_col = get_products_collection()
    history_col = get_price_history_collection()

    results = []
    for prod in products_col.find({"query": query}):
        latest_price = history_col.find_one(
            {"product_url": prod["product_url"], "source": prod["source"]},
            sort=[("scraped_at", DESCENDING)],
        )
        doc = {
            "product_url": prod.get("product_url", ""),
            "source": prod.get("source", ""),
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "query": prod.get("query", ""),
            "last_scraped_at": prod.get("last_scraped_at"),
            "price": latest_price["price"] if latest_price else "",
            "scraped_at": latest_price["scraped_at"] if latest_price else None,
        }
        results.append(doc)

    results.sort(key=lambda x: (x.get("source", ""), x.get("name", "")))
    return results


def get_unique_queries() -> List[str]:
    """Return all distinct query strings ever searched."""
    products_col = get_products_collection()
    return products_col.distinct("query")


def close_db() -> None:
    """Close the MongoDB connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")