"""
MongoDB module for storing products with embedded price history.

Single collection "products":
  - Mỗi document là một sản phẩm
  - price_history là mảng embedded, append-only
"""

import os
import logging
from datetime import datetime, timedelta
import re
from typing import List, Dict, Any, Optional
from collections import defaultdict

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId

load_dotenv()

logger = logging.getLogger(__name__)

def _env_or_default(name, default):
    """Read env var; empty string counts as unset."""
    value = os.environ.get(name, "").strip()
    return value if value else default


MONGO_URI = (
    _env_or_default("MONGODB_URI", "")
    or _env_or_default("MONGO_URI", "")
    or "mongodb+srv://22050040_db_user:Accnam55@giasanpham.uqyaw1p.mongodb.net/?appName=GiaSanPham"
)
MONGO_DB = _env_or_default("MONGO_DB", "price_tracker")


def parse_price(price: str) -> int:
    """
    "29.990.000₫" -> 29990000
    "Liên hệ" -> 0
    """
    if not price:
        return 0

    digits = re.sub(r"[^\d]", "", str(price))

    if not digits:
        return 0

    return int(digits)

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
    col.create_index("name")
    col.create_index("source")
    col.create_index("price_value")
    col.create_index("average_price")
    col.create_index([("price_history.scraped_at", DESCENDING)])
    logger.info("MongoDB indexes initialized in database '%s'", MONGO_DB)

def init_forecast_collection() -> None:
    """Create indexes for the 'forecasts' collection."""
    col = get_db()["forecasts"]
    col.create_index([("product_url", ASCENDING), ("source", ASCENDING)])
    col.create_index([("predict_date", DESCENDING)])
    logger.info("MongoDB 'forecasts' collection indexes initialized")

def init_sentiment_collection() -> None:
    """Create indexes for the 'sentiments' collection."""
    col = get_db()["sentiments"]
    col.create_index([("product_url", ASCENDING), ("source", ASCENDING)], unique=True)
    col.create_index([("created_at", DESCENDING)])
    logger.info("MongoDB 'sentiments' collection indexes initialized")


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
        price_str = prod.get("price", "Liên hệ")
        comments = prod.get("comments", [])

        if not product_url or not source:
            continue

        new_price_value = parse_price(price_str)

        # Find existing doc to check last price and get full history
        existing_doc = col.find_one(
            {"product_url": product_url, "source": source},
            {"price_history": 1}
        )

        history = []
        last_price_value = 0
        last_scraped_at = None
        if existing_doc:
            history = existing_doc.get("price_history", [])
            if history:
                last_entry = history[-1]
                last_price_value = last_entry.get('price_value', parse_price(last_entry.get('price')))
                last_scraped_at = last_entry.get('scraped_at')

        # LUÔN ghi snapshot giá (kể cả khi không đổi) để tích lũy dữ liệu train LSTM.
        # Chỉ bỏ qua nếu entry cuối có CÙNG giá và được ghi trong 55 phút gần nhất
        # (tránh trùng lặp do retry/refresh cùng giờ).
        should_append = True
        if last_scraped_at is not None and last_price_value == new_price_value:
            if isinstance(last_scraped_at, datetime):
                if now - last_scraped_at < timedelta(minutes=55):
                    should_append = False
        
        # Prepare fields for the $set operation
        set_fields = {
            "name": name,
            "image_url": image_url,
            "price": price_str,
            "price_value": new_price_value,
            "query": query,
            "last_scraped_at": now,
        }

        if comments:
            set_fields["comments"] = comments
            set_fields["comments_updated_at"] = now
            set_fields["comments_count"] = len(comments)

        # Calculate and add statistics
        # Luôn cập nhật giá mới nhất, kể cả khi là 0
        set_fields["latest_price"] = new_price_value

        history_prices = [h.get('price_value', parse_price(h.get('price'))) for h in history]
        all_prices = history_prices + [new_price_value]
        # Lọc các giá hợp lệ (> 0) để tính toán thống kê
        valid_prices = [p for p in all_prices if p > 0]
        
        if valid_prices:
            set_fields["lowest_price"] = min(valid_prices)
            set_fields["highest_price"] = max(valid_prices)
            set_fields["average_price"] = int(sum(valid_prices) / len(valid_prices))
        else:
            # Nếu không có giá hợp lệ nào, đặt các thống kê về 0
            set_fields["lowest_price"] = 0
            set_fields["highest_price"] = 0
            set_fields["average_price"] = 0

        # Construct the final update operation
        update_op = {"$set": set_fields}
        if should_append:
            price_change_amount = new_price_value - last_price_value
            price_change_percent = (price_change_amount / last_price_value * 100) if last_price_value > 0 else 0
            update_op["$push"] = {
                "price_history": {
                    "price": price_str,
                    "price_value": new_price_value,
                    "scraped_at": now,
                    "previous_price": last_price_value,
                    "price_change": price_change_amount,
                    "price_change_percent": round(price_change_percent, 2)
                }
            }

        col.update_one({"product_url": product_url, "source": source}, update_op, upsert=True)

    logger.info(
        "Saved %d products for query '%s' (%d new price entries)",
        len(products),
        query,
        len(products),
    )


