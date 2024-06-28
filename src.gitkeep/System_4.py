# System-4 Extended Context Window

# src/system_4.py

from nltk.tokenize import word_tokenize
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
from spacy import load as spacy_load

class System4:
    def __init__(self, nlp_model, context_manager):
        self.nlp_model = nlp_model
        self.context_manager = context_manager

    async def process_text(self, text):
        tokens = word_tokenize(text)
        summarized = self.summarize_text(tokens)
        keywords = self.extract_keywords(tokens)
        context = f"Summarized: {summarized}, Keywords: {keywords}"
        self.context_manager.update_context(context)
        return context

    def summarize_text(self, tokens):
        parser = PlaintextParser.from_string(" ".join(tokens), Tokenizer("english"))
        summarizer = TextRankSummarizer()
        summary = summarizer(parser.document, 1)
        return " ".join([str(sentence) for sentence in summary])

    def extract_keywords(self, tokens):
        nlp = spacy_load("en_core_web_sm")
        doc = nlp(" ".join(tokens))
        return ", ".join([chunk.text for chunk in doc.noun_chunks])
