# tests/test_system_os.py

import unittest
from src.system_os import SystemOS

class TestSystemOS(unittest.TestCase):

    def setUp(self):
        self.system_os = SystemOS()

    def test_process_user_input(self):
        user_input = "Explain the significance of quantum tunneling in physics."
        output = self.system_os.process_user_input(user_input)
        self.assertIn("response", output)
        self.assertIn("patterns", output)
        self.assertIn("prediction", output)
        self.assertIn("problem_solution", output)
        self.assertIn("creative_solution", output)
        self.assertIn("integrated_insights", output)
        self.assertIn("freds_thoughts", output)

if __name__ == '__main__':
    unittest.main()
      
