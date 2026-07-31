"""
Quick test to verify the matches_query_exact fix for brand-only queries.
Run: python -m pytest tests/test_filter_fix.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.search_filter import matches_query_exact, normalize_text, filter_comparable_phones


def test_samsung_brand_only():
    """Query 'samsung' should match 'Samsung Galaxy S26 Ultra'"""
    name = "Samsung Galaxy S26 Ultra (5G) 12GB 256GB - 1 đổi 1 12 tháng"
    query = "samsung"
    result = matches_query_exact(name, query)
    print(f"Test 1: query='{query}' vs name='{name[:50]}...' = {result}")
    assert result == True, f"FAILED: query '{query}' should match '{name[:50]}...'"


def test_iphone_brand_only():
    """Query 'iphone' should match 'Apple iPhone 15 Pro Max'"""
    name = "Apple iPhone 15 Pro Max 256GB"
    query = "iphone"
    result = matches_query_exact(name, query)
    print(f"Test 2: query='{query}' vs name='{name}' = {result}")
    assert result == True, f"FAILED: query '{query}' should match '{name}'"


def test_samsung_model_query():
    """Query 'samsung galaxy s26' should match product name"""
    name = "Samsung Galaxy S26 Ultra (5G) 12GB 256GB"
    query = "samsung galaxy s26"
    result = matches_query_exact(name, query)
    print(f"Test 3: query='{query}' vs name='{name[:50]}...' = {result}")
    assert result == True, f"FAILED: query '{query}' should match '{name[:50]}...'"


def test_iphone_15_query():
    """Query 'iphone 15' should match 'Apple iPhone 15 Pro Max'"""
    name = "Apple iPhone 15 Pro Max 256GB"
    query = "iphone 15"
    result = matches_query_exact(name, query)
    print(f"Test 4: query='{query}' vs name='{name}' = {result}")
    assert result == True, f"FAILED: query '{query}' should match '{name}'"


def test_normalize():
    """Verify normalize_text works correctly"""
    name = "Samsung Galaxy S26 Ultra (5G) 12GB 256GB - 1 đổi 1 12 tháng"
    norm = normalize_text(name)
    print(f"Test 5: normalize='{norm}'")
    assert "samsung" in norm, f"FAILED: 'samsung' should be in normalized text"
    assert "galaxy" in norm, f"FAILED: 'galaxy' should be in normalized text"


if __name__ == "__main__":
    test_samsung_brand_only()
    test_iphone_brand_only()
    test_samsung_model_query()
    test_iphone_15_query()
    test_normalize()
    print("\n=== ALL TESTS PASSED! ===")