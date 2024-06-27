# context_manager.py

class ContextManager:
    """Class to manage and cache contextual information efficiently."""
    def __init__(self):
        self.context_cache = {}
        self.lock = threading.Lock()

    def update_context(self, context_data: Any) -> None:
        with self.lock:
            context_key = hash(str(context_data))
            if context_key not in self.context_cache:
                self.context_cache[context_key] = Context()
            self.context_cache[context_key].update_context(context_data)

    def get_context(self, context_data: Any) -> 'Context':
        with self.lock:
            context_key = hash(str(context_data))
            return self.context_cache.get(context_key, None)

class Context:
    """Class to manage and share contextual information across experts and systems."""
    def __init__(self):
        self.context = {}

    def update_context(self, key: str, value: Any) -> None:
        self.context[key] = value

    def get_context(self, key: str):
        return self.context.get(key, None)
