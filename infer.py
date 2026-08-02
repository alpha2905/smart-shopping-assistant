# ai/sentiment/infer.py
import logging
from typing import List, Dict, Any
from collections import Counter

logger = logging.getLogger(__name__)

def analyze_sentiments(pipeline, comments: List[str]) -> Dict[str, Any]:
    """
    Analyzes a list of comments using the PhoBERT pipeline and aggregates the results.
    """
    if not comments:
        return {
            "positive": 0.0, "neutral": 0.0, "negative": 0.0,
            "sentiment": "neutral", "sentiment_score": 0.5,
            "comment_count": 0
        }

    try:
        # PhoBERT returns results like [{'label': 'NEU', 'score': 0.9...}]
        results = pipeline(comments)
    except Exception as e:
        logger.error(f"Error during sentiment pipeline inference: {e}")
        return {}

    # Map PhoBERT labels to our standard labels
    label_map = {"POS": "positive", "NEU": "neutral", "NEG": "negative"}
    sentiments = [label_map.get(res['label'], "neutral") for res in results]
    
    counts = Counter(sentiments)
    total = len(sentiments)

    positive_pct = counts.get("positive", 0) / total
    neutral_pct = counts.get("neutral", 0) / total
    negative_pct = counts.get("negative", 0) / total

    # Calculate a single sentiment score (e.g., from 0 to 1)
    # positive=1, neutral=0.5, negative=0
    sentiment_score = (positive_pct * 1.0) + (neutral_pct * 0.5) + (negative_pct * 0.0)

    return {
        "positive": round(positive_pct, 4),
        "neutral": round(neutral_pct, 4),
        "negative": round(negative_pct, 4),
        "sentiment": counts.most_common(1)[0][0] if counts else "neutral",
        "sentiment_score": round(sentiment_score, 4),
        "comment_count": total
    }