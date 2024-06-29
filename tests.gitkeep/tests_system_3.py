# tests/test_system_3.py

import unittest
from src.system_3 import System3

class TestSystem3(unittest.TestCase):

    def setUp(self):
        self.system3 = System3()

    def test_add_context(self):
        context_data = "Sample context"
        self.system3.add_context(context_data)
        self.assertIn(context_data, self.system3.get_context())

if __name__ == '__main__':
    unittest.main()

