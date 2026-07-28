from pydantic import BaseModel
from typing import List, Optional


class Product(BaseModel):
    """Product data model for scraped items."""
    name: str
    price: str
    image_url: str
    product_url: str
    source: str
    comments: List[str] = []


class SearchResult(BaseModel):
    """Wrapper for all search results from a query."""
    query: str
    results: List[Product]
    total_count: int
