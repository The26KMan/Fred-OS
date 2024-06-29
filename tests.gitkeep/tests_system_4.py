# tests/test_system_4.py

import unittest
from sentence_transformers import SentenceTransformer
from src.context_manager import ContextManager
from src.system_4 import System4

class TestSystem4(unittest.TestCase):

    def setUp(self):
        self.nlp_model = SentenceTransformer('paraphrase-MiniLM-L6-v2')
        self.context_manager = ContextManager()
        self.system4 = System4(self.nlp_model, self.context_manager)

    def test_process_text(self):
        text = "What is quantum mechanics?"
        context = self.system4.process_text(text)
        self.assertIn("Summarized:", context)
        self.assertIn("Keywords:", context)

if __name__ == '__main__':
    unittest.main()
      
