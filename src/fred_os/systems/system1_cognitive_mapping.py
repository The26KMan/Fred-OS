"""System-1: Cognitive Mapping for Fred-OS vNext.

This module ports the System-1 design into an explicit, inspectable runtime
contract. It uses deterministic standard-library heuristics as the baseline.
A host may supply stronger NLP components upstream without changing this output
contract.

Specification: specs/systems/system1_cognitive_mapping.md
Schema: schemas/systems/system1_cognitive_mapping.schema.json
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from fred_os.runtime.contracts import SystemPlugin


class EmotionalSubtype(str, Enum):
    CURIOSITY = "curiosity"
    MYSTERY = "mystery"
    DANGER = "danger"
    WONDER = "wonder"
    ANXIETY = "anxiety"
    EXCITEMENT = "excitement"
    CONFUSION = "confusion"
    REVELATION = "revelation"
    TENSION = "tension"
    RESOLUTION = "resolution"


class ReasoningType(str, Enum):
    DIRECT = "direct"
    ANALOGICAL = "analogical"
    CROSS_DOMAIN = "cross_domain"


@dataclass(frozen=True)
class SemanticConcept:
    raw_phrase: str
    normalized_concept: str
    semantic_domain: str
    abstraction_level: int
    analogical_bridges: tuple[str, ...] = ()
    emotional_subtypes: tuple[EmotionalSubtype, ...] = ()
    cross_domain_links: Mapping[str, float] = field(default_factory=dict)
    emergence_potential: float = 0.0
    is_emergent: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["emotional_subtypes"] = [item.value for item in self.emotional_subtypes]
        result["analogical_bridges"] = list(self.analogical_bridges)
        result["cross_domain_links"] = dict(self.cross_domain_links)
        return result


@dataclass(frozen=True)
class ConceptEdge:
    source: str
    target: str
    weight: float
    reasoning_type: ReasoningType
    hops: int
    path: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "weight": round(self.weight, 4),
            "reasoning_type": self.reasoning_type.value,
            "hops": self.hops,
            "path": list(self.path),
        }


@dataclass(frozen=True)
class System1Config:
    max_concepts: int = 15
    min_phrase_chars: int = 3
    max_ngram: int = 3
    max_edges_per_node: int = 6
    emergence_threshold: float = 0.48
    target_domains: tuple[str, ...] = (
        "mathematics", "physics", "philosophy", "psychology",
        "logic", "spirituality", "general", "synthesis",
    )
    completeness_retrieval_floor: float = 0.75
    neural_overlay_enabled: bool = False

    @classmethod
    def from_runtime(cls, config: Any) -> "System1Config":
        get = config.get
        return cls(
            max_concepts=int(get("systems.s1.max_concepts", 15)),
            min_phrase_chars=int(get("systems.s1.min_phrase_chars", 3)),
            max_ngram=int(get("systems.s1.max_ngram", 3)),
            max_edges_per_node=int(get("systems.s1.max_edges_per_node", 6)),
            emergence_threshold=float(get("systems.s1.emergence_threshold", 0.48)),
            completeness_retrieval_floor=float(get("systems.s1.completeness_retrieval_floor", 0.75)),
            neural_overlay_enabled=bool(get("systems.s1.neural_overlay_enabled", False)),
        )


class DomainKnowledge:
    """Transparent lexical baseline, not a substitute for a trained model."""

    KEYWORDS: Mapping[str, tuple[str, ...]] = {
        "mathematics": ("number", "equation", "proof", "theorem", "calculation", "divide", "zero", "infinity", "limit", "singularity", "set"),
        "physics": ("quantum", "particle", "wave", "measurement", "energy", "force", "field", "superposition", "collapse", "state"),
        "philosophy": ("meaning", "existence", "reality", "truth", "knowledge", "consciousness", "ethics", "moral", "ontology", "paradox"),
        "psychology": ("emotion", "behavior", "cognition", "perception", "memory", "anxiety", "attention", "learning", "identity"),
        "logic": ("reasoning", "inference", "deduction", "argument", "validity", "contradiction", "constraint", "governance", "evidence"),
        "spirituality": ("transcendence", "meaning", "purpose", "sacred", "wisdom", "enlightenment", "faith", "spiritual"),
    }
    BRIDGES: Mapping[str, tuple[str, ...]] = {
        "superposition": ("ambiguity", "multiple meanings", "potential states"),
        "measurement": ("observation", "collapse", "decision"),
        "wave": ("probability", "signal", "pattern"),
        "undefined": ("liminal", "boundary", "threshold"),
        "memory": ("continuity", "retrieval", "identity"),
        "semantic": ("meaning", "interpretation", "context"),
        "deeplink": ("provenance", "evidence", "traceability"),
        "governance": ("constraint", "ethics", "oversight"),
    }
    EMOTIONS: Mapping[EmotionalSubtype, tuple[str, ...]] = {
        EmotionalSubtype.CURIOSITY: ("wonder", "question", "explore", "why", "how"),
        EmotionalSubtype.MYSTERY: ("unknown", "hidden", "secret", "liminal"),
        EmotionalSubtype.DANGER: ("risk", "warning", "threat", "unsafe"),
        EmotionalSubtype.WONDER: ("amazing", "remarkable", "fascinating"),
        EmotionalSubtype.ANXIETY: ("worry", "fear", "uncertain", "unstable"),
        EmotionalSubtype.EXCITEMENT: ("thrilling", "dynamic", "energetic"),
        EmotionalSubtype.CONFUSION: ("unclear", "ambiguous", "paradox"),
        EmotionalSubtype.REVELATION: ("discovery", "insight", "realization"),
        EmotionalSubtype.TENSION: ("conflict", "opposition", "struggle"),
        EmotionalSubtype.RESOLUTION: ("answer", "solution", "clarity"),
    }
    DOMAIN_PRIORS: Mapping[str, Mapping[str, float]] = {
        "mathematics": {"physics": 0.65, "logic": 0.72, "philosophy": 0.22},
        "physics": {"mathematics": 0.65, "philosophy": 0.30, "logic": 0.28},
        "philosophy": {"logic": 0.56, "spirituality": 0.48, "psychology": 0.35},
        "psychology": {"philosophy": 0.35, "spirituality": 0.25, "logic": 0.20},
        "logic": {"mathematics": 0.72, "philosophy": 0.56, "general": 0.35},
        "spirituality": {"philosophy": 0.48, "psychology": 0.25, "general": 0.25},
        "general": {"logic": 0.35, "philosophy": 0.20},
    }
    ALIASES: Mapping[str, str] = {
        "deep links": "deeplink provenance",
        "deep link": "deeplink provenance",
        "memory lake": "semantic memory lake",
        "system os": "system-os",
        "system-os": "system-os",
    }

    @classmethod
    def classify(cls, phrase: str) -> str:
        lower = phrase.lower()
        scores = {domain: sum(1 for key in keys if re.search(rf"\b{re.escape(key)}\b", lower)) for domain, keys in cls.KEYWORDS.items()}
        best_domain, best_score = max(scores.items(), key=lambda item: item[1])
        return best_domain if best_score else "general"

    @classmethod
    def bridges(cls, phrase: str) -> tuple[str, ...]:
        lower = phrase.lower().replace("-", "")
        found: list[str] = []
        for key, values in cls.BRIDGES.items():
            if key in lower:
                found.extend(values)
        return tuple(dict.fromkeys(found))[:3]

    @classmethod
    def emotions(cls, phrase: str, context: str) -> tuple[EmotionalSubtype, ...]:
        haystack = f"{phrase} {context}".lower()
        hits = [emotion for emotion, keywords in cls.EMOTIONS.items() if any(re.search(rf"\b{re.escape(keyword)}\b", haystack) for keyword in keywords)]
        return tuple(hits[:2])


class CognitiveMapper:
    """Deterministic semantic graph mapper with explicit uncertainty reporting."""

    STOPWORDS = frozenset({"the", "and", "for", "that", "with", "this", "from", "into", "about", "what", "when", "where", "which", "while", "have", "will", "would", "could", "should", "their", "there", "then", "than", "them", "they", "your", "ours", "are", "was", "were", "been", "being", "not", "but", "can", "how", "use", "using", "through", "between", "across", "under"})
    VERBS = frozenset({"build", "create", "use", "connect", "preserve", "maintain", "scale", "map", "retrieve", "store", "govern", "validate", "compare", "explain", "improve", "migrate", "design", "protect", "resolve"})

    def __init__(self, config: System1Config | None = None) -> None:
        self.config = config or System1Config()

    def process(self, text: str, *, context: Sequence[str] = (), enable_emergence: bool = True) -> dict[str, Any]:
        if not isinstance(text, str):
            raise TypeError("System-1 expects text as a string")
        phrases = self.extract_concepts(text)
        concepts: list[SemanticConcept] = []
        seen: set[str] = set()
        for phrase in phrases:
            concept = self.normalize_concept(phrase, " ".join(context))
            if concept.normalized_concept not in seen:
                seen.add(concept.normalized_concept)
                concepts.append(concept)
        edges = self.find_connections(concepts)
        emergent = self.generate_emergent(concepts) if enable_emergence else []
        metrics = self.calculate_metrics(concepts, edges, emergent)
        facets = self.facet_coverage(text, concepts)
        kpi = self.kpi_signals(concepts, metrics, facets)
        uncertainty = self.uncertainty(concepts, metrics, facets)
        graph = self.build_graph(concepts, edges, emergent)
        return {
            "enriched_concepts": [item.to_dict() for item in concepts],
            "multi_hop_connections": [item.to_dict() for item in edges],
            "emergent_concepts": [item.to_dict() for item in emergent],
            "cognitive_graph": graph,
            "insight_metrics": metrics,
            "kpi_signals": kpi,
            "uncertainty": uncertainty,
            "svo_triples": self.extract_svo_heuristic(text),
            "mermaid": self.to_mermaid(graph),
            "metadata": {"text_length": len(text), "concepts_extracted": len(concepts), "connections_found": len(edges), "emergent_generated": len(emergent), "extractor": "deterministic_lexical_baseline"},
        }

    def extract_concepts(self, text: str) -> list[str]:
        tokens = [match.group(0).lower() for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_-]*", text) if len(match.group(0)) >= self.config.min_phrase_chars]
        tokens = [token for token in tokens if token not in self.STOPWORDS]
        if not tokens:
            return []
        counts: Counter[str] = Counter()
        first_index: dict[str, int] = {}
        for width in range(1, self.config.max_ngram + 1):
            for index in range(0, len(tokens) - width + 1):
                phrase = " ".join(tokens[index:index + width])
                if len(phrase) >= self.config.min_phrase_chars:
                    counts[phrase] += 1
                    first_index.setdefault(phrase, index)
        lower = text.lower()
        for phrase in ("semantic memory", "memory lake", "system-os", "deep links", "ethical governance", "cognitive mapping", "knowledge graph", "subject verb object", "coreference resolution", "fuzzy cognitive maps"):
            if phrase in lower:
                counts[phrase] += 2
                first_index.setdefault(phrase, lower.index(phrase))
        ranked = []
        for phrase, frequency in counts.items():
            domain_bonus = 1.2 if DomainKnowledge.classify(phrase) != "general" else 0.0
            score = frequency + len(DomainKnowledge.bridges(phrase)) * 0.8 + domain_bonus + min(0.8, 0.2 * (len(phrase.split()) - 1))
            ranked.append((phrase, first_index[phrase], score))
        ranked.sort(key=lambda row: (-row[2], row[1], -len(row[0])))
        selected: list[str] = []
        for phrase, _, _ in ranked:
            if any(phrase in item.split() and DomainKnowledge.classify(phrase) == DomainKnowledge.classify(item) for item in selected):
                continue
            selected.append(phrase)
            if len(selected) >= self.config.max_concepts:
                break
        return selected

    def normalize_concept(self, phrase: str, context: str = "") -> SemanticConcept:
        canonical = DomainKnowledge.ALIASES.get(phrase.lower().strip(), phrase.lower().strip())
        domain = DomainKnowledge.classify(canonical)
        bridges = DomainKnowledge.bridges(canonical)
        emotions = DomainKnowledge.emotions(canonical, context)
        abstraction = min(5, max(0, round(max(1, len(canonical.split())) - 1 + (0.8 if domain in {"philosophy", "logic", "spirituality"} else 0.4))))
        emergence = min(1.0, 0.18 + 0.13 * len(bridges) + 0.08 * len(emotions) + 0.07 * abstraction + (0.16 if any(marker in canonical for marker in ("paradox", "undefined", "liminal", "ambiguity")) else 0.0))
        return SemanticConcept(phrase, canonical, domain, abstraction, bridges, emotions, dict(DomainKnowledge.DOMAIN_PRIORS.get(domain, {})), round(emergence, 4))

    def find_connections(self, concepts: Sequence[SemanticConcept]) -> list[ConceptEdge]:
        results: list[ConceptEdge] = []
        for index, left in enumerate(concepts):
            created = 0
            for right in concepts[index + 1:]:
                edge = self._edge_between(left, right)
                if edge:
                    results.append(edge)
                    created += 1
                    if created >= self.config.max_edges_per_node:
                        break
        return sorted(results, key=lambda item: item.weight, reverse=True)

    @staticmethod
    def _similarity(left: SemanticConcept, right: SemanticConcept) -> float:
        return 1.0 - abs(left.abstraction_level - right.abstraction_level) / 5.0

    def _edge_between(self, left: SemanticConcept, right: SemanticConcept) -> ConceptEdge | None:
        similarity = self._similarity(left, right)
        emotions = len(set(left.emotional_subtypes) & set(right.emotional_subtypes))
        if left.semantic_domain == right.semantic_domain:
            return ConceptEdge(left.normalized_concept, right.normalized_concept, min(1.0, 0.46 + 0.34 * similarity + 0.08 * emotions), ReasoningType.DIRECT, 1, (left.normalized_concept, right.normalized_concept))
        bridges = tuple(sorted(set(left.analogical_bridges) & set(right.analogical_bridges)))
        if bridges:
            return ConceptEdge(left.normalized_concept, right.normalized_concept, min(1.0, 0.38 + 0.30 * similarity + 0.12 * len(bridges)), ReasoningType.ANALOGICAL, 2, (left.normalized_concept, bridges[0], right.normalized_concept))
        prior = max(float(left.cross_domain_links.get(right.semantic_domain, 0.0)), float(right.cross_domain_links.get(left.semantic_domain, 0.0)))
        if prior or emotions:
            return ConceptEdge(left.normalized_concept, right.normalized_concept, min(1.0, 0.20 + 0.48 * prior + 0.20 * similarity + 0.05 * emotions), ReasoningType.CROSS_DOMAIN, 2, (left.normalized_concept, f"domain:{right.semantic_domain}", right.normalized_concept))
        return None

    def generate_emergent(self, concepts: Sequence[SemanticConcept]) -> list[SemanticConcept]:
        result: list[SemanticConcept] = []
        seen: set[str] = set()
        for concept in concepts:
            if concept.emergence_potential >= self.config.emergence_threshold:
                for bridge in concept.analogical_bridges:
                    label = f"{concept.semantic_domain}–{bridge} bridge"
                    if label not in seen:
                        seen.add(label)
                        result.append(SemanticConcept(label, label, "synthesis", min(5, concept.abstraction_level + 1), (bridge,), (), {}, round(concept.emergence_potential * 0.80, 4), True))
        domains = list(dict.fromkeys(item.semantic_domain for item in concepts if item.semantic_domain != "general"))
        for index, left in enumerate(domains):
            for right in domains[index + 1:]:
                label = f"{left}–{right} synthesis"
                if label not in seen:
                    seen.add(label)
                    result.append(SemanticConcept(label, label, "synthesis", 4, (left, right), (), {}, 0.60, True))
        return result[:5]

    def calculate_metrics(self, concepts: Sequence[SemanticConcept], edges: Sequence[ConceptEdge], emergent: Sequence[SemanticConcept]) -> dict[str, Any]:
        nodes = list(concepts) + list(emergent)
        if not nodes:
            return {"insight_score": 0.0, "domain_diversity": 0, "domain_completeness": 0.0, "cross_domain_connections": 0, "emergent_concept_count": 0, "abstraction_diversity": 0.0, "multi_hop_density": 0.0}
        domains = {item.semantic_domain for item in concepts}
        completeness = min(1.0, len(domains) / len(self.config.target_domains))
        cross = sum(1 for edge in edges if edge.reasoning_type == ReasoningType.CROSS_DOMAIN)
        possible = max(1, len(concepts) * (len(concepts) - 1) // 2)
        cross_density = cross / possible
        abstraction = len({item.abstraction_level for item in nodes}) / 6.0
        multi_hop = sum(1 for edge in edges if edge.hops > 1) / max(1, len(edges))
        insight = min(1.0, 0.25 * completeness + 0.25 * min(1.0, cross_density * 3) + 0.20 * min(1.0, len(emergent) / 5) + 0.15 * abstraction + 0.15 * multi_hop)
        return {"insight_score": round(insight, 4), "domain_diversity": len(domains), "domain_completeness": round(completeness, 4), "cross_domain_connections": cross, "emergent_concept_count": len(emergent), "abstraction_diversity": round(abstraction, 4), "multi_hop_density": round(multi_hop, 4)}

    def facet_coverage(self, text: str, concepts: Sequence[SemanticConcept]) -> dict[str, list[str]]:
        lower = text.lower()
        if any(marker in lower for marker in ("how ", "how can", "steps", "implement", "build", "migrate")):
            required = ["procedural_steps", "success_criteria", "prerequisites", "validation_methods"]
        elif any(marker in lower for marker in ("compare", "versus", "vs ", "difference")):
            required = ["comparative_dimensions", "contrast_points", "trade_offs", "decision_criteria"]
        else:
            required = ["formal_definition", "examples", "analogies", "practical_applications"]
        if any(marker in lower for marker in ("system-os", "system os", "architecture", "runtime")):
            required = list(dict.fromkeys(required + ["integration_contracts", "evidence_provenance"]))
        signals = {"procedural_steps": ("step", "process", "implement", "build", "migrate"), "success_criteria": ("success", "outcome", "goal", "result"), "prerequisites": ("require", "dependency", "need", "before"), "validation_methods": ("test", "validate", "verify", "audit"), "comparative_dimensions": ("compare", "dimension", "feature"), "contrast_points": ("difference", "contrast", "versus"), "trade_offs": ("trade", "cost", "risk", "benefit"), "decision_criteria": ("criteria", "choose", "decision"), "formal_definition": ("what", "definition", "meaning", "is"), "examples": ("example", "instance", "such"), "analogies": ("like", "analogy", "bridge", "similar"), "practical_applications": ("use", "apply", "build", "implement"), "integration_contracts": ("integration", "contract", "interface", "system"), "evidence_provenance": ("evidence", "source", "provenance", "deeplink")}
        mapped = " ".join(item.normalized_concept for item in concepts)
        covered = [facet for facet in required if any(word in lower or word in mapped for word in signals[facet])]
        return {"required_facets": required, "covered_facets": covered, "missing_facets": [facet for facet in required if facet not in covered]}

    def kpi_signals(self, concepts: Sequence[SemanticConcept], metrics: Mapping[str, Any], facets: Mapping[str, Sequence[str]]) -> dict[str, Any]:
        completeness = float(metrics["domain_completeness"])
        return {"completeness_contribution": round(completeness, 4), "trajectory_fit_contribution": round(min(1.0, 0.20 * float(metrics["insight_score"])), 4), "facet_completeness": round(len(facets["covered_facets"]) / max(1, len(facets["required_facets"])), 4), "required_facets": list(facets["required_facets"]), "covered_facets": list(facets["covered_facets"]), "missing_facets": list(facets["missing_facets"]), "domains_covered": sorted({item.semantic_domain for item in concepts}), "retrieval_recommendation": "retrieve_increase_completeness" if completeness < self.config.completeness_retrieval_floor else "continue"}

    def uncertainty(self, concepts: Sequence[SemanticConcept], metrics: Mapping[str, Any], facets: Mapping[str, Sequence[str]]) -> dict[str, Any]:
        if not concepts:
            return {"score": 1.0, "drivers": {"knowledge_gaps": 1.0, "ambiguity_level": 0.0, "complexity": 0.0, "context_dependency": 0.0}, "gaps": ["No concepts were extracted; require clarification or a broader upstream parser."]}
        emergence = sum(item.emergence_potential for item in concepts) / len(concepts)
        abstraction = sum(item.abstraction_level for item in concepts) / len(concepts)
        links = sum(len(item.cross_domain_links) for item in concepts)
        gaps = 1.0 - float(metrics["domain_completeness"])
        facet_gaps = len(facets["missing_facets"]) / max(1, len(facets["required_facets"]))
        drivers = {"knowledge_gaps": round(gaps, 4), "ambiguity_level": round(emergence, 4), "complexity": round(abstraction / 5.0, 4), "context_dependency": round(min(1.0, links / max(1, len(concepts) * 2)), 4), "facet_gaps": round(facet_gaps, 4)}
        score = min(1.0, 0.36 * drivers["knowledge_gaps"] + 0.25 * drivers["ambiguity_level"] + 0.19 * drivers["complexity"] + 0.20 * drivers["facet_gaps"])
        gaps_list = [f"Missing facet: {item}" for item in facets["missing_facets"]]
        return {"score": round(score, 4), "drivers": drivers, "gaps": gaps_list}

    @staticmethod
    def build_graph(concepts: Sequence[SemanticConcept], edges: Sequence[ConceptEdge], emergent: Sequence[SemanticConcept]) -> dict[str, Any]:
        return {"nodes": [item.to_dict() for item in list(concepts) + list(emergent)], "edges": [item.to_dict() for item in edges]}

    @staticmethod
    def to_mermaid(graph: Mapping[str, Any]) -> str:
        lines = ["graph TD"]
        ids: dict[str, str] = {}
        for index, node in enumerate(graph.get("nodes", [])):
            node_id = f"N{index}"
            ids[node["normalized_concept"]] = node_id
            lines.append(f'    {node_id}["{str(node["normalized_concept"]).replace(chr(34), chr(39))[:72]}"]')
        for edge in graph.get("edges", []):
            if edge["source"] in ids and edge["target"] in ids:
                lines.append(f'    {ids[edge["source"]]} -->|{edge["reasoning_type"]}:{edge["weight"]:.2f}| {ids[edge["target"]]}')
        return "\n".join(lines)

    @classmethod
    def extract_svo_heuristic(cls, text: str) -> list[dict[str, str]]:
        triples: list[dict[str, str]] = []
        for sentence in re.split(r"[.!?]+", text):
            words = [match.group(0) for match in re.finditer(r"[A-Za-z][A-Za-z_-]*", sentence)]
            for verb_index, word in enumerate(words):
                if word.lower() not in cls.VERBS:
                    continue
                subject = next((item for item in reversed(words[:verb_index]) if item.lower() not in cls.STOPWORDS), "")
                obj = next((item for item in words[verb_index + 1:] if item.lower() not in cls.STOPWORDS), "")
                if subject and obj:
                    triples.append({"subject": subject, "verb": word, "object": obj, "method": "heuristic"})
        return triples[:8]


class System1CognitiveMappingPlugin(SystemPlugin):
    """Registry adapter that preserves System-1 outputs for downstream systems."""

    SYSTEM_ID = "S1"
    SYSTEM_NAME = "Cognitive Mapping"

    def initialize(self) -> None:
        self.mapper = CognitiveMapper(System1Config.from_runtime(self.config))
        self.overlay = None
        if self.mapper.config.neural_overlay_enabled:
            from .system1_neural_overlay import System1NeuralOverlay
            self.overlay = System1NeuralOverlay()
        super().initialize()

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", ""))
        result = self.mapper.process(text, context=tuple(payload.get("context", ())))
        lower = text.lower()
        task_class = "systemic" if any(word in lower for word in ("build", "design", "implement", "migrate", "architecture", "runtime")) else "creative" if any(word in lower for word in ("feel", "relationship", "grief", "creative", "art")) else "general"
        memory_hits: list[dict[str, Any]] = []
        memory = context.get("memory")
        if memory is not None and hasattr(memory, "recall"):
            try:
                memory_hits = list(getattr(memory.recall(text, limit=3), "hits", []))
            except Exception as exc:
                memory_hits = [{"status": "unavailable", "reason": str(exc)}]
        if self.overlay is not None:
            result["neural_telemetry"] = self.overlay.update(kpi_signals=result["kpi_signals"], uncertainty=result["uncertainty"])
        result.update({"system_id": self.SYSTEM_ID, "entities": [item["normalized_concept"] for item in result["enriched_concepts"]], "task_class": task_class, "memory_context": memory_hits, "memory_write_candidate": {"status": "candidate_only", "reason": "System-1 does not persist inferred facts without an explicit governance-approved write."}})
        return result
