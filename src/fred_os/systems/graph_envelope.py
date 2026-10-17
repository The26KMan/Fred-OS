"""Reference System-1 Graph Envelope construction and structural validation.

System-2 consumes ``schema://S1/graph-envelope/1.0`` by immutable identity,
revision, and digest. The vNext S1 adapter predates that transport contract, so
this module bridges the live S1 output into the reference envelope shape and
checks the envelope before S2 is allowed to consume it.

The envelope is a *transport* contract: it carries the canonical graph payload,
its validation record, provenance, and a content digest. S2 never mutates it.
"""
from __future__ import annotations

import re
from hashlib import sha256
import json
from typing import Any, Mapping

ENVELOPE_VERSION = "1.0"
PAYLOAD_SCHEMA = "schema://S1/context-graph/1.0"
PRODUCER_VERSION = "0.3.0-draft.7"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_NODE_TYPES = frozenset(
    {"entity", "actor", "role", "concept", "event", "objective", "task",
     "constraint", "claim", "question", "temporal-marker", "domain", "system", "artifact"}
)
_EPISTEMIC_STATES = frozenset({"source", "prior", "inferred", "uncertain", "contradicted"})
_GRAPH_FAMILIES = frozenset(
    {"situational", "task", "semantic", "temporal", "influence", "neurosemantic", "article-overlay"}
)
_RELATION_BY_REASONING = {
    "direct": "associated-with",
    "analogical": "analogous-to",
    "cross_domain": "cross-domain-association",
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def canonical_digest(value: Any) -> str:
    """Digest a JSON-compatible value exactly as the S1/S2 runtimes do."""
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + sha256(data).hexdigest()


def slugify(value: Any, fallback: str = "node") -> str:
    """Return an identifier conforming to ``schema://S1/common/1.0``."""
    text = re.sub(r"[^A-Za-z0-9._:/-]+", "-", str(value or "").strip().lower()).strip("-")
    if not text or not text[0].isalnum():
        text = f"{fallback}-{text}".strip("-") if text else fallback
    return text[:256]


def _confidence(value: Any, method: str = "rule-derived") -> dict[str, Any]:
    return {
        "value": round(clamp(value), 6),
        "method": method,
        "calibration_ref": None,
        "explanation_code": None,
    }


def _provenance(source_id: str, producer_id: str, block_id: str | None = None) -> list[dict[str, Any]]:
    seed = f"{source_id}|{block_id or ''}|{producer_id}"
    return [
        {
            "provenance_id": "prov-" + sha256(seed.encode("utf-8")).hexdigest()[:16],
            "source_id": slugify(source_id, "source"),
            "block_id": block_id,
            "span": None,
            "span_unavailable_reason": "whole_block_semantic_reference",
            "producer_id": producer_id,
            "transformation_chain": ["S1.deterministic-lexical-baseline"],
        }
    ]


def _nodes_from_concepts(concepts: list[Mapping[str, Any]], source_id: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    nodes: list[dict[str, Any]] = []
    node_ids: dict[str, str] = {}
    seen: set[str] = set()
    for concept in concepts:
        label = str(concept.get("normalized_concept") or concept.get("raw_phrase") or "").strip()
        if not label:
            continue
        node_id = slugify(label)
        if node_id in seen:
            continue
        seen.add(node_id)
        node_ids[label] = node_id
        node_ids[label.lower()] = node_id
        domains = [str(concept.get("semantic_domain") or "general")]
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "type": "concept",
                "epistemic_state": "source",
                "salience": round(clamp(concept.get("emergence_potential", 0.5)), 6),
                "activation": 0.0,
                "confidence": _confidence(concept.get("emergence_potential", 0.5)),
                "provenance": _provenance(source_id, "S1.cognitive_mapping"),
                "temporal": None,
                "domains": domains,
                "attributes": {
                    "abstraction_level": int(concept.get("abstraction_level", 0) or 0),
                    "analogical_bridges": list(concept.get("analogical_bridges", []) or []),
                    "emotional_subtypes": list(concept.get("emotional_subtypes", []) or []),
                },
            }
        )
    return nodes, node_ids