def get_product_price_history(
    product_url: str, source: str
) -> List[Dict[str, Any]]:
    """Return all historical prices for a product, oldest first.
    It checks both the dedicated source collection and the main 'products' collection.
    """
    db = get_db()
    doc = None

    # Mapping from source name to collection name
    source_to_collection_map = {
        "FPT Shop": "fpt",
        "Thế Giới Di Động": "tgdd",
        "CellphoneS": "cellphones",
        "Hoàng Hà Mobile": "hoangha",
        "Di Động Việt": "didongviet",
        "Viettel Store": "viettelstore",
        "Clickbuy": "clickbuy",
        "MobileCity": "mobilecity",
    }

    # 1. Try dedicated collection first
    collection_name = source_to_collection_map.get(source)
    if collection_name:
        col = db[collection_name]
        doc = col.find_one(
            {"product_url": product_url, "source": source},
            {"price_history": 1, "_id": 0},
        )
    
    # 2. If not found, try the main 'products' collection
    if not doc:
        col = get_collection() # main 'products' collection
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

def get_price_statistics(product_url: str, source: str) -> Optional[Dict[str, Any]]:
    """
    Get pre-calculated price statistics for a product.
    """
    doc = get_collection().find_one(
        {"product_url": product_url, "source": source},
        {
            "_id": 0,
            "latest_price": 1,
            "lowest_price": 1,
            "highest_price": 1,
            "average_price": 1,
            "price_history": {"$slice": -1}  # Get the last history entry for change info
        }
    )
    if not doc:
        return None

    stats = {
        "current_price": doc.get("latest_price"),
        "lowest_price": doc.get("lowest_price"),
        "highest_price": doc.get("highest_price"),
        "average_price": doc.get("average_price"),
    }

    # Add change info from the last history entry
    history = doc.get("price_history", [])
    if history:
        last_entry = history[0]
        stats["price_change"] = last_entry.get("price_change")
        stats["price_change_percent"] = last_entry.get("price_change_percent")

    return stats

def save_forecasts(
    product_url: str,
    source: str,
    forecasts: List[Dict[str, Any]],
    metrics: Dict[str, Any]
) -> None:
    """Saves a batch of forecasts to the 'forecasts' collection."""
    col = get_db()["forecasts"]
    now = datetime.utcnow()
    
    prediction_updated_at = metrics.get("prediction_updated_at", now)
    docs_to_insert = []
    for forecast in forecasts:
        docs_to_insert.append({
            "product_url": product_url,
            "source": source,
            "predict_date": forecast["date"],
            "forecast_price": forecast["price"],
            "model": "LSTM",
            "mae": metrics.get("mae"),
            "rmse": metrics.get("rmse"),
            "mape": metrics.get("mape"),
            "prediction_updated_at": prediction_updated_at,
            "verified": False, # Mark as not yet verified against actual price
        })

    if docs_to_insert:
        # Remove old forecasts for this product before inserting new ones
        col.delete_many({"product_url": product_url, "source": source})
        col.insert_many(docs_to_insert)
        logger.info(f"Saved {len(docs_to_insert)} new forecasts for {source} - {product_url}")

def get_forecasts(product_url: str, source: str) -> List[Dict[str, Any]]:
    """Gets all forecasts for a product, sorted by date."""
    col = get_db()["forecasts"]
    cursor = col.find(
        {"product_url": product_url, "source": source},
        {"_id": 0, "predict_date": 1, "forecast_price": 1}
    ).sort("predict_date", ASCENDING)
    return list(cursor)

def get_unverified_forecasts() -> List[Dict[str, Any]]:
    """Gets all forecasts that have not been verified and whose prediction date is in the past."""
    col = get_db()["forecasts"]
    cursor = col.find({
        "verified": False,
        "predict_date": {"$lt": datetime.utcnow()}
    })
    return list(cursor)

