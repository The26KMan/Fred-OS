"""Run System-1 directly and print an inspectable map plus Mermaid text."""
from fred_os.systems.system1_cognitive_mapping import CognitiveMapper


PROMPT = """
How can System-OS use a Semantic Memory Lake and immutable DeepLinks to preserve
provenance, connect architecture decisions over time, and maintain ethical
governance while its runtime scales?
"""


if __name__ == "__main__":
    result = CognitiveMapper().process(PROMPT)
    print("KPI:", result["kpi_signals"])
    print("Uncertainty:", result["uncertainty"])
    print("Concepts:")
    for concept in result["enriched_concepts"][:8]:
        print(f"- {concept['normalized_concept']} [{concept['semantic_domain']}]")
    print("\nMermaid:\n")
    print(result["mermaid"])
