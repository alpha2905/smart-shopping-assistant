"""
MongoDB module for storing products with embedded price history.

Single collection "products":
  - Mỗi document là một sản phẩm
  - price_history là mảng embedded, append-only
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

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
    Lưu cả comments (bình luận/đánh giá) nếu scraper cào được.
    """
    col = get_collection()
    now = datetime.utcnow()

    for prod in products:
        product_url = prod.get("product_url", "")
        source = prod.get("source", "")
        name = prod.get("name", "")
        image_url = prod.get("image_url", "")
        price = prod.get("price", "")
        comments = prod.get("comments", [])

        if not product_url or not source:
            continue

        set_fields = {
            "name": name,
            "image_url": image_url,
            "query": query,
            "last_scraped_at": now,
        }

        # Chỉ cập nhật comments khi scraper thực sự cào được comment mới
        # (tránh ghi đè comment cũ bằng list rỗng khi scraper không lấy comment)
        if comments:
            set_fields["comments"] = comments
            set_fields["comments_updated_at"] = now
            set_fields["comments_count"] = len(comments)

        col.update_one(
            {"product_url": product_url, "source": source},
            {
                "$set": set_fields,
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


def get_product_comments(product_url: str, source: str) -> List[str]:
    """
    Return comments/reviews đã cào được cho một sản phẩm.
    Trả về list rỗng nếu chưa có comment.
    """
    col = get_collection()
    doc = col.find_one(
        {"product_url": product_url, "source": source},
        {"comments": 1, "_id": 0},
    )
    if not doc or "comments" not in doc:
        return []
    return doc.get("comments", [])


def get_all_products() -> List[Dict[str, Any]]:
    """Return latest snapshot of all tracked products with their current price and comments."""
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
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
        })
    results.sort(key=lambda x: (x.get("query", ""), x.get("source", ""), x.get("name", "")))
    return results


def get_latest_prices_for_query(query: str) -> List[Dict[str, Any]]:
    """Return products whose last-scraped query matches (latest price + comments)."""
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
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
        })
    results.sort(key=lambda x: (x.get("source", ""), x.get("name", "")))
    return results


def get_products_with_price_history(min_history: int = 3) -> List[Dict[str, Any]]:
    """Return products that have at least `min_history` price entries."""
    col = get_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        if len(price_history) >= min_history:
            results.append({
                "product_url": doc.get("product_url", ""),
                "source": doc.get("source", ""),
                "name": doc.get("name", ""),
                "image_url": doc.get("image_url", ""),
                "query": doc.get("query", ""),
                "price_history_count": len(price_history),
                "latest_price": price_history[-1].get("price", "") if price_history else "",
            })
    results.sort(key=lambda x: x.get("price_history_count", 0), reverse=True)
    return results


def save_prediction(product_url: str, source: str, prediction: Dict[str, Any]) -> None:
    """Cache LSTM prediction in the product document."""
    col = get_collection()

    # Convert numpy types to native Python types for JSON serialization
    def convert_numpy(obj):
        if isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy(v) for v in obj]
        elif hasattr(obj, "item"):  # numpy scalars
            return obj.item()
        return obj

    cleaned_prediction = convert_numpy(prediction)

    col.update_one(
        {"product_url": product_url, "source": source},
        {"$set": {
            "prediction": cleaned_prediction,
            "prediction_updated_at": datetime.utcnow(),
        }},
    )
    logger.info("Cached prediction for %s/%s", source, product_url[:50])


def get_prediction(product_url: str, source: str) -> Optional[Dict[str, Any]]:
    """Get cached prediction for a product, or None if not cached."""
    col = get_collection()
    doc = col.find_one(
        {"product_url": product_url, "source": source},
        {"prediction": 1, "prediction_updated_at": 1, "_id": 0},
    )
    if not doc or "prediction" not in doc:
        return None
    return {
        "prediction": doc["prediction"],
        "prediction_updated_at": doc.get("prediction_updated_at"),
    }


def get_tgdd_collection():
    """Return the 'tgdd' collection (separate from 'products')."""
    return get_db()["tgdd"]


