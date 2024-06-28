# Memory Module

from typing import Any, Optional
from context_manager import ContextManager  # Importing ContextManager if it's used

class MemoryModule:
    """Class to manage memory storage and retrieval."""
    def __init__(self, persistence_file: Optional[str] = None):
        self.memory = {}
        self.persistence_file = persistence_file

    def store_memory(self, key: str, value: Any) -> None:
        self.memory[key] = value
        self._persist_memory()

    def retrieve_memory(self, key: str) -> Any:
        return self.memory.get(key, None)

    def search_memory(self, query: str) -> list:
        return [key for key in self.memory if query in key]

    def _persist_memory(self) -> None:
        if self.persistence_file:
            with open(self.persistence_file, 'w') as file:
                file.write(str(self.memory))

class EnhancedMemoryModule(MemoryModule):
    def __init__(self, persistence_file: Optional[str] = None):
        super().__init__(persistence_file)

    def store_memory(self, key: str, value: Any, context: Optional[str] = None) -> None:
        super().store_memory(key, value)

    def retrieve_memory(self, key: str) -> Any:
        return super().retrieve_memory(key)
      
