# tests/test_system_6.py

import unittest
from src.system_6 import System6

class TestSystem6(unittest.TestCase):

    def setUp(self):
        self.system6 = System6()

    def test_generate_creative_solution(self):
        problem = "How to reduce carbon emissions?"
        solution = self.system6.generate_creative_solution(problem)
        self.assertIn("Creative approach", solution)

if __name__ == '__main__':
    unittest.main()