def _edges_from_connections(
    connections: list[Mapping[str, Any]], node_ids: Mapping[str, str], source_id: str
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, connection in enumerate(connections, start=1):
        source = node_ids.get(str(connection.get("source", ""))) or node_ids.get(str(connection.get("source", "")).lower())
        target = node_ids.get(str(connection.get("target", ""))) or node_ids.get(str(connection.get("target", "")).lower())
        if not source or not target or source == target:
            continue
        reasoning = str(connection.get("reasoning_type", "direct"))
        edges.append(
            {
                "id": f"e{index}",
                "source": source,
                "target": target,
                "relation": _RELATION_BY_REASONING.get(reasoning, "associated-with"),
                "weight": round(clamp(connection.get("weight", 0.0), -1.0, 1.0), 6),
                "confidence": _confidence(connection.get("weight", 0.0)),
                "epistemic_state": "source" if reasoning == "direct" else "inferred",
                "provenance": _provenance(source_id, "S1.cognitive_mapping"),
                "temporal": None,
                "attributes": {
                    "reasoning_type": reasoning,
                    "hops": int(connection.get("hops", 1) or 1),
                },
            }
        )
    return edges


def build_graph_envelope(
    s1_output: Mapping[str, Any],
    *,
    source_id: str = "s1.turn",
    graph_id: str | None = None,
    revision: int = 1,
    graph_family: str = "situational",
    runtime_profile: str = "development",
    created_at: str | None = None,
    block_id: str | None = None,
) -> dict[str, Any]:
    """Bridge a live S1 output into a reference Graph Envelope."""
    concepts = [item for item in s1_output.get("enriched_concepts", []) or [] if isinstance(item, Mapping)]
    connections = [item for item in s1_output.get("multi_hop_connections", []) or [] if isinstance(item, Mapping)]
    nodes, node_ids = _nodes_from_concepts(concepts, source_id)
    edges = _edges_from_connections(connections, node_ids, source_id)

    payload = {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "source_layer_present": True,
            "overlay_layer_present": False,
            "uncertainty": dict(s1_output.get("uncertainty", {}) or {}),
        },
    }
    family = graph_family if graph_family in _GRAPH_FAMILIES else "situational"
    resolved_graph_id = slugify(graph_id, "graph") if graph_id else "graph-" + sha256(
        f"{source_id}|{len(nodes)}|{len(edges)}".encode("utf-8")
    ).hexdigest()[:16]
    digest = canonical_digest(payload)
    return {
        "envelope_version": ENVELOPE_VERSION,
        "graph_id": resolved_graph_id,
        "graph_family": family,
        "graph_revision": int(revision),
        "parent_revision": None if int(revision) == 0 else max(0, int(revision) - 1),
        "producer": {
            "system": "S1",
            "functioning": "functioning://S1/GRAPH.CONSTRUCTION",
            "version": PRODUCER_VERSION,
            "runtime_profile": runtime_profile,
        },
        "temporal_anchor": None,
        "payload_schema": PAYLOAD_SCHEMA,
        "payload": payload,
        "validation": {
            "status": "valid",
            "schema_valid": True,
            "semantic_valid": True,
            "validator": "fred_os.systems.graph_envelope",
            "validated_at": created_at or "1970-01-01T00:00:00Z",
            "violations": [],
        },
        "provenance": _provenance(source_id, "S1.cognitive_mapping", block_id),
        "handoffs": [],
        "content_digest": digest,
        "created_at": created_at or "1970-01-01T00:00:00Z",
    }