def mark_forecasts_as_verified(forecast_ids: List[ObjectId]) -> None:
    """Marks a list of forecasts as verified."""
    if not forecast_ids:
        return
    col = get_db()["forecasts"]
    col.update_many(
        {"_id": {"$in": forecast_ids}},
        {"$set": {"verified": True}}
    )

def save_sentiment_result(product_url: str, source: str, result: Dict[str, Any]) -> None:
    """
    Upserts the sentiment analysis result for a product into the 'sentiments' collection.
    """
    col = get_db()["sentiments"]
    now = datetime.utcnow()

    update_payload = {
        "$set": {
            "product_url": product_url,
            "source": source,
            "positive": result.get("positive"),
            "neutral": result.get("neutral"),
            "negative": result.get("negative"),
            "sentiment": result.get("sentiment"),
            "sentiment_score": result.get("sentiment_score"),
            "comment_count": result.get("comment_count"),
            "model": "PhoBERT",
            "created_at": now,
        }
    }
    col.update_one(
        {"product_url": product_url, "source": source},
        update_payload,
        upsert=True
    )
    logger.info(f"Saved sentiment analysis for {source} - {product_url}")

def get_sentiment_result(product_url: str, source: str) -> Optional[Dict[str, Any]]:
    """Retrieves the sentiment analysis result for a product."""
    col = get_db()["sentiments"]
    return col.find_one({"product_url": product_url, "source": source}, {"_id": 0})

def get_all_product_urls_by_source() -> Dict[str, List[str]]:
    """
    Lấy tất cả các URL sản phẩm duy nhất từ TẤT CẢ các collection,
    nhóm chúng theo 'source'.
    Hàm này dùng để phục vụ việc cập nhật giá hàng loạt.
    """
    logger.info("Đang truy vấn tất cả URL sản phẩm duy nhất từ TẤT CẢ các collection trong DB...")
    db = get_db()
    
    collection_names = [
        "products", "tgdd", "fpt", "cellphones", "viettelstore",
        "hoangha", "didongviet", "clickbuy", "mobilecity"
    ]

    urls_by_source = defaultdict(set)

    pipeline = [
        {
            "$match": {
                "product_url": {"$exists": True, "$ne": ""},
                "source": {"$exists": True, "$ne": ""}
            }
        },
        {
            "$group": {
                "_id": "$source",
                "urls": {"$addToSet": "$product_url"}
            }
        }
    ]

    for name in collection_names:
        try:
            if name in db.list_collection_names():
                for item in db[name].aggregate(pipeline):
                    if item.get('_id') and item.get('urls'):
                        urls_by_source[item['_id']].update(item['urls'])
        except Exception as e:
            logger.warning(f"Could not get URLs from collection '{name}': {e}")

    final_urls_by_source = {source: sorted(list(url_set)) for source, url_set in urls_by_source.items()}
    total_urls = sum(len(urls) for urls in final_urls_by_source.values())
    logger.info(f"Đã tìm thấy {total_urls} URL từ {len(final_urls_by_source)} sàn trong DB để cập nhật giá.")
    return final_urls_by_source

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
    """Return products whose last-scraped query matches (latest price + comments).

    Dùng regex case-insensitive để không phân biệt hoa/thường,
    tránh cache/DB miss khi người dùng gõ "iPhone 17" còn dữ liệu lưu "iphone 17".
    """
    col = get_collection()
    results = []
    query_regex = re.compile(f"^{re.escape(query.strip())}$", re.IGNORECASE)
    for doc in col.find({"query": query_regex}):
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
    """Return products that have at least `min_history` price entries from ALL collections."""
    db = get_db()
    results = []
    
    collection_names = [
        "products", "tgdd", "fpt", "cellphones", "viettelstore",
        "hoangha", "didongviet", "clickbuy", "mobilecity"
    ]

    for name in collection_names:
        try:
            col = db[name]
            # Efficiently find documents with enough history using $expr + $size
            for doc in col.find({
                "price_history": {"$exists": True},
                "$expr": {"$gte": [{"$size": "$price_history"}, min_history]}
            }):
                price_history = doc.get("price_history", [])
                results.append({
                    "product_url": doc.get("product_url", ""),
                    "source": doc.get("source", ""),
                    "name": doc.get("name", ""),
                    "image_url": doc.get("image_url", ""),
                    "query": doc.get("query", ""),
                    "price_history_count": len(price_history),
                    "latest_price": price_history[-1].get("price", "") if price_history else "",
                })
        except Exception as e:
             logger.warning(f"Could not get products with history from collection '{name}': {e}")

    results.sort(key=lambda x: x.get("price_history_count", 0), reverse=True)
    return results

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


