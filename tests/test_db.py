import os
import unittest

from utils.db import (
    init_db, save_search_results, get_product_price_history,
    get_collection, close_db, get_product_comments,
)

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

    def test_save_and_retrieve_comments(self):
        """Lưu comments vào DB và lấy ra được."""
        prod = {
            'name': 'iPhone 15 Pro',
            'price': '25000000',
            'image_url': 'https://example.com/iphone15pro.jpg',
            'product_url': 'https://example.com/iphone-15-pro',
            'source': 'FPT Shop',
            'comments': ['Sản phẩm rất tốt', 'Pin khá', 'Máy đẹp, đáng mua'],
        }
        save_search_results('iphone', [prod])

        comments = get_product_comments('https://example.com/iphone-15-pro', 'FPT Shop')
        self.assertEqual(len(comments), 3)
        self.assertIn('Sản phẩm rất tốt', comments)
        self.assertIn('Pin khá', comments)
        self.assertIn('Máy đẹp, đáng mua', comments)

    def test_comments_updated_on_rescrape(self):
        """Khi scrape lại, comments mới ghi đè comments cũ."""
        url = 'https://example.com/iphone-15-pro'
        source = 'FPT Shop'

        first = [{
            'name': 'iPhone 15 Pro',
            'price': '25000000',
            'image_url': 'https://example.com/iphone15pro.jpg',
            'product_url': url,
            'source': source,
            'comments': ['Bình luận cũ 1', 'Bình luận cũ 2'],
        }]
        save_search_results('iphone', first)

        second = [{
            'name': 'iPhone 15 Pro',
            'price': '24000000',
            'image_url': 'https://example.com/iphone15pro.jpg',
            'product_url': url,
            'source': source,
            'comments': ['Bình luận mới 1', 'Bình luận mới 2', 'Bình luận mới 3'],
        }]
        save_search_results('iphone', second)

        comments = get_product_comments(url, source)
        self.assertEqual(len(comments), 3)
        self.assertIn('Bình luận mới 1', comments)
        self.assertNotIn('Bình luận cũ 1', comments)

    def test_empty_comments_not_overwrite_existing(self):
        """Khi scraper không cào được comment (list rỗng), không ghi đè comment cũ."""
        url = 'https://example.com/iphone-15-pro'
        source = 'Thế Giới Di Động'

        first = [{
            'name': 'iPhone 15 Pro',
            'price': '25000000',
            'image_url': 'https://example.com/iphone15pro.jpg',
            'product_url': url,
            'source': source,
            'comments': ['Comment cũ 1', 'Comment cũ 2'],
        }]
        save_search_results('iphone', first)

        # Scrape lại nhưng không có comment (scraper khác không cào comment)
        second = [{
            'name': 'iPhone 15 Pro',
            'price': '24000000',
            'image_url': 'https://example.com/iphone15pro.jpg',
            'product_url': url,
            'source': source,
            'comments': [],
        }]
        save_search_results('iphone', second)

        comments = get_product_comments(url, source)
        self.assertEqual(len(comments), 2)
        self.assertIn('Comment cũ 1', comments)

    def test_get_product_comments_empty(self):
        """Sản phẩm chưa có comment trả về list rỗng."""
        prod = {
            'name': 'Test Phone',
            'price': '10000000',
            'image_url': 'https://example.com/test.jpg',
            'product_url': 'https://example.com/test-phone',
            'source': 'test-shop',
        }
        save_search_results('test', [prod])

        comments = get_product_comments('https://example.com/test-phone', 'test-shop')
        self.assertEqual(comments, [])


if __name__ == '__main__':
    unittest.main()
