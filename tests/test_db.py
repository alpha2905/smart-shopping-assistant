import os
import unittest

from utils.db import init_db, save_search_results, get_product_price_history, get_collection, close_db

MONGO_TEST_DB = "price_tracker_test"


class DbStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["MONGO_DB"] = MONGO_TEST_DB
        init_db()

    @classmethod
    def tearDownClass(cls):
        from utils.db import get_client
        client = get_client()
        client.drop_database(MONGO_TEST_DB)
        close_db()

    def setUp(self):
        get_collection().delete_many({})

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

    def test_single_document_per_product(self):
        """Chỉ 1 document cho 1 sản phẩm, dù scrape nhiều lần."""
        prod = {
            'name': 'Samsung Galaxy',
            'price': '15000000',
            'image_url': 'https://example.com/s23.jpg',
            'product_url': 'https://example.com/s23',
            'source': 'test-shop',
        }
        save_search_results('samsung', [prod])
        save_search_results('samsung', [prod])
        save_search_results('samsung', [prod])

        col = get_collection()
        count = col.count_documents({"product_url": "https://example.com/s23", "source": "test-shop"})
        self.assertEqual(count, 1)

        history = get_product_price_history('https://example.com/s23', 'test-shop')
        self.assertEqual(len(history), 3)


if __name__ == '__main__':
    unittest.main()