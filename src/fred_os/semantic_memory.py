"""Semantic Memory Lake policy over the durable artifact store."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from .artifact_store import ArtifactStore, Fragment
from .provenance import Authority, Lifecycle

@dataclass(frozen=True)
class RecallReceipt:
    query: str
    hits: tuple[dict[str, Any], ...]

class SemanticMemoryLake:
    def __init__(self, path: str | Path, tenant_id: str, project_id: str) -> None:
        self.store = ArtifactStore(path, tenant_id, project_id)

    def ingest(self, artifact_id: str, title: str, text: str, authority: Authority = Authority.DESIGN_SPEC, source_uri: str = '') -> dict[str, Any]:
        fragments = self.store.ingest(artifact_id=artifact_id,title=title,text=text,authority=authority,source_uri=source_uri)
        return {'artifact_id':artifact_id,'fragment_count':len(fragments),'deeplinks':[fragment.locator.canonical for fragment in fragments]}

    def recall(self, query: str, limit: int = 6) -> RecallReceipt:
        fragments = self.store.search(query, limit)
        hits=[]
        for rank, fragment in enumerate(fragments,1):
            hits.append({'rank':rank,'authority':fragment.authority.value,'deeplink':fragment.locator.canonical,'source_uri':fragment.source_uri,'line_range':[fragment.start_line,fragment.end_line],'excerpt':fragment.body[:600]})
        return RecallReceipt(query, tuple(hits))

    def checkpoint(self, title: str, summary: str, source_deeplinks: Sequence[str], decisions: Sequence[str] = (), open_questions: Sequence[str] = ()) -> dict[str, Any]:
        for link in source_deeplinks:
            # Parsing happens as part of a lookup path in future expansion; this
            # currently prevents malformed checkpoint references.
            if not link.startswith('deeplink://'):
                raise ValueError('Checkpoint sources must be immutable DeepLinks')
        body='\n'.join([summary, 'Sources: '+', '.join(source_deeplinks), 'Decisions: '+', '.join(decisions), 'Open questions: '+', '.join(open_questions)])
        return self.ingest('checkpoint-'+str(abs(hash(body))),title,body,Authority.GOVERNANCE_POLICY)

    def close(self) -> None:
        self.store.close()
