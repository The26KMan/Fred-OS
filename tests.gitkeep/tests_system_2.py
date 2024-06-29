# tests/test_system_2.py

import unittest
from src.system_2 import System2

class TestSystem2(unittest.TestCase):

    def setUp(self):
        self.system2 = System2()

    def test_process_data(self):
        data = 10
        processed_data = self.system2.process_data(data)
        self.assertEqual(processed_data, 20)

if __name__ == '__main__':
    unittest.main()
