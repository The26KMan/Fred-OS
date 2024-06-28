# System-3 The Thought Process

import concurrent.futures
from typing import List
from system_2 import Expert

class System3:
    """Processes tasks in parallel using ThreadPoolExecutor."""
    def __init__(self, experts: List[Expert]):
        self.experts = experts

    def process_tasks(self, tasks: List[str]) -> List[str]:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(expert.process, task) for expert, task in zip(self.experts, tasks)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        return results
      
