"""System-1 runtime adapter: semantic mapping plus situation/temporal signals.

The semantic graph engine remains in `system1_cognitive_mapping.py`. This
adapter adds the System-OS situation model required by TSC and downstream
routing: entities, objectives, constraints, questions, temporal references,
gaps, ambiguity, and turn-state signals.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from fred_os.runtime.contracts import SystemPlugin
from .system1_cognitive_mapping import CognitiveMapper, System1Config


class SituationalLayer:
    DATE = re.compile(r"\b(?:\d{4}-\d{1,2}-\d{1,2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2}(?:,?\s+\d{4})?|today|tomorrow|yesterday|tonight|this\s+(?:week|month|year)|next\s+(?:week|month|year))\b", re.I)
    EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    URL = re.compile(r"https?://[^\s]+")
    NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
    PROPER = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
    QUESTION_STARTERS = ("what", "how", "why", "when", "where", "who", "which", "can", "could", "should", "would")
    OBJECTIVE_WORDS = {"goal", "objective", "deliver", "prototype", "draft", "build", "design", "plan", "summarize", "analyze", "cite", "migrate", "implement", "create"}
    CONSTRAINT_PATTERNS = (
        r"\bmust\b[^.,;!?]{0,100}", r"\bshould\b[^.,;!?]{0,100}", r"\brequired?\b[^.,;!?]{0,100}",
        r"\bby\s+(?:\w+\s+)?\d{1,2}(?:,?\s+\d{4})?", r"\bdeadline\b[^.,;!?]{0,100}",
        r"\binclude\b[^.,;!?]{0,100}", r"\bno\s+more\s+than\b[^.,;!?]{0,60}",
    )
    POSITIVE_CONSTRAINT = re.compile(r"\b(?:must|should|required\s+to)\s+(?:include|use|enable|keep|retain)\s+(.+)$", re.I)
    NEGATIVE_CONSTRAINT = re.compile(r"\b(?:must|should)\s+not\s+(?:include|use|enable|keep|retain)\s+(.+)$", re.I)
    EXCLUSION_CONSTRAINT = re.compile(r"\b(?:must|should)\s+(?:exclude|omit|disable|remove)\s+(.+)$", re.I)

    def build(self, text: str, semantic: Mapping[str, Any], temporal: Any | None = None) -> dict[str, Any]:
        entities = {
            "proper_nouns": sorted(set(self.PROPER.findall(text))),
            "dates": sorted(set(self.DATE.findall(text))),
            "emails": sorted(set(self.EMAIL.findall(text))),
            "urls": sorted(set(self.URL.findall(text))),
            "numbers": sorted(set(self.NUMBER.findall(text))),
            "concept_nodes": [item.get("normalized_concept", "") for item in semantic.get("enriched_concepts", []) if isinstance(item, Mapping)],
        }
        constraints = sorted({match.group(0).strip() for pattern in self.CONSTRAINT_PATTERNS for match in re.finditer(pattern, text, flags=re.I)})
        ambiguities = self._ambiguities(constraints)
        tokens = {item.lower() for item in re.findall(r"[A-Za-z][A-Za-z_-]*", text)}
        objectives = sorted(tokens & self.OBJECTIVE_WORDS)
        questions = [text.strip()] if "?" in text or text.strip().lower().startswith(self.QUESTION_STARTERS) else []
        temporal_refs = entities["dates"]
        state = self._state(questions, constraints, objectives)
        gaps = self._gaps(constraints, objectives, entities, semantic)
        for ambiguity in ambiguities:
            gaps.append({"type": ambiguity["type"], "reason": ambiguity["reason"]})
        uncertainty = self._uncertainty(semantic, questions, entities, gaps)
        signals = {
            "uncertainty": uncertainty["score"],
            "commit_tokens": bool(entities["dates"] or entities["numbers"] or constraints),
            "sensitive_flags": any(flag in text.lower() for flag in ("privacy", "legal", "medical", "financial", "deadline", "housing")),
        }
        turn_id = getattr(temporal, "current_turn", 0) + 1 if temporal is not None else None
        return {
            "entities": entities,
            "objectives": objectives,
            "constraints": constraints,
            "ambiguities": ambiguities,
            "open_questions": questions,
            "temporal_refs": temporal_refs,
            "temporal_state": state,
            "turn_id": turn_id,
            "gaps": gaps,
            "signals": signals,
            "uncertainty": uncertainty,
        }

    @classmethod
    def _ambiguities(cls, constraints: list[str]) -> list[dict[str, str]]:
        positive: dict[str, str] = {}
        negative: dict[str, str] = {}

        def normalize_target(value: str) -> str:
            return " ".join(re.findall(r"[A-Za-z0-9_-]+", value.lower())).strip()

        for constraint in constraints:
            negative_match = cls.NEGATIVE_CONSTRAINT.search(constraint) or cls.EXCLUSION_CONSTRAINT.search(constraint)
            if negative_match:
                target = normalize_target(negative_match.group(1))
                if target:
                    negative[target] = constraint
                continue
            positive_match = cls.POSITIVE_CONSTRAINT.search(constraint)
            if positive_match:
                target = normalize_target(positive_match.group(1))
                if target:
                    positive[target] = constraint

        ambiguities: list[dict[str, str]] = []
        for target in sorted(set(positive).intersection(negative)):
            ambiguities.append({
                "type": "contradictory_constraint",
                "target": target,
                "positive": positive[target],
                "negative": negative[target],
                "reason": f"Conflicting constraints both require and prohibit '{target}'.",
            })
        return ambiguities

    @staticmethod
    def _state(questions: list[str], constraints: list[str], objectives: list[str]) -> str:
        if questions:
            return "ask"
        if constraints:
            return "constrain"
        if objectives:
            return "decide"
        return "state"

    @staticmethod
    def _gaps(constraints: list[str], objectives: list[str], entities: Mapping[str, list[str]], semantic: Mapping[str, Any]) -> list[dict[str, str]]:
        gaps: list[dict[str, str]] = []
        lower_constraints = " ".join(constraints).lower()
        if any("deadline" in item or item.startswith("by ") for item in lower_constraints.split(" | ")) and not entities.get("dates"):
            gaps.append({"type": "deadline_missing_date", "reason": "deadline language has no recognized date"})
        if objectives and not constraints:
            gaps.append({"type": "unbounded_objectives", "reason": "objectives were detected without explicit constraints or success criteria"})
        missing = list(semantic.get("kpi_signals", {}).get("missing_facets", []))
        for facet in missing[:4]:
            gaps.append({"type": "missing_facet", "reason": str(facet)})
        return gaps

    @staticmethod
    def _uncertainty(semantic: Mapping[str, Any], questions: list[str], entities: Mapping[str, list[str]], gaps: list[Mapping[str, str]]) -> dict[str, Any]:
        previous = dict(semantic.get("uncertainty", {}))
        base = float(previous.get("score", 1.0))
        grounding = min(0.25, 0.04 * len(entities.get("proper_nouns", [])) + 0.06 * len(entities.get("dates", [])) + 0.03 * len(entities.get("numbers", [])))
        score = max(0.0, min(1.0, 0.72 * base + (0.12 if questions else 0.0) + 0.06 * len(gaps) - grounding))
        drivers = dict(previous.get("drivers", {}))
        drivers.update({"situational_questions": len(questions), "situational_gaps": len(gaps), "grounding_signals": round(grounding, 4)})
        return {"score": round(score, 4), "drivers": drivers, "gaps": list(previous.get("gaps", [])) + [item["reason"] for item in gaps]}


class System1RuntimeAdapter(SystemPlugin):
    SYSTEM_ID = "S1"
    SYSTEM_NAME = "Cognitive Mapping"

    def initialize(self) -> None:
        self.mapper = CognitiveMapper(System1Config.from_runtime(self.config))
        self.situational = SituationalLayer()
        self.overlay = None
        if self.mapper.config.neural_overlay_enabled:
            from .system1_neural_overlay import System1NeuralOverlay
            self.overlay = System1NeuralOverlay()
        super().initialize()

    def process(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text", ""))
        temporal = context.get("temporal")
        temporal_packet = temporal.context_packet(text) if temporal is not None and hasattr(temporal, "context_packet") else {}
        context_text = [item.get("content", "") for item in temporal_packet.get("working_cues", []) + temporal_packet.get("contextual_cues", [])]
        context_text.extend(str(item) for item in payload.get("context", ()))
        result = self.mapper.process(text, context=tuple(context_text))
        situation = self.situational.build(text, result, temporal)
        result["context_graph"] = {key: situation[key] for key in ("entities", "objectives", "constraints", "ambiguities", "open_questions", "temporal_refs", "temporal_state", "turn_id")}
        result["temporal_state"] = situation["temporal_state"]
        result["gaps"] = situation["gaps"]
        result["signals"] = situation["signals"]
        result["uncertainty"] = situation["uncertainty"]
        memory_hits: list[dict[str, Any]] = []
        memory = context.get("memory")
        if memory is not None and hasattr(memory, "recall"):
            try:
                memory_hits = list(getattr(memory.recall(text, limit=3), "hits", []))
            except Exception as exc:
                memory_hits = [{"status": "unavailable", "reason": str(exc)}]
        lower = text.lower()
        task_class = "systemic" if any(word in lower for word in ("build", "design", "implement", "migrate", "architecture", "runtime")) else "creative" if any(word in lower for word in ("feel", "relationship", "grief", "creative", "art")) else "general"
        if self.overlay is not None:
            result["neural_telemetry"] = self.overlay.update(kpi_signals=result["kpi_signals"], uncertainty=result["uncertainty"])
        result.update({
            "system_id": self.SYSTEM_ID,
            "entities": result["context_graph"]["entities"]["concept_nodes"],
            "task_class": task_class,
            "memory_context": memory_hits,
            "temporal_context": temporal_packet,
            "memory_write_candidate": {"status": "candidate_only", "reason": "System-1 cannot persist inferred facts without governance-approved evidence."},
        })
        return result