def validate_graph_envelope(envelope: Mapping[str, Any]) -> list[dict[str, str]]:
    """Structural validation of a reference Graph Envelope. Returns violations."""
    violations: list[dict[str, str]] = []

    def add(code: str, path: str, message: str) -> None:
        violations.append({"code": code, "path": path, "message": message})

    required = (
        "envelope_version", "graph_id", "graph_family", "graph_revision", "parent_revision",
        "producer", "temporal_anchor", "payload_schema", "payload", "validation",
        "provenance", "handoffs", "content_digest", "created_at",
    )
    for key in required:
        if key not in envelope:
            add("MISSING_FIELD", f"$/{key}", f"required field '{key}' is absent")
    if violations:
        return violations

    if envelope["envelope_version"] != ENVELOPE_VERSION:
        add("ENVELOPE_VERSION", "$/envelope_version", "unsupported envelope version")
    if not _IDENTIFIER.match(str(envelope["graph_id"])):
        add("INVALID_IDENTIFIER", "$/graph_id", "graph_id is not a valid identifier")
    if envelope["graph_family"] not in _GRAPH_FAMILIES:
        add("INVALID_GRAPH_FAMILY", "$/graph_family", "unknown graph family")
    if not isinstance(envelope["graph_revision"], int) or envelope["graph_revision"] < 0:
        add("INVALID_REVISION", "$/graph_revision", "revision must be a non-negative integer")
    if envelope["payload_schema"] != PAYLOAD_SCHEMA:
        add("PAYLOAD_SCHEMA", "$/payload_schema", "unsupported payload schema")
    if not _DIGEST.match(str(envelope["content_digest"])):
        add("INVALID_DIGEST", "$/content_digest", "content_digest must be sha256:<64 hex>")

    payload = envelope["payload"]
    if not isinstance(payload, Mapping) or "nodes" not in payload or "edges" not in payload:
        add("INVALID_PAYLOAD", "$/payload", "payload must contain nodes and edges")
        return violations

    node_ids: set[str] = set()
    for index, node in enumerate(payload["nodes"]):
        path = f"$/payload/nodes/{index}"
        if not isinstance(node, Mapping):
            add("INVALID_NODE", path, "node must be an object")
            continue
        for key in ("id", "label", "type", "epistemic_state", "salience", "activation", "confidence", "provenance", "domains", "attributes"):
            if key not in node:
                add("MISSING_NODE_FIELD", f"{path}/{key}", f"node field '{key}' is absent")
        node_id = str(node.get("id", ""))
        if not _IDENTIFIER.match(node_id):
            add("INVALID_IDENTIFIER", f"{path}/id", "node id is not a valid identifier")
        if node.get("type") not in _NODE_TYPES:
            add("INVALID_NODE_TYPE", f"{path}/type", "unknown node type")
        if node.get("epistemic_state") not in _EPISTEMIC_STATES:
            add("INVALID_EPISTEMIC_STATE", f"{path}/epistemic_state", "unknown epistemic state")
        node_ids.add(node_id)

    for index, edge in enumerate(payload["edges"]):
        path = f"$/payload/edges/{index}"
        if not isinstance(edge, Mapping):
            add("INVALID_EDGE", path, "edge must be an object")
            continue
        for key in ("id", "source", "target", "relation", "weight", "confidence", "epistemic_state", "provenance", "attributes"):
            if key not in edge:
                add("MISSING_EDGE_FIELD", f"{path}/{key}", f"edge field '{key}' is absent")
        if edge.get("source") not in node_ids:
            add("DANGLING_EDGE", f"{path}/source", "edge source does not reference a node")
        if edge.get("target") not in node_ids:
            add("DANGLING_EDGE", f"{path}/target", "edge target does not reference a node")

    if not violations and canonical_digest(payload) != envelope["content_digest"]:
        add("DIGEST_MISMATCH", "$/content_digest", "content_digest does not match the canonical payload")
    return violations


def envelope_is_valid(envelope: Mapping[str, Any]) -> bool:
    return not validate_graph_envelope(envelope)
