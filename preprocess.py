# ai/sentiment/preprocess.py
from typing import List

def clean_comment(comment: str) -> str:
    """
    Basic cleaning for a single comment before sending to PhoBERT.
    """
    if not comment:
        return ""
    # Simple cleaning: remove extra whitespace
    return " ".join(comment.split())

def preprocess_comments(comments: List[str]) -> List[str]:
    """
    Preprocesses a list of comments for sentiment analysis.
    """
    return [clean_comment(c) for c in comments if c and len(c.split()) > 2]