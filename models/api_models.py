# models/api_models.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class Product(BaseModel):
    product_url: str
    source: str
    name: str
    image_url: Optional[str] = None
    price: str
    comments: List[str] = []
    comments_count: int = 0
    last_scraped_at: Optional[datetime] = None

class SearchResponse(BaseModel):
    query: str
    total: int
    products: List[Product]
    cached: bool

class SentimentResponse(BaseModel):
    positive: float
    neutral: float
    negative: float
    sentiment: str
    sentiment_score: float
    comment_count: int
    model: str
    created_at: datetime

class PriceHistoryEntry(BaseModel):
    time: str
    price: int

class PriceStatisticsResponse(BaseModel):
    current_price: Optional[int] = None
    lowest_price: Optional[int] = None
    highest_price: Optional[int] = None
    average_price: Optional[int] = None
    price_change: Optional[int] = None
    price_change_percent: Optional[float] = None

class ForecastEntry(BaseModel):
    predict_date: datetime
    forecast_price: float

class ForecastResponse(BaseModel):
    product_url: str
    source: str
    forecast: List[ForecastEntry]