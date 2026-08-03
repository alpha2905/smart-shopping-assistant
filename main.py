import logging
import sys
import json
from typing import List, Dict, Any, Tuple
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
from datetime import datetime, timedelta

# APScheduler cho tác vụ định kỳ
from apscheduler.schedulers.background import BackgroundScheduler

from utils.db import (
    init_db, save_search_results, get_unique_queries, close_db,
    get_product_price_history, get_products_with_price_history, get_price_statistics, get_latest_prices_for_query,
    get_product_comments,
    init_tgdd_collection, save_tgdd_products, get_all_tgdd_products,
    init_fpt_collection, save_fpt_products_incremental, get_all_fpt_products,
    init_viettelstore_collection, save_viettelstore_products, get_all_viettelstore_products,
    init_hoangha_collection, save_hoangha_products, get_all_hoangha_products,
    init_mobilecity_collection, save_mobilecity_products, get_all_mobilecity_products,
    init_clickbuy_collection, save_clickbuy_products, get_all_clickbuy_products,
    init_didongviet_collection, save_didongviet_products, get_all_didongviet_products,
    init_cellphones_collection, save_cellphones_products, get_all_cellphones_products,
    parse_price, init_forecast_collection, save_forecasts, get_forecasts, init_sentiment_collection, get_sentiment_result)
from utils.chatbot import get_chat_response
from utils.recommendation_engine import (
    calculate_pqs, calculate_price_statistics, get_buy_recommendation,
    analyze_product, analyze_products_batch,
)
from utils.search_filter import filter_comparable_phones

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Platform Product Search API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-memory cache ───────────────────────────────────────────────────
CACHE_TTL = timedelta(hours=1)
_cache: Dict[str, Dict[str, Any]] = {}

# ─── Scheduler chạy ngầm ────────────────────────────────────────────────
scheduler = BackgroundScheduler()


def _get_scraper_classes():
    """
    Lazy import các scraper crawl4ai (chỉ khi cần) để tránh phụ thuộc
    crawl4ai khi chạy CI/tests (requirements.txt không cài crawl4ai).
    """
    from scrapers.all_sites import (
        TGDDScraper, FPTScraper, CellphoneSScraper, HoangHaScraper,
        DiDongVietScraper, ViettelStoreScraper, ClickBuyScraper, MobileCityScraper,
    )
    return [
        FPTScraper, DiDongVietScraper, ClickBuyScraper, CellphoneSScraper,
        ViettelStoreScraper, HoangHaScraper, MobileCityScraper, TGDDScraper,
    ]


def run_single_scraper(scraper_class, query: str, max_products: int = 5) -> List[Dict[str, Any]]:
    """
    Hàm chạy từng scraper (crawl4ai-based) trong thread riêng.
    """
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        scraper = scraper_class(headless=True)
        logger.info(f"Đang cào từ {scraper.site_name} (query='{query}')...")
        products = scraper.search(query=query, max_products=max_products)
        for p in products:
            products_data.append({
                "name": p.name,
                "price": p.price,
                "image_url": p.image_url,
                "product_url": p.product_url,
                "source": p.source,
                "comments": getattr(p, "comments", []),
            })
        logger.info(f"Hoàn thành {scraper.site_name}: {len(products)} sản phẩm")
    except Exception as e:
        logger.error(f"Lỗi khi cào từ {scraper_class.__name__}: {e}", exc_info=True)
    return products_data


