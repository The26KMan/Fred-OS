# System-4 Extended Context Window

from context_manager import ContextManager
from typing import List
from nltk.tokenize import word_tokenize
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
import spacy

class System4:
    """Context Extension System."""
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager
        self.nlp = spacy.load("en_core_web_sm")

    def process_text(self, text: str) -> str:
        tokens = word_tokenize(text)
        summarized = self.summarize_text(tokens)
        keywords = self.extract_keywords(tokens)
        context = f"Summarized: {summarized}, Keywords: {keywords}"
        self.context_manager.update_context(context)
        return context

    def summarize_text(self, tokens: List[str]) -> str:
        parser = PlaintextParser.from_string(" ".join(tokens), Tokenizer("english"))
        summarizer = TextRankSummarizer()
        summary = summarizer(parser.document, 1)
        return " ".join([str(sentence) for sentence in summary])

    def extract_keywords(self, tokens: List[str]) -> str:
        doc = self.nlp(" ".join(tokens))
        return ", ".join([chunk.text for chunk in doc.noun_chunks])
      