def get_mobilecity_collection():
    """Return the 'mobilecity' collection."""
    return get_db()["mobilecity"]


def init_mobilecity_collection() -> None:
    """Create indexes for the 'mobilecity' collection if they don't exist."""
    col = get_mobilecity_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'mobilecity' collection indexes initialized")


def save_mobilecity_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'mobilecity' (riêng biệt).
    """
    col = get_mobilecity_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "MobileCity"),
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

    logger.info("Saved %d products to 'mobilecity' collection", saved)
    return saved


def get_all_mobilecity_products() -> List[Dict[str, Any]]:
    """Return all products from the 'mobilecity' collection."""
    col = get_mobilecity_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "MobileCity"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def get_clickbuy_collection():
    """Return the 'clickbuy' collection."""
    return get_db()["clickbuy"]


def init_clickbuy_collection() -> None:
    """Create indexes for the 'clickbuy' collection if they don't exist."""
    col = get_clickbuy_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'clickbuy' collection indexes initialized")


def save_clickbuy_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'clickbuy' (riêng biệt).
    """
    col = get_clickbuy_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "Clickbuy"),
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

    logger.info("Saved %d products to 'clickbuy' collection", saved)
    return saved


def get_all_clickbuy_products() -> List[Dict[str, Any]]:
    """Return all products from the 'clickbuy' collection."""
    col = get_clickbuy_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "Clickbuy"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def get_didongviet_collection():
    """Return the 'didongviet' collection."""
    return get_db()["didongviet"]


def init_didongviet_collection() -> None:
    """Create indexes for the 'didongviet' collection if they don't exist."""
    col = get_didongviet_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'didongviet' collection indexes initialized")


def save_didongviet_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'didongviet' (riêng biệt).
    """
    col = get_didongviet_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "Di Động Việt"),
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

    logger.info("Saved %d products to 'didongviet' collection", saved)
    return saved


def get_all_didongviet_products() -> List[Dict[str, Any]]:
    """Return all products from the 'didongviet' collection."""
    col = get_didongviet_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "Di Động Việt"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def get_hoangha_collection():
    """Return the 'hoangha' collection."""
    return get_db()["hoangha"]


def init_hoangha_collection() -> None:
    """Create indexes for the 'hoangha' collection if they don't exist."""
    col = get_hoangha_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'hoangha' collection indexes initialized")


def save_hoangha_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'hoangha' (riêng biệt).
    """
    col = get_hoangha_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "Hoàng Hà Mobile"),
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

    logger.info("Saved %d products to 'hoangha' collection", saved)
    return saved


def get_all_hoangha_products() -> List[Dict[str, Any]]:
    """Return all products from the 'hoangha' collection."""
    col = get_hoangha_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "Hoàng Hà Mobile"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


def get_unique_queries() -> List[str]:
    """Return all distinct query strings ever searched from ALL collections."""
    db = get_db()
    all_queries = set()
    
    collection_names = [
        "products", "tgdd", "fpt", "cellphones", "viettelstore",
        "hoangha", "didongviet", "clickbuy", "mobilecity"
    ]

    for name in collection_names:
        try:
            col = db[name]
            # Check if 'query' field exists in the collection's documents
            if col.count_documents({"query": {"$exists": True}}) > 0:
                queries = col.distinct("query")
                for q in queries:
                    if q: # filter out None or empty strings
                        all_queries.add(q)
        except Exception as e:
            logger.warning(f"Could not get queries from collection '{name}': {e}")
    
    logger.info(f"Found {len(all_queries)} unique queries across all collections.")
    return sorted(list(all_queries))


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


def get_viettelstore_collection():
    """Return the 'viettelstore' collection."""
    return get_db()["viettelstore"]


def init_viettelstore_collection() -> None:
    """Create indexes for the 'viettelstore' collection if they don't exist."""
    col = get_viettelstore_collection()
    col.create_index([("product_url", ASCENDING)], unique=True)
    col.create_index([("name", ASCENDING)])
    col.create_index([("last_scraped_at", DESCENDING)])
    logger.info("MongoDB 'viettelstore' collection indexes initialized")


