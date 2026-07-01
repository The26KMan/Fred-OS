"""Semantic Memory Lake policy over the durable artifact store."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .artifact_store import ArtifactStore
from .provenance import Authority


@dataclass(frozen=True)
class RecallReceipt:
    query: str
    hits: tuple[dict[str, Any], ...]


class SemanticMemoryLake:
    def __init__(self, path: str | Path, tenant_id: str, project_id: str) -> None:
        self.store = ArtifactStore(path, tenant_id, project_id)

    def ingest(self, artifact_id: str, title: str, text: str,
               authority: Authority = Authority.DESIGN_SPEC, source_uri: str = "") -> dict[str, Any]:
        fragments = self.store.ingest(
            artifact_id=artifact_id, title=title, text=text,
            authority=authority, source_uri=source_uri,
        )
        return {
            "artifact_id": artifact_id,
            "fragment_count": len(fragments),
            "deeplinks": [fragment.locator.canonical for fragment in fragments],
        }

    def recall(self, query: str, limit: int = 6) -> RecallReceipt:
        fragments = self.store.search(query, limit)
        hits: list[dict[str, Any]] = []
        for rank, fragment in enumerate(fragments, 1):
            locator = fragment.locator.canonical
            hits.append({
                "rank": rank,
                "authority": fragment.authority.value,
                "deeplink": locator,
                "source_uri": fragment.source_uri,
                "line_range": [fragment.start_line, fragment.end_line],
                "excerpt": fragment.body[:600],
                "temporal_links": self.store.temporal_links_for_locator(locator),
            })
        return RecallReceipt(query, tuple(hits))

    def link_tsc_shard(self, deeplink: str, tsc_shard_id: str, relation: str = "recall_context") -> bool:
        return self.store.link_temporal_shard(deeplink, tsc_shard_id, relation)

    def sources_for_tsc_shard(self, tsc_shard_id: str) -> list[dict[str, Any]]:
        return self.store.locators_for_temporal_shard(tsc_shard_id)

    def checkpoint(self, title: str, summary: str, source_deeplinks: Sequence[str],
                   decisions: Sequence[str] = (), open_questions: Sequence[str] = ()) -> dict[str, Any]:
        for link in source_deeplinks:
            if not link.startswith("deeplink://"):
                raise ValueError("Checkpoint sources must be immutable DeepLinks")
        body = "\n".join([
            summary,
            "Sources: " + ", ".join(source_deeplinks),
            "Decisions: " + ", ".join(decisions),
            "Open questions: " + ", ".join(open_questions),
        ])
        return self.ingest("checkpoint-" + str(abs(hash(body))), title, body, Authority.GOVERNANCE_POLICY)

    def close(self) -> None:
        self.store.close()
