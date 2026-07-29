import unittest

from utils.search_filter import (
    build_canonical_key,
    filter_comparable_phones,
    is_phone_product,
    matches_query_exact,
    parse_price,
)


class SearchFilterTests(unittest.TestCase):
    def test_parse_price(self):
        self.assertEqual(parse_price("12.990.000 đ"), 12990000)
        self.assertEqual(parse_price("Liên hệ"), 0)

    def test_is_phone_product_excludes_accessories(self):
        self.assertFalse(is_phone_product("Ốp lưng iPhone 15 Pro Max"))
        self.assertFalse(is_phone_product("Tai nghe AirPods Pro"))
        self.assertTrue(is_phone_product("iPhone 15 Pro Max 256GB"))

    def test_matches_query_exact(self):
        self.assertTrue(matches_query_exact("Apple iPhone 15 Pro Max 256GB", "iPhone 15 Pro Max"))
        self.assertFalse(matches_query_exact("iPhone 15 Pro", "iPhone 15 Pro Max"))
        self.assertTrue(matches_query_exact("Samsung Galaxy S24 Ultra 256GB", "Galaxy S24 Ultra 256GB"))

    def test_build_canonical_key_aligns_variants(self):
        key_a = build_canonical_key("Apple iPhone 15 Pro Max 256GB (Chính hãng)", "iPhone 15 Pro Max")
        key_b = build_canonical_key("iPhone 15 Pro Max 256GB", "iPhone 15 Pro Max")
        self.assertEqual(key_a, key_b)

    def test_filter_picks_cheapest_per_platform_and_aligns(self):
        products = [
            {"name": "iPhone 15 Pro Max 256GB", "price": "30.000.000 đ", "source": "FPT Shop", "product_url": "https://fptshop.com.vn/dien-thoai/a", "image_url": ""},
            {"name": "iPhone 15 Pro Max 256GB", "price": "29.000.000 đ", "source": "FPT Shop", "product_url": "https://fptshop.com.vn/dien-thoai/b", "image_url": ""},
            {"name": "Apple iPhone 15 Pro Max 256GB", "price": "28.500.000 đ", "source": "Thế Giới Di Động", "product_url": "https://thegioididong.com/dtdd/a", "image_url": ""},
            {"name": "Ốp lưng iPhone 15 Pro Max", "price": "200.000 đ", "source": "CellphoneS", "product_url": "https://cellphones.com.vn/phu-kien", "image_url": ""},
            {"name": "iPhone 15 Pro Max 128GB", "price": "25.000.000 đ", "source": "CellphoneS", "product_url": "https://cellphones.com.vn/dien-thoai/c", "image_url": ""},
        ]
        result = filter_comparable_phones(products, "iPhone 15 Pro Max")
        sources = {p["source"] for p in result}
        self.assertIn("FPT Shop", sources)
        self.assertIn("Thế Giới Di Động", sources)
        self.assertNotIn("CellphoneS", sources)  # 128GB khác biến thể 256GB
        fpt = next(p for p in result if p["source"] == "FPT Shop")
        self.assertEqual(fpt["price"], "29.000.000 đ")


if __name__ == "__main__":
    unittest.main()
