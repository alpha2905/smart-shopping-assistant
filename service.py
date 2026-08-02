# ai/sentiment/service.py
import logging
from typing import List, Dict, Any

from utils.db import get_product_comments, save_sentiment_result
from ai.sentiment.model import get_sentiment_pipeline
from ai.sentiment.preprocess import preprocess_comments
from ai.sentiment.infer import analyze_sentiments

logger = logging.getLogger(__name__)

# Initialize the pipeline once when the module is loaded
try:
    sentiment_pipeline = get_sentiment_pipeline()
except Exception as e:
    sentiment_pipeline = None
    logger.error("Sentiment analysis pipeline could not be initialized. Sentiment features will be disabled.")

def analyze_and_save_product_sentiment(product_url: str, source: str) -> Dict[str, Any]:
    """
    Full pipeline: Get comments, preprocess, analyze, and save the result.
    """
    if not sentiment_pipeline:
        raise RuntimeError("Sentiment pipeline is not available.")

    # 1. Get comments from DB
    comments = get_product_comments(product_url, source)
    if not comments:
        return {"message": "No comments found for this product."}

    # 2. Preprocess comments
    processed_comments = preprocess_comments(comments)
    if not processed_comments:
        return {"message": "No valid comments left after preprocessing."}

    # 3. Analyze sentiments
    analysis_result = analyze_sentiments(sentiment_pipeline, processed_comments)

    # 4. Save result to DB
    save_sentiment_result(product_url, source, analysis_result)

    return analysis_result