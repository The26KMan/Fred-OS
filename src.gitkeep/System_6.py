# System-6 The Knowledge Visualizer

import networkx as nx
import pandas as pd
import plotly.graph_objects as go

class InfluenceFlowerGenerator:
    def __init__(self, data):
        self.data = data
        self.graph = nx.DiGraph()

    def preprocess_data(self):
        # Preprocess the data (Placeholder)
        pass

    def compute_influence_scores(self):
        # Compute influence scores (Placeholder)
        pass

    def create_entity_graph(self):
        # Create entity graph (Placeholder)
        pass

    def generate_influence_flower(self, entity_id, file_path):
        # Generate and save influence flower visualization (Placeholder)
        pass

class System6:
    def __init__(self):
        self.knowledge_graph = nx.DiGraph()
        self.influence_flower_generator = None

    def load_academic_data(self, data):
        self.influence_flower_generator = InfluenceFlowerGenerator(data)

    def generate_influence_visualization(self, entity_id, visualization_type='Influence Flower', file_path=None):
        if visualization_type == 'Influence Flower':
            self.influence_flower_generator.generate_influence_flower(entity_id, file_path)
        elif visualization_type == 'Knowledge Graph':
            self.visualize_knowledge_graph()

    def integrate_llm_knowledge(self, llm_knowledge):
        llm_df = pd.DataFrame.from_dict(llm_knowledge, orient='index')
        llm_df['concept'] = llm_df.index
        llm_df['related_info'] = llm_df.values

        llm_data = {
            'title': llm_df['concept'].tolist(),
            'related_info': llm_df['related_info'].tolist(),
        }

        self.influence_flower_generator.data.update(llm_data)
        self.influence_flower_generator.preprocess_data()
        self.influence_flower_generator.compute_influence_scores()
        self.influence_flower_generator.create_entity_graph()

    def visualize_knowledge_graph(self):
        nx.draw(self.knowledge_graph, with_labels=True)
        plt.show()
      