def save_viettelstore_products(products: List[Dict[str, Any]]) -> int:
    """
    Upsert products vào collection 'viettelstore' (riêng biệt).
    """
    col = get_viettelstore_collection()
    now = datetime.utcnow()
    saved = 0

    for prod in products:
        product_url = prod.get("product_url", "")
        if not product_url:
            continue

        price = prod.get("price", "")
        set_fields = {
            "name": prod.get("name", ""),
            "image_url": prod.get("image_url", ""),
            "price": price,
            "source": prod.get("source", "Viettel Store"),
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

    logger.info("Saved %d products to 'viettelstore' collection", saved)
    return saved


def get_all_viettelstore_products() -> List[Dict[str, Any]]:
    """Return all products from the 'viettelstore' collection."""
    col = get_viettelstore_collection()
    results = []
    for doc in col.find({}):
        price_history = doc.get("price_history", [])
        latest_price = price_history[-1] if price_history else {}
        results.append({
            "product_url": doc.get("product_url", ""),
            "name": doc.get("name", ""),
            "image_url": doc.get("image_url", ""),
            "price": doc.get("price", latest_price.get("price", "")),
            "source": doc.get("source", "Viettel Store"),
            "last_scraped_at": doc.get("last_scraped_at"),
            "comments": doc.get("comments", []),
            "comments_count": doc.get("comments_count", 0),
            "price_history_count": len(price_history),
        })
    results.sort(key=lambda x: x.get("name", ""))
    return results


# ─── Users & Favorites ─────────────────────────────────────────────────

def get_users_collection():
    """Return the 'users' collection."""
    return get_db()["users"]


def get_favorites_collection():
    """Return the 'favorites' collection."""
    return get_db()["favorites"]


def init_auth_collections() -> None:
    """Create indexes for 'users' and 'favorites' collections."""
    users = get_users_collection()
    users.create_index([("email", ASCENDING)], unique=True)
    users.create_index([("username", ASCENDING)], unique=True)

    favs = get_favorites_collection()
    favs.create_index(
        [("user_id", ASCENDING), ("product_url", ASCENDING), ("source", ASCENDING)],
        unique=True,
    )
    favs.create_index([("created_at", DESCENDING)])
    logger.info("MongoDB 'users' and 'favorites' collection indexes initialized")


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Find a user by email (case-insensitive)."""
    return get_users_collection().find_one({"email": email.strip().lower()})


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Find a user by username (case-sensitive, field stored lowercase)."""
    return get_users_collection().find_one({"username": username.strip().lower()})


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Find a user by its ObjectId string."""
    try:
        return get_users_collection().find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None


def create_user(username: str, email: str, password_hash: str) -> Dict[str, Any]:
    """Insert a new user; raises pymongo DuplicateKeyError if already exists."""
    now = datetime.utcnow()
    user = {
        "username": username.strip().lower(),
        "email": email.strip().lower(),
        "password_hash": password_hash,
        "created_at": now,
    }
    result = get_users_collection().insert_one(user)
    user["_id"] = result.inserted_id
    return user


def add_favorite(
    user_id: str,
    product_url: str,
    source: str,
    product_data: Dict[str, Any],
) -> bool:
    """
    Add a favorite product for a user. Returns True if newly added,
    False if it already existed.
    """
    col = get_favorites_collection()
    doc = {
        "user_id": user_id,
        "product_url": product_url,
        "source": source,
        "name": product_data.get("name", ""),
        "image_url": product_data.get("image_url", ""),
        "price": product_data.get("price", ""),
        "created_at": datetime.utcnow(),
    }
    try:
        col.insert_one(doc)
        return True
    except Exception:
        # Duplicate → already favorite
        return False


def remove_favorite(user_id: str, product_url: str, source: str) -> bool:
    """Remove a favorite product. Returns True if something was removed."""
    result = get_favorites_collection().delete_one(
        {"user_id": user_id, "product_url": product_url, "source": source}
    )
    return result.deleted_count > 0


def get_favorites(user_id: str) -> List[Dict[str, Any]]:
    """Return all favorite products for a user, most recently added first."""
    cursor = get_favorites_collection().find(
        {"user_id": user_id}, {"_id": 0, "user_id": 0}
    ).sort("created_at", DESCENDING)
    return list(cursor)


def is_favorite(user_id: str, product_url: str, source: str) -> bool:
    """Check whether a product is already in the user's favorites."""
    return (
        get_favorites_collection().count_documents(
            {"user_id": user_id, "product_url": product_url, "source": source}
        )
        > 0
    )