def init_tgdd_collection() -> None:
    """Create indexes for the 'tgdd' collection if they don't exist."""
    col = get_tgdd_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'tgdd' collection indexes initialized")


def save_tgdd_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'tgdd' (riêng biệt).
    Mỗi sản phẩm: upsert theo product_url, push price vào price_history.
    Trả về số sản phẩm đã lưu.
    """
    col = get_tgdd_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        name = prod.get("name", "")
        if not product_url:
            continue

        set_fields = {
            "name": name,
            "image_url": prod.get("image_url", ""),
            "price": prod.get("price", ""),
            "source": prod.get("source", "Thế Giới Di Động"),
            "last_scraped_at": now,
        }

        comments = prod.get("comments", [])
        if comments:
            set_fields["comments"] = comments
            set_fields["comments_count"] = len(comments)
            set_fields["comments_updated_at"] = now

        col.update_one(
            {"product_url": product_url},
            {
                "$set": set_fields,
                "$push": {
                    "price_history": {
                        "price": prod.get("price", ""),
                        "scraped_at": now,
                    }
                },
            },
            upsert=True,
        )
        saved += 1

    logger.info("Saved %d products to 'tgdd' collection", saved)
    return saved


def get_all_tgdd_products() -> List[Dict[str, Any]]:
    """Return all products from the 'tgdd' collection."""
    col = get_tgdd_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "Thế Giới Di Động"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
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

def get_cellphones_collection():
    """Return the 'cellphones' collection (separate from 'products')."""
    return get_db()["cellphones"]


def init_cellphones_collection() -> None:
    """Create indexes for the 'cellphones' collection if they don't exist."""
    col = get_cellphones_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'cellphones' collection indexes initialized")


def get_all_cellphones_products() -> List[Dict[str, Any]]:
    """Return all products from the 'cellphones' collection."""
    col = get_cellphones_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "CellphoneS"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def save_cellphones_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert sản phẩm vào collection 'cellphones' (riêng biệt).
    Mỗi sản phẩm: upsert theo product_url, push price vào price_history.
    Trả về số sản phẩm đã lưu.
    """
    col = get_cellphones_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        name = prod.get("name", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": name,
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "CellphoneS"),
            "last_scraped_at": now,
        }

        comments = prod.get("comments", [])
        if comments:
            set_fields["comments"] = comments
            set_fields["comments_count"] = len(comments)
            set_fields["comments_updated_at"] = now

        col.update_one(
            {"product_url": product_url},
            {
                "$set": set_fields,
                "$push": {
                    "price_history": {
                        "price": price,
                        "scraped_at": now,
                    }
                },
            },
            upsert=True,
        )
        saved += 1

    logger.info("Saved %d products to 'cellphones' collection", saved)
    return saved


def get_fpt_collection():
    """Return the 'fpt' collection (separate from 'products')."""
    return get_db()["fpt"]


def init_fpt_collection() -> None:
    """Create indexes for the 'fpt' collection if they don't exist."""
    col = get_fpt_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'fpt' collection indexes initialized")


def get_all_fpt_products() -> List[Dict[str, Any]]:
    """Return all products from the 'fpt' collection."""
    col = get_fpt_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "FPT Shop"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def save_fpt_products_incremental(products: List[Dict[str, Any]]) -> int:
    """
    Upsert sản phẩm vào collection 'fpt' theo cơ chế cào tới đâu lưu tới đó.
    Mỗi sản phẩm: upsert theo product_url, push price vào price_history.
    Trả về số sản phẩm đã lưu.
    """
    col = get_fpt_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        name = prod.get("name", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": name,
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "FPT Shop"),
            "last_scraped_at": now,
        }

        comments = prod.get("comments", [])
        if comments:
            set_fields["comments"] = comments
            set_fields["comments_count"] = len(comments)
            set_fields["comments_updated_at"] = now

        col.update_one(
            {"product_url": product_url},
            {
                "$set": set_fields,
                "$push": {
                    "price_history": {
                        "price": price,
                        "scraped_at": now,
                    }
                },
            },
            upsert=True,
        )
        saved += 1

    logger.info("Saved %d products incrementally to 'fpt' collection", saved)
    return saved