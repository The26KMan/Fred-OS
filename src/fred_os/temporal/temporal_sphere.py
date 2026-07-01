"""Temporal Sphere Component (TSC) for Fred-OS vNext.

TSC provides an explicit temporal substrate: bounded working cues, compressed
contextual segments, cautiously promoted episodic patterns, commitments, and
heuristic next-step projections. It is invoked by the RuntimeKernel per turn;
it is not a hidden background process or a claim of model-internal persistence.

Each temporal shard may carry Memory Lake references. Memory Lake records may
likewise retain a `tsc_shard_id` in their provenance when an explicit caller
creates that cross-reference.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", text) if len(item) > 2}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class TemporalSphereConfig:
    working_capacity: int = 5
    micro_window: int = 5
    meso_window: int = 4
    episodic_min_reinforcement: int = 2
    projection_limit: int = 3

    @classmethod
    def from_runtime(cls, config: Any) -> "TemporalSphereConfig":
        return cls(
            working_capacity=int(config.get("temporal.working_capacity", 5)),
            micro_window=int(config.get("temporal.micro_window", 5)),
            meso_window=int(config.get("temporal.meso_window", 4)),
            episodic_min_reinforcement=int(config.get("temporal.episodic_min_reinforcement", 2)),
            projection_limit=int(config.get("temporal.projection_limit", 3)),
        )


@dataclass
class TemporalShard:
    shard_id: str
    turn: int
    created_at: float
    user_input: str
    summary: str
    entities: list[str]
    objectives: list[str]
    constraints: list[str]
    open_questions: list[str]
    temporal_refs: list[str]
    temporal_state: str
    uncertainty: float
    importance: float
    commitment_keys: list[str] = field(default_factory=list)
    memory_lake_node_ids: list[str] = field(default_factory=list)
    source_deeplinks: list[str] = field(default_factory=list)

    def cue(self, current_turn: int) -> dict[str, Any]:
        recency = max(0, current_turn - self.turn)
        salience = round(_clamp(self.importance / (1.0 + 0.20 * recency)), 4)
        return {
            "type": "working",
            "shard_id": self.shard_id,
            "turn": self.turn,
            "content": self.summary,
            "recency": recency,
            "salience": salience,
            "temporal_state": self.temporal_state,
            "source_deeplinks": list(self.source_deeplinks),
            "memory_lake_node_ids": list(self.memory_lake_node_ids),
        }


@dataclass
class ContextSegment:
    segment_id: str
    layer: str
    start_turn: int
    end_turn: int
    summary: str
    topics: list[str]
    commitments: list[str]
    importance: float
    source_shard_ids: list[str]

    def cue(self, query: str) -> dict[str, Any]:
        query_terms = _tokens(query)
        segment_terms = _tokens(self.summary + " " + " ".join(self.topics))
        overlap = len(query_terms & segment_terms) / max(1, len(query_terms))
        return {
            "type": f"contextual_{self.layer}",
            "segment_id": self.segment_id,
            "content": self.summary,
            "relevance": round(_clamp(0.60 * overlap + 0.40 * self.importance), 4),
            "time_range": [self.start_turn, self.end_turn],
            "commitments": list(self.commitments),
            "source_shard_ids": list(self.source_shard_ids),
        }


@dataclass
class EpisodicPattern:
    pattern_id: str
    signature: str
    description: str
    confidence: float
    evidence_turns: list[int]
    source_shard_ids: list[str]


class TemporalSphere:
    """Bounded, deterministic temporal memory and context service."""

    def __init__(self, config: TemporalSphereConfig | None = None) -> None:
        self.config = config or TemporalSphereConfig()
        self.session_id = str(uuid.uuid4())
        self.current_turn = 0
        self.working_memory: deque[TemporalShard] = deque(maxlen=self.config.working_capacity)
        self.micro_segments: list[ContextSegment] = []
        self.meso_segments: list[ContextSegment] = []
        self.episodic_patterns: list[EpisodicPattern] = []
        self.commitments: dict[str, dict[str, Any]] = {}
        self._signature_evidence: dict[str, list[TemporalShard]] = {}
        self._uncertainty_history: deque[float] = deque(maxlen=20)

    def record_turn(self, user_input: str, s1_output: Mapping[str, Any], outputs: Mapping[str, Any] | None = None) -> TemporalShard:
        self.current_turn += 1
        context_graph = dict(s1_output.get("context_graph", {}))
        entities = self._flatten_entities(context_graph.get("entities", s1_output.get("entities", [])))
        objectives = list(context_graph.get("objectives", []))
        constraints = list(context_graph.get("constraints", []))
        questions = list(context_graph.get("open_questions", []))
        temporal_refs = list(context_graph.get("temporal_refs", []))
        temporal_state = str(s1_output.get("temporal_state", context_graph.get("temporal_state", "state")))
        uncertainty = _clamp(dict(s1_output.get("uncertainty", {})).get("score", 1.0))
        concepts = [item.get("normalized_concept", "") for item in s1_output.get("enriched_concepts", []) if isinstance(item, Mapping)]
        commitments = self._extract_commitments(constraints, temporal_refs, context_graph, user_input)
        summary = self._summarize(objectives, constraints, questions, concepts, temporal_state)
        importance = self._importance(objectives, constraints, questions, uncertainty)
        shard = TemporalShard(
            shard_id=f"tsc-{self.session_id[:8]}-{self.current_turn}",
            turn=self.current_turn,
            created_at=time.time(),
            user_input=user_input,
            summary=summary,
            entities=entities,
            objectives=objectives,
            constraints=constraints,
            open_questions=questions,
            temporal_refs=temporal_refs,
            temporal_state=temporal_state,
            uncertainty=uncertainty,
            importance=importance,
            commitment_keys=[item["key"] for item in commitments],
            source_deeplinks=self._extract_deeplinks(s1_output),
        )
        if len(self.working_memory) == self.working_memory.maxlen:
            self._promote_to_contextual(self.working_memory[0])
        self.working_memory.append(shard)
        self._uncertainty_history.append(uncertainty)
        for commitment in commitments:
            self.commitments[commitment["key"]] = {**commitment, "turn": self.current_turn, "shard_id": shard.shard_id}
        self._observe_pattern(shard)
        self._maybe_promote_micro_to_meso()
        return shard

    def attach_memory_reference(self, shard_id: str, *, memory_lake_node_id: str | None = None, deeplink: str | None = None) -> bool:
        for shard in self.working_memory:
            if shard.shard_id != shard_id:
                continue
            if memory_lake_node_id and memory_lake_node_id not in shard.memory_lake_node_ids:
                shard.memory_lake_node_ids.append(memory_lake_node_id)
            if deeplink and deeplink not in shard.source_deeplinks:
                shard.source_deeplinks.append(deeplink)
            return True
        return False

    def context_packet(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        working = sorted((shard.cue(self.current_turn) for shard in self.working_memory), key=lambda item: item["salience"], reverse=True)
        contextual = [segment.cue(query) for segment in self.micro_segments + self.meso_segments]
        contextual = sorted(contextual, key=lambda item: item["relevance"], reverse=True)[:max(0, limit - len(working))]
        patterns = self._episodic_cues(query)[:3]
        return {
            "session_id": self.session_id,
            "current_turn": self.current_turn,
            "working_cues": working[:limit],
            "contextual_cues": contextual,
            "episodic_cues": patterns,
            "commitments": list(self.commitments.values())[-10:],
            "temporal_entropy": round(self.temporal_entropy(), 4),
            "coherence": round(self.coherence(), 4),
            "projections": self.project_next_steps(query),
        }

    def resolve_reference(self, reference: str) -> dict[str, Any] | None:
        wanted = _tokens(reference)
        candidates: list[tuple[float, str, str, int | None]] = []
        for shard in self.working_memory:
            score = len(wanted & _tokens(shard.user_input + " " + shard.summary))
            if score:
                candidates.append((score + 0.20 * shard.importance, shard.shard_id, shard.summary, shard.turn))
        for segment in self.micro_segments + self.meso_segments:
            score = len(wanted & _tokens(segment.summary + " " + " ".join(segment.topics)))
            if score:
                candidates.append((score + 0.10 * segment.importance, segment.segment_id, segment.summary, segment.end_turn))
        if not candidates:
            return None
        score, identifier, summary, turn = max(candidates, key=lambda item: item[0])
        return {"reference": reference, "id": identifier, "summary": summary, "turn": turn, "confidence": round(_clamp(score / max(1, len(wanted))), 4)}

    def check_commitment(self, key: str) -> dict[str, Any] | None:
        normalized = key.strip().lower()
        exact = self.commitments.get(normalized)
        if exact:
            return dict(exact)
        for candidate, record in reversed(list(self.commitments.items())):
            if normalized in candidate or candidate in normalized:
                return dict(record)
        return None

    def project_next_steps(self, query: str) -> list[dict[str, Any]]:
        if not self.working_memory:
            return []
        latest = self.working_memory[-1]
        actions: list[tuple[str, float, str]] = []
        if latest.open_questions or latest.temporal_state == "ask":
            actions.append(("clarify_missing_information", 0.65, "open questions or an interrogative state remain"))
        if latest.constraints or latest.temporal_refs:
            actions.append(("verify_commitments", 0.62, "constraints or temporal references are present"))
        if latest.uncertainty >= 0.55:
            actions.append(("retrieve_or_expand_evidence", 0.58, "uncertainty is elevated"))
        if latest.objectives:
            actions.append(("advance_declared_objective", 0.56, "an objective was detected"))
        if not actions:
            actions.append(("continue_current_topic", 0.40, "no stronger transition signal was detected"))
        return [{"action": action, "probability": probability, "basis": basis, "kind": "heuristic_projection"} for action, probability, basis in actions[:self.config.projection_limit]]

    def temporal_entropy(self) -> float:
        if not self._uncertainty_history:
            return 0.0
        mean = sum(self._uncertainty_history) / len(self._uncertainty_history)
        spread = sum((value - mean) ** 2 for value in self._uncertainty_history) / len(self._uncertainty_history)
        return _clamp(0.70 * mean + 0.30 * min(1.0, spread * 4.0))

    def coherence(self) -> float:
        if not self.working_memory:
            return 1.0
        states = Counter(shard.temporal_state for shard in self.working_memory)
        dominant = max(states.values()) / len(self.working_memory)
        uncommitted = sum(1 for shard in self.working_memory if shard.constraints and not shard.commitment_keys)
        return _clamp(0.70 * dominant + 0.30 * (1.0 - uncommitted / len(self.working_memory)))

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "session_id": self.session_id,
            "current_turn": self.current_turn,
            "working_memory": [asdict(item) for item in self.working_memory],
            "micro_segments": [asdict(item) for item in self.micro_segments],
            "meso_segments": [asdict(item) for item in self.meso_segments],
            "episodic_patterns": [asdict(item) for item in self.episodic_patterns],
            "commitments": dict(self.commitments),
            "temporal_entropy": self.temporal_entropy(),
            "coherence": self.coherence(),
        }

    def save_snapshot(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True), encoding="utf-8")
        return target

    @staticmethod
    def _flatten_entities(entities: Any) -> list[str]:
        if isinstance(entities, Mapping):
            values: list[str] = []
            for group in entities.values():
                if isinstance(group, Sequence) and not isinstance(group, (str, bytes)):
                    values.extend(str(item) for item in group)
            return sorted(dict.fromkeys(values))[:30]
        if isinstance(entities, Sequence) and not isinstance(entities, (str, bytes)):
            return [str(item) for item in entities][:30]
        return []

    @staticmethod
    def _extract_deeplinks(s1_output: Mapping[str, Any]) -> list[str]:
        links: list[str] = []
        for item in s1_output.get("memory_context", []):
            if isinstance(item, Mapping) and str(item.get("deeplink", "")).startswith("deeplink://"):
                links.append(str(item["deeplink"]))
        return list(dict.fromkeys(links))

    @staticmethod
    def _summarize(objectives: Sequence[str], constraints: Sequence[str], questions: Sequence[str], concepts: Sequence[str], state: str) -> str:
        portions = [f"state={state}"]
        if objectives:
            portions.append("objectives=" + ", ".join(objectives[:4]))
        if constraints:
            portions.append("constraints=" + ", ".join(constraints[:4]))
        if questions:
            portions.append("questions=" + "; ".join(questions[:1])[:180])
        if concepts:
            portions.append("concepts=" + ", ".join(concepts[:6]))
        return " | ".join(portions)

    @staticmethod
    def _importance(objectives: Sequence[str], constraints: Sequence[str], questions: Sequence[str], uncertainty: float) -> float:
        return _clamp(0.25 + 0.18 * bool(objectives) + 0.24 * bool(constraints) + 0.18 * bool(questions) + 0.15 * uncertainty)

    @staticmethod
    def _extract_commitments(constraints: Sequence[str], temporal_refs: Sequence[str], graph: Mapping[str, Any], text: str) -> list[dict[str, str]]:
        values: list[tuple[str, str]] = []
        for ref in temporal_refs:
            values.append((f"temporal:{ref.lower()}", ref))
        for constraint in constraints:
            values.append((f"constraint:{constraint.lower()}", constraint))
        for number in graph.get("entities", {}).get("numbers", []) if isinstance(graph.get("entities"), Mapping) else []:
            values.append((f"number:{number}", str(number)))
        for match in re.findall(r"\b(?:must|shall|required|by)\b[^.,;!?]{0,80}", text, flags=re.I):
            values.append((f"commitment:{match.lower().strip()}", match.strip()))
        unique: dict[str, dict[str, str]] = {}
        for key, value in values:
            unique[key] = {"key": key, "value": value, "source": "s1_temporal_extraction"}
        return list(unique.values())[:12]

    def _promote_to_contextual(self, shard: TemporalShard) -> None:
        self.micro_segments.append(ContextSegment(
            segment_id=f"micro-{shard.shard_id}",
            layer="micro",
            start_turn=shard.turn,
            end_turn=shard.turn,
            summary=shard.summary,
            topics=shard.entities[:8],
            commitments=shard.commitment_keys,
            importance=shard.importance,
            source_shard_ids=[shard.shard_id],
        ))

    def _maybe_promote_micro_to_meso(self) -> None:
        if len(self.micro_segments) < self.config.micro_window:
            return
        source = self.micro_segments[-self.config.micro_window:]
        topics = Counter(topic for segment in source for topic in segment.topics)
        commitments = list(dict.fromkeys(item for segment in source for item in segment.commitments))
        summary = " | ".join(segment.summary for segment in source[-3:])[:1200]
        self.meso_segments.append(ContextSegment(
            segment_id=f"meso-{source[0].start_turn}-{source[-1].end_turn}",
            layer="meso",
            start_turn=source[0].start_turn,
            end_turn=source[-1].end_turn,
            summary=summary,
            topics=[topic for topic, _ in topics.most_common(8)],
            commitments=commitments,
            importance=round(sum(segment.importance for segment in source) / len(source), 4),
            source_shard_ids=[identifier for segment in source for identifier in segment.source_shard_ids],
        ))
        if len(self.meso_segments) > self.config.meso_window * 3:
            self.meso_segments = self.meso_segments[-self.config.meso_window * 3:]

    def _observe_pattern(self, shard: TemporalShard) -> None:
        signature = "|".join(sorted(set(shard.objectives + shard.temporal_state.split()))) or "state"
        evidence = self._signature_evidence.setdefault(signature, [])
        evidence.append(shard)
        if len(evidence) != self.config.episodic_min_reinforcement:
            return
        pattern = EpisodicPattern(
            pattern_id=f"pattern-{len(self.episodic_patterns) + 1}",
            signature=signature,
            description=f"Repeated temporal signature: {signature}",
            confidence=round(_clamp(0.40 + 0.15 * len(evidence)), 4),
            evidence_turns=[item.turn for item in evidence],
            source_shard_ids=[item.shard_id for item in evidence],
        )
        self.episodic_patterns.append(pattern)

    def _episodic_cues(self, query: str) -> list[dict[str, Any]]:
        query_terms = _tokens(query)
        cues: list[dict[str, Any]] = []
        for pattern in self.episodic_patterns:
            relevance = len(query_terms & _tokens(pattern.description)) / max(1, len(query_terms))
            if relevance or not query_terms:
                cues.append({"type": "episodic", "pattern_id": pattern.pattern_id, "content": pattern.description, "confidence": pattern.confidence, "relevance": round(_clamp(relevance), 4), "evidence_turns": pattern.evidence_turns, "source_shard_ids": pattern.source_shard_ids})
        return sorted(cues, key=lambda item: (item["relevance"], item["confidence"]), reverse=True)
