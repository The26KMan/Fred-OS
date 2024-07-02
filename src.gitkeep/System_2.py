# System-2 The Brain

from context_manager import ContextManager
from typing import Any, List

class ContextManager:
    """Class to manage and cache contextual information efficiently."""
    def __init__(self):
        self.context_cache = {}
        self.lock = threading.Lock()

    def update_context(self, context_key: str, context_data: Any) -> None:
        with self.lock:
            if context_key not in self.context_cache:
                self.context_cache[context_key] = Context()
            self.context_cache[context_key].update_context(context_key, context_data)

    def get_context(self, context_key: str) -> 'Context':
        with self.lock:
            return self.context_cache.get(context_key, None)

class Context:
    """Class to manage and share contextual information across experts and systems."""
    def __init__(self):
        self.context = {}

    def update_context(self, key: str, value: Any) -> None:
        self.context[key] = value

    def get_context(self, key: str):
        return self.context.get(key, None)

class Expert:
    """Abstract base class for experts."""
    def process(self, input_data: Any) -> Any:
        raise NotImplementedError

class TaskUnderstandingExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        task_analysis = f"Task analysis for '{input_data}': Improve productivity by identifying and addressing time-wasting activities, prioritizing tasks, and optimizing work processes."
        self.context_manager.update_context('task_analysis', task_analysis)
        return task_analysis

class CompetencyMappingExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        competency_mapping = f"Competency mapping for '{input_data}': Time management, task prioritization, process optimization, productivity tools."
        self.context_manager.update_context('competency_mapping', competency_mapping)
        return competency_mapping

class IntegrationAndSynthesisExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        integrated_output = f"Integrated output for '{input_data}': To improve productivity, analyze time-wasting activities and prioritize tasks based on importance and deadlines. Implement productivity tools and optimize processes to streamline work. Focus on high-impact tasks and eliminate distractions."
        self.context_manager.update_context('integrated_output', integrated_output)
        return integrated_output

class System2:
    """Handles response generation and resource management."""
    def __init__(self, experts: List[Expert]):
        self.experts = experts

    def generate_response(self, input_data: str) -> str:
        outputs = [expert.process(input_data) for expert in self.experts]
        response = self.combine_outputs(outputs)
        return response

    def combine_outputs(self, outputs: List[str]) -> str:
        return " ".join(outputs)

# Run a simple test
context_manager = ContextManager()
experts = [TaskUnderstandingExpert(context_manager), CompetencyMappingExpert(context_manager), IntegrationAndSynthesisExpert(context_manager)]
system2 = System2(experts)

input_data = "improve productivity"
response = system2.generate_response(input_data)
response