def scrape_and_save(query: str) -> List[Dict[str, Any]]:
    """Scrape từ tất cả sàn cho 1 query, lưu vào MongoDB, trả về kết quả."""
    scraper_classes = _get_scraper_classes()

    all_products = []
    max_products = None

    with ThreadPoolExecutor(max_workers=7) as executor:
        future_map = {
            executor.submit(run_single_scraper, sc, query, max_products): sc.__name__
            for sc in scraper_classes
        }

        for future in as_completed(future_map):
            scraper_name = future_map[future]
            try:
                result = future.result()
                if result:
                    all_products.extend(result)
            except Exception as e:
                logger.error(f"Luồng thực thi {scraper_name} gặp sự cố: {e}")

    filtered_products = filter_comparable_phones(all_products, query)
    logger.info(
        f"Lọc kết quả: {len(all_products)} sản phẩm thô → {len(filtered_products)} điện thoại khớp. "
        f"Lưu hết {len(all_products)} sản phẩm vào DB"
    )

    if all_products:
        save_search_results(query, all_products)

    return filtered_products


def scheduled_scrape_all():
    """Chạy mỗi giờ: scrape lại toàn bộ query đã từng được tìm kiếm."""
    logger.info("=== Scheduled scrape: bắt đầu cào lại tất cả query ===")
    try:
        queries = get_unique_queries()
        if not queries:
            logger.info("Chưa có query nào trong DB, bỏ qua scheduled scrape.")
            return
        for q in queries:
            logger.info(f"Scheduled scrape cho query: '{q}'")
            try:
                scrape_and_save(q)
            except Exception as e:
                logger.error(f"Lỗi scheduled scrape query '{q}': {e}", exc_info=True)
        logger.info("=== Scheduled scrape hoàn tất ===")
    except Exception as e:
        logger.error(f"Lỗi scheduled scrape: {e}", exc_info=True)


# ─── Sự kiện vòng đời FastAPI ──────────────────────────────────────────

@app.on_event("startup")
def startup():
    """Khởi tạo DB + scheduler khi app start."""
    init_sentiment_collection()
    init_forecast_collection()
    init_db()

    scheduler.add_job(
        scheduled_scrape_all,
        "interval",
        hours=1,
        id="hourly_scrape",
        replace_existing=True,
        next_run_time=None,
    )
    scheduler.start()
    logger.info("Scheduler started: sẽ scrape lại tất cả query mỗi 1 giờ")


