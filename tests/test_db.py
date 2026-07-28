import os
import unittest

from utils.db import init_db, save_search_results, get_product_price_history, close_db

MONGO_TEST_DB = "price_tracker_test"


class DbStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set MongoDB test DB cho toàn bộ test class."""
        os.environ["MONGO_DB"] = MONGO_TEST_DB
        init_db()

    @classmethod
    def tearDownClass(cls):
        """Dọn dẹp: xoá test database và đóng kết nối."""
        from utils.db import get_client
        client = get_client()
        client.drop_database(MONGO_TEST_DB)
        close_db()

    def setUp(self):
        """Xoá dữ liệu cũ trong collection products và price_history trước mỗi test."""
        from utils.db import get_products_collection, get_price_history_collection
        get_products_collection().delete_many({})
        get_price_history_collection().delete_many({})

    def test_save_search_results_keeps_price_history(self):
        first = [{
            'name': 'iPhone 15',
            'price': '20000000',
            'image_url': 'https://example.com/1.jpg',
            'product_url': 'https://example.com/iphone-15',
            'source': 'test-shop',
            'comments': ['good']
        }]
        save_search_results('iphone', first)

        second = [{
            'name': 'iPhone 15',
            'price': '21000000',
            'image_url': 'https://example.com/1.jpg',
            'product_url': 'https://example.com/iphone-15',
            'source': 'test-shop',
            'comments': ['great']
        }]
        save_search_results('iphone', second)

        history = get_product_price_history('https://example.com/iphone-15', 'test-shop')
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['price'], '20000000')
        self.assertEqual(history[1]['price'], '21000000')


if __name__ == '__main__':
    unittest.main()