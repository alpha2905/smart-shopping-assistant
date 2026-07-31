# DONE: Complete implementation for FPT Shop + CellphoneS crawl to MongoDB

## FPT Shop (`scrapers/fptshop.py` + `scripts/crawl_fpt_all.py`)
- [x] Updated selectors matching actual HTML structure
- [x] Added pagination support via `.pagerLink`
- [x] Updated `extract_comments()` with `span.break-word` selector
- [x] API endpoints: `POST /api/crawl/fpt`, `GET /api/fpt/products`

## CellphoneS (`scrapers/cellphones.py` + `scripts/crawl_cellphones_all.py`)
- [x] Updated `crawl_all_phones()` with proper selectors
- [x] Updated `extract_comments()` with `div.boxReview-comment-item`
- [x] Added collection `cellphones` to `utils/db.py`
- [x] Created `scripts/crawl_cellphones_all.py`
- [x] API endpoints: `POST /api/crawl/cellphones`, `GET /api/cellphones/products`

## How to run:
- `python scripts/crawl_fpt_all.py` - Crawl FPT Shop into MongoDB collection `fpt`
- `python scripts/crawl_cellphones_all.py` - Crawl CellphoneS into MongoDB collection `cellphones`
- Via API: `POST /api/crawl/fpt`, `POST /api/crawl/cellphones`

