# tests/test_db.py
import pytest
from mongomock import MongoClient
from unittest.mock import patch
from datetime import datetime, timedelta

# We need to patch the db connection before importing the functions
@pytest.fixture(scope="function")
def mock_db():
    with patch('utils.db.get_client') as mock_get_client:
        mock_client = MongoClient()
        mock_get_client.return_value = mock_client
        yield mock_client
        mock_client.close()

def test_save_search_results_new_product(mock_db):
    """
    Tests saving a completely new product.
    """
    from utils.db import save_search_results, get_collection
    
    collection = get_collection()
    assert collection.count_documents({}) == 0

    product_data = [{
        "product_url": "http://example.com/product1",
        "source": "TestStore",
        "name": "Test Product 1",
        "price": "1.000.000đ"
    }]

    save_search_results("test query", product_data)

    assert collection.count_documents({}) == 1
    doc = collection.find_one()
    assert doc["name"] == "Test Product 1"
    assert doc["price_value"] == 1000000
    assert len(doc["price_history"]) == 1
    assert doc["price_history"][0]["price_value"] == 1000000

def test_save_search_results_price_change(mock_db):
    """
    Tests that a new price entry is pushed to history when the price changes.
    """
    from utils.db import save_search_results, get_collection
    
    # First save
    product_data_1 = [{"product_url": "http://example.com/product1", "source": "TestStore", "name": "Test Product 1", "price": "1.000.000đ"}]
    save_search_results("test query", product_data_1)

    # Second save with different price
    product_data_2 = [{"product_url": "http://example.com/product1", "source": "TestStore", "name": "Test Product 1 Updated", "price": "1.200.000đ"}]
    save_search_results("test query", product_data_2)

    doc = get_collection().find_one()
    assert doc["name"] == "Test Product 1 Updated"
    assert doc["price_value"] == 1200000
    assert len(doc["price_history"]) == 2
    assert doc["price_history"][0]["price_value"] == 1000000
    assert doc["price_history"][1]["price_value"] == 1200000
    assert doc["price_history"][1]["price_change"] == 200000

def test_save_search_results_no_price_change_dedupe(mock_db):
    """
    Gia khong doi và lan ghi truoc cach <55 phut -> KHONG append entry trung
    (tranh trung lap khi workflow chay lai trong cung 1 gio).
    """
    from utils.db import save_search_results, get_collection

    product_data = [{"product_url": "http://example.com/product1", "source": "TestStore", "name": "Test Product 1", "price": "1.000.000đ"}]
    save_search_results("test query", product_data)
    first_save_time = get_collection().find_one()["last_scraped_at"]

    save_search_results("test query", product_data)

    doc = get_collection().find_one()
    assert len(doc["price_history"]) == 1
    assert doc["last_scraped_at"] >= first_save_time

def test_save_search_results_same_price_new_hour_appends(mock_db):
    """
    Gia khong doi nhung da qua khung gio moi (>=55 phut) -> VAN append snapshot
    de tich luy du lieu huan luyen LSTM (append-only theo gio).
    """
    from utils.db import save_search_results, get_collection

    product_data = [{"product_url": "http://example.com/product1", "source": "TestStore", "name": "Test Product 1", "price": "1.000.000đ"}]
    save_search_results("test query", product_data)

    # Mo phong lan ghi truoc da cach 2 gio
    col = get_collection()
    col.update_one(
        {"product_url": "http://example.com/product1", "source": "TestStore"},
        {"$set": {"price_history.0.scraped_at": datetime.utcnow() - timedelta(hours=2)}}
    )

    save_search_results("test query", product_data)

    doc = get_collection().find_one()
    assert len(doc["price_history"]) == 2
    assert doc["price_history"][0]["price_value"] == 1000000
    assert doc["price_history"][1]["price_value"] == 1000000
    assert doc["price_history"][1]["price_change"] == 0
