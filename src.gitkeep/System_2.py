# System-2 The Brain


from context_manager import ContextManager
from typing import Any, List

class Expert:
    """Abstract base class for experts."""
    def process(self, input_data: Any) -> Any:
        raise NotImplementedError

class TaskUnderstandingExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        task_analysis = f"Task analysis for '{input_data}': Improve productivity by identifying and addressing time-wasting activities, prioritizing tasks, and optimizing work processes."
        self.context_manager.update_context(task_analysis)
        return task_analysis

class CompetencyMappingExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        competency_mapping = f"Competency mapping for '{input_data}': Time management, task prioritization, process optimization, productivity tools."
        self.context_manager.update_context(competency_mapping)
        return competency_mapping

class IntegrationAndSynthesisExpert(Expert):
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager

    def process(self, input_data: str) -> str:
        integrated_output = f"Integrated output for '{input_data}': To improve productivity, analyze time-wasting activities and prioritize tasks based on importance and deadlines. Implement productivity tools and optimize processes to streamline work. Focus on high-impact tasks and eliminate distractions."
        self.context_manager.update_context(integrated_output)
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
      
