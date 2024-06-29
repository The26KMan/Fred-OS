# tests/test_system_7.py

import unittest
from src.system_7 import System7

class TestSystem7(unittest.TestCase):

    def setUp(self):
        self.system7 = System7()

    def test_integrate_insights(self):
        insights = ["Insight 1", "Insight 2"]
        integrated_solution = self.system7.integrate_insights(insights)
        self.assertIn("Insight 1", integrated_solution)
        self.assertIn("Insight 2", integrated_solution)

if __name__ == '__main__':
    unittest.main()