@app.on_event("shutdown")
def shutdown():
    """Dọn dẹp khi app tắt."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    close_db()


# ─── API Endpoint ──────────────────────────────────────────────────────

@app.get("/api/search")
def search_products(
    q: str = Query(..., description="Từ khóa tìm kiếm sản phẩm"),
    force_refresh: bool = Query(False, description="Bỏ qua cache, scrape lại từ đầu"),
):
    now = datetime.utcnow()

    if not force_refresh:
        cached_in_memory = _cache.get(q)
        if cached_in_memory and now < cached_in_memory["expire_at"]:
            logger.info("Query '%s' found in in-memory cache, returning %d products.", q, len(cached_in_memory["data"]))
            return {
                "query": q,
                "total": len(cached_in_memory["data"]),
                "products": cached_in_memory["data"],
                "cached": True,
            }

        cached_in_db = get_latest_prices_for_query(q)
        if cached_in_db:
            logger.info("Query '%s' found in DB, returning %d cached products instantly", q, len(cached_in_db))
            _cache[q] = {"data": cached_in_db, "expire_at": now + CACHE_TTL}
            return {
                "query": q,
                "total": len(cached_in_db),
                "products": cached_in_db,
                "cached": True,
            }

    logger.info("Query '%s' not in cache (or force_refresh), scraping from stores...", q)
    all_products = scrape_and_save(q)

    _cache[q] = {"data": all_products, "expire_at": now + CACHE_TTL}

    return {
        "query": q,
        "total": len(all_products),
        "products": all_products,
        "cached": False,
    }


# ─── SSE Streaming Search Endpoint ─────────────────────────────────────

async def _run_scraper_async(scraper_class, query: str, max_products: int) -> Tuple[str, List[Dict[str, Any]]]:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, run_single_scraper, scraper_class, query, max_products
    )
    source = getattr(scraper_class, "site_name", scraper_class.__name__)
    return source, result


@app.get("/api/search/stream")
async def search_products_stream(
    q: str = Query(..., description="Từ khóa tìm kiếm sản phẩm"),
    force_refresh: bool = Query(False, description="Bỏ qua cache, scrape lại từ đầu"),
):
    now = datetime.utcnow()

    if not force_refresh:
        cached_in_memory = _cache.get(q)
        if cached_in_memory and now < cached_in_memory["expire_at"]:
            logger.info("Query '%s' found in in-memory cache, streaming %d products", q, len(cached_in_memory["data"]))
            async def cached_stream_in_memory():
                yield f"event: cached\ndata: {json.dumps({'total': len(cached_in_memory['data']), 'products': cached_in_memory['data']}, ensure_ascii=False, default=str)}\n\n"
                yield f"event: done\ndata: {json.dumps({'total': len(cached_in_memory['data']), 'query': q, 'cached': True}, ensure_ascii=False)}\n\n"
            return StreamingResponse(cached_stream_in_memory(), media_type="text/event-stream")

        cached_in_db = get_latest_prices_for_query(q)
        if cached_in_db:
            logger.info("Query '%s' found in DB, streaming %d cached products", q, len(cached_in_db))
            _cache[q] = {"data": cached_in_db, "expire_at": now + CACHE_TTL}
            async def cached_stream_db():
                yield f"event: cached\ndata: {json.dumps({'total': len(cached_in_db), 'products': cached_in_db}, ensure_ascii=False, default=str)}\n\n"
                yield f"event: done\ndata: {json.dumps({'total': len(cached_in_db), 'query': q, 'cached': True}, ensure_ascii=False)}\n\n"
            return StreamingResponse(cached_stream_db(), media_type="text/event-stream")

    max_products = 15
    scraper_classes = _get_scraper_classes()

    async def event_stream():
        all_products = []

        tasks = [
            asyncio.ensure_future(_run_scraper_async(sc, q, max_products))
            for sc in scraper_classes
        ]

        try:
            for coro in asyncio.as_completed(tasks):
                try:
                    source, result = await coro
                    if result:
                        all_products.extend(result)
                        event_data = {
                            "source": source,
                            "products": result,
                            "count": len(result),
                        }
                        yield f"event: store\ndata: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
                    else:
                        event_data = {
                            "source": source,
                            "products": [],
                            "count": 0,
                        }
                        yield f"event: store\ndata: {json.dumps(event_data, ensure_ascii=False, default=str)}\n\n"
                except Exception as e:
                    logger.error(f"Lỗi scraper trong SSE stream: {e}", exc_info=True)
                    yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

            filtered_products = filter_comparable_phones(all_products, q)
            logger.info(
                f"SSE stream: {len(all_products)} sản phẩm thô → {len(filtered_products)} điện thoại khớp. "
                f"Lưu hết {len(all_products)} sản phẩm vào DB"
            )

            if all_products:
                save_search_results(q, all_products)

            _cache[q] = {"data": all_products, "expire_at": datetime.utcnow() + CACHE_TTL}

            done_data = {
                "total": len(all_products),
                "query": q,
                "cached": False,
            }
            yield f"event: done\ndata: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"Lỗi nghiêm trọng trong SSE stream: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Price History + LSTM Prediction Endpoints ─────────────────────────
SEQ_LENGTH = 3


def _create_sequences(data, seq_length: int):
    """Tạo chuỗi (X, y) cho LSTM từ dữ liệu đã chuẩn hóa."""
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i : i + seq_length])
        y.append(data[i + seq_length])
    return X, y


def _train_and_predict(price_history: List[Dict[str, Any]], predict_days: int = 7):
    """
    Huấn luyện LSTM nhanh và dự báo giá (lazy import tensorflow).
    Trả về dict kết quả hoặc None nếu không đủ dữ liệu.
    """
    import numpy as np
    from sklearn.preprocessing import MinMaxScaler

    prices = []
    for h in price_history:
        p = h.get("price_value", parse_price(h.get("price", "")))
        if p and p > 0:
            prices.append(float(p))

    if len(prices) < SEQ_LENGTH + 1:
        return None

    prices_raw = np.array(prices).reshape(-1, 1)
    scaler = MinMaxScaler()
    prices_norm = scaler.fit_transform(prices_raw).flatten()

    X, y = _create_sequences(prices_norm, SEQ_LENGTH)
    if not X:
        return None

    X = np.array(X).reshape((len(X), SEQ_LENGTH, 1))
    y = np.array(y)

    # Lazy import tensorflow để tránh lỗi khi chạy CI/tests
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Input, Dropout
    from tensorflow.keras.optimizers import Adam

    model = Sequential([
        Input(shape=(SEQ_LENGTH, 1)),
        LSTM(64, return_sequences=True),
        Dropout(0.2),
        LSTM(32, return_sequences=False),
        Dropout(0.2),
        Dense(16, activation="relu"),
        Dense(1),
    ])
    model.compile(optimizer=Adam(learning_rate=0.01), loss="mse")
    model.fit(X, y, epochs=50, batch_size=4, verbose=0)

    # Dự báo
    last_sequence = prices_norm[-SEQ_LENGTH:].copy()
    predictions_norm = []
    for _ in range(predict_days):
        input_seq = last_sequence.reshape((1, SEQ_LENGTH, 1))
        pred_norm = model.predict(input_seq, verbose=0)[0][0]
        predictions_norm.append(pred_norm)
        last_sequence = np.append(last_sequence[1:], pred_norm)

    predictions_raw = scaler.inverse_transform(np.array(predictions_norm).reshape(-1, 1)).flatten()

    # Metrics
    y_pred_train_norm = model.predict(X, verbose=0)
    y_pred_train_raw = scaler.inverse_transform(y_pred_train_norm)
    y_true_raw = prices_raw[SEQ_LENGTH:]
    mae = float(np.mean(np.abs(y_true_raw - y_pred_train_raw)))
    rmse = float(np.sqrt(np.mean((y_true_raw - y_pred_train_raw) ** 2)))
    mask = y_true_raw != 0
    mape = float(np.mean(np.abs((y_true_raw[mask] - y_pred_train_raw[mask]) / y_true_raw[mask])) * 100) if np.any(mask) else 0.0

    today = datetime.utcnow().date()
    forecasts = [
        {"date": today + timedelta(days=i + 1), "price": round(float(p), 0)}
        for i, p in enumerate(predictions_raw)
    ]

    return {
        "forecasts": forecasts,
        "metrics": {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "mape": round(mape, 2),
            "prediction_updated_at": datetime.utcnow(),
        },
    }


@app.get("/api/products-with-history")
def list_products_with_history():
    """List all products that have enough price history for LSTM prediction."""
    products = get_products_with_price_history(min_history=3)
    return {
        "total": len(products),
        "products": products,
    }


@app.get("/api/product-history")
def get_product_history_api(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    history = get_product_price_history(product_url, source)
    if not history:
        return {"error": "No price history found for this product."}

    chart_data = [
        {
            "time": entry.get("scraped_at").strftime("%Y-%m-%d"),
            "price": entry.get("price_value", parse_price(entry.get("price")))
        }
        for entry in history if entry.get("price_value", parse_price(entry.get("price"))) > 0
    ]
    return chart_data


@app.get("/api/product-statistics")
def get_product_statistics_api(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    stats = get_price_statistics(product_url, source)
    if not stats:
        return {"error": "No statistics found for this product."}
    return stats


@app.get("/api/price-history")
def get_price_history(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
    force_retrain: bool = Query(False, description="Force retrain LSTM (bypass cache)"),
):
    cache_key = f"{source}:{product_url}"
    if not force_retrain:
        cached = _cache.get(cache_key)
        if cached and datetime.utcnow() < cached["expire_at"]:
            logger.info("Returning cached prediction for %s/%s", source, product_url[:50])
            return {
                "product_url": product_url,
                "source": source,
                "cached": True,
                **cached["data"],
            }

    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {
            "product_url": product_url,
            "source": source,
            "error": "No price history found for this product",
        }

    result = _train_and_predict(price_history, predict_days=7)
    if result is None:
        return {
            "product_url": product_url,
            "source": source,
            "error": "Not enough price data for prediction (need ≥3 data points)",
            "history_count": len(price_history),
        }

    # Lưu forecast vào DB
    try:
        save_forecasts(product_url, source, result["forecasts"], result["metrics"])
    except Exception as e:
        logger.error(f"Không lưu được forecast: {e}")

    _cache[cache_key] = {"data": result, "expire_at": datetime.utcnow() + CACHE_TTL}

    return {
        "product_url": product_url,
        "source": source,
        "cached": False,
        **result,
    }


# ─── Chatbot Endpoint ──────────────────────────────────────────────────

@app.post("/api/chat")
def chat_endpoint(message: Dict[str, Any]):
    user_message = message.get("message", "").strip()
    if not user_message:
        return {
            "text": "Bạn chưa nhập tin nhắn. Hãy gửi tin nhắn để tôi hỗ trợ bạn nhé! 😊",
            "intent": "empty",
            "query": None,
        }

    logger.info(f"Chat request: '{user_message[:100]}'")
    response = get_chat_response(user_message)
    return response


# ─── Product Quality Score (PQS) & Recommendation Endpoints ────────────

@app.get("/api/product-analysis")
def product_analysis(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    forecast_data = get_forecasts(product_url, source)

    result = analyze_product(
        product=product,
        comments=get_product_comments(product_url, source),
        forecast_result=forecast_data,
    )
    return result


@app.get("/api/product-pqs")
def product_pqs(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    pqs_result = calculate_pqs(
        product=product,
        comments=get_product_comments(product_url, source),
    )
    return pqs_result


@app.get("/api/price-statistics")
def price_statistics(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    stats = calculate_price_statistics(product_url, source)
    if not stats:
        return {"error": "Not enough price history (need >=2 data points)"}
    return stats


@app.get("/api/buy-recommendation")
def buy_recommendation(
    product_url: str = Query(..., description="Product URL"),
    source: str = Query(..., description="Source name"),
):
    price_history = get_product_price_history(product_url, source)
    if not price_history:
        return {"error": "No data found for this product"}

    latest = price_history[-1] if price_history else {}
    product = {
        "name": latest.get("name", ""),
        "price": latest.get("price", ""),
        "product_url": product_url,
        "source": source,
    }

    pqs_result = calculate_pqs(
        product=product,
        comments=get_product_comments(product_url, source),
    )

    price_stats = calculate_price_statistics(product_url, source)

    forecast_data = get_forecasts(product_url, source)

    recommendation = get_buy_recommendation(
        product=product,
        pqs_result=pqs_result,
        price_stats=price_stats,
        forecast_result=forecast_data,
    )
    return recommendation


@app.get("/api/products-ranked")
def products_ranked(
    query: str = Query(..., description="Search query"),
):
    products = get_latest_prices_for_query(query)
    if not products:
        return {"query": query, "total": 0, "products": []}

    results = analyze_products_batch(products)
    return {
        "query": query,
        "total": len(results),
        "products": results,
    }


# ─── Full Crawl Endpoints (lazy import crawl4ai scrapers) ──────────────

def _crawl_all_sync(scraper_cls, source_name: str) -> List[Dict[str, Any]]:
    """Cào toàn bộ sản phẩm của 1 sàn bằng scraper crawl4ai."""
    if sys.platform == 'win32':
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    products_data = []
    try:
        scraper = scraper_cls(headless=True)
        logger.info(f"Bắt đầu crawl TẤT CẢ sản phẩm từ {source_name}...")
        products = scraper.crawl_all_phones()
        logger.info(f"Đã crawl được {len(products)} sản phẩm từ {source_name}.")

        # Cào comment cho từng sản phẩm
        if products:
            scraper._attach_comments(products, max_comments=300)

        for prod in products:
            products_data.append({
                "name": prod.name,
                "price": prod.price,
                "image_url": prod.image_url,
                "product_url": prod.product_url,
                "source": prod.source,
                "comments": getattr(prod, "comments", []),
            })

        logger.info(f"Crawl {source_name} hoàn tất: {len(products_data)} sản phẩm với comments.")
    except Exception as e:
        logger.error(f"Lỗi khi crawl {source_name}: {e}", exc_info=True)
    return products_data


async def _crawl_and_save(init_fn, save_fn, scraper_cls, source_name):
    init_fn()
    loop = asyncio.get_event_loop()
    products = await loop.run_in_executor(None, _crawl_all_sync, scraper_cls, source_name)

    if not products:
        return {"message": f"Không cào được sản phẩm nào từ {source_name}", "total": 0}

    saved = save_fn(products)
    return {
        "message": f"Đã cào và lưu {saved} sản phẩm vào collection '{source_name}'",
        "total_crawled": len(products),
        "total_saved": saved,
    }


@app.post("/api/crawl/mobilecity")
async def crawl_mobilecity_all():
    from scrapers.all_sites import MobileCityScraper
    return await _crawl_and_save(init_mobilecity_collection, save_mobilecity_products, MobileCityScraper, "mobilecity")


@app.get("/api/mobilecity/products")
def list_mobilecity_products():
    products = get_all_mobilecity_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/clickbuy")
async def crawl_clickbuy_all():
    from scrapers.all_sites import ClickBuyScraper
    return await _crawl_and_save(init_clickbuy_collection, save_clickbuy_products, ClickBuyScraper, "clickbuy")


@app.get("/api/clickbuy/products")
def list_clickbuy_products():
    products = get_all_clickbuy_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/didongviet")
async def crawl_didongviet_all():
    from scrapers.all_sites import DiDongVietScraper
    return await _crawl_and_save(init_didongviet_collection, save_didongviet_products, DiDongVietScraper, "didongviet")


@app.get("/api/didongviet/products")
def list_didongviet_products():
    products = get_all_didongviet_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/viettelstore")
async def crawl_viettelstore_all():
    from scrapers.all_sites import ViettelStoreScraper
    return await _crawl_and_save(init_viettelstore_collection, save_viettelstore_products, ViettelStoreScraper, "viettelstore")


@app.get("/api/viettelstore/products")
def list_viettelstore_products():
    products = get_all_viettelstore_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/hoangha")
async def crawl_hoangha_all():
    from scrapers.all_sites import HoangHaScraper
    return await _crawl_and_save(init_hoangha_collection, save_hoangha_products, HoangHaScraper, "hoangha")


@app.get("/api/hoangha/products")
def list_hoangha_products():
    products = get_all_hoangha_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/cellphones")
async def crawl_cellphones_all():
    from scrapers.all_sites import CellphoneSScraper
    return await _crawl_and_save(init_cellphones_collection, save_cellphones_products, CellphoneSScraper, "cellphones")


@app.get("/api/cellphones/products")
def list_cellphones_products():
    products = get_all_cellphones_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/tgdd")
async def crawl_tgdd_all():
    from scrapers.all_sites import TGDDScraper
    return await _crawl_and_save(init_tgdd_collection, save_tgdd_products, TGDDScraper, "tgdd")


@app.get("/api/tgdd/products")
def list_tgdd_products():
    products = get_all_tgdd_products()
    return {"total": len(products), "products": products}


@app.post("/api/crawl/fpt")
async def crawl_fpt_all():
    from scrapers.all_sites import FPTScraper
    return await _crawl_and_save(init_fpt_collection, save_fpt_products_incremental, FPTScraper, "fpt")


@app.get("/api/fpt/products")
def list_fpt_products():
    products = get_all_fpt_products()
    return {"total": len(products), "products": products}