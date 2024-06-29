# tests/test_system_5.py

import unittest
from src.system_5 import System5

class TestSystem5(unittest.TestCase):

    def setUp(self):
        self.system5 = System5()

    def test_encrypt_decrypt_data(self):
        data = b"Sensitive data"
        encrypted_data = self.system5.encrypt_data(data)
        decrypted_data = self.system5.decrypt_data(encrypted_data)
        self.assertEqual(decrypted_data, data)

    def test_api_request(self):
        endpoint = "https://api.example.com/data"
        params = {"query": "example"}
        headers = {"Authorization": "Bearer test_token"}
        response = self.system5.external_api_request(endpoint, params, headers)
        self.assertIsNotNone(response)

    def test_scrape_web_page(self):
        url = "https://example.com"
        soup = self.system5.scrape_web_page(url)
        self.assertIsNotNone(soup)

if __name__ == '__main__':
    unittest.main()

