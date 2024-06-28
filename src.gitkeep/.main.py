# Main.py

from system_2 import System2, TaskUnderstandingExpert, CompetencyMappingExpert, IntegrationAndSynthesisExpert
from system_3 import System3
from system_4 import System4
from system_5 import System5
from system_6 import System6
from system_7 import System7
from system_8 import EthicalEvaluationModel
from context_manager import ContextManager

def main():
    context_manager = ContextManager()

    # Initialize experts and systems
    task_expert = TaskUnderstandingExpert(context_manager)
    competency_expert = CompetencyMappingExpert(context_manager)
    integration_expert = IntegrationAndSynthesisExpert(context_manager)
    experts = [task_expert, competency_expert, integration_expert]
    system2 = System2(experts)
    system3 = System3(experts)
    system4 = System4(context_manager)
    system6 = System6()
    system7 = System7(context_manager)

    # Example usage
    user_input = "How can I improve my productivity?"
    response2 = system2.generate_response(user_input)
    response3 = system3.process_tasks([user_input])
    response4 = system4.process_text(user_input)
    
    # Print responses
    print(response2)
    print(response3)
    print(response4)

if __name__ == "__main__":
    main()

