"""Durable, version-aware semantic artifact store."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .provenance import Authority, Lifecycle, SourceLocator, slug

def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8', errors='ignore')).hexdigest()

@dataclass(frozen=True)
class Fragment:
    locator: SourceLocator
    body: str
    authority: Authority
    lifecycle: Lifecycle
    source_uri: str
    start_line: int
    end_line: int

class ArtifactStore:
    def __init__(self, path: str | Path, tenant_id: str, project_id: str) -> None:
        self.tenant_id, self.project_id = slug(tenant_id, 'default'), slug(project_id, 'system-os')
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript('''
          CREATE TABLE IF NOT EXISTS revisions(revision_id TEXT PRIMARY KEY, tenant_id TEXT, project_id TEXT, artifact_id TEXT, ordinal INTEGER, content_hash TEXT, authority TEXT, lifecycle TEXT, source_uri TEXT, created_at REAL);
          CREATE TABLE IF NOT EXISTS fragments(fragment_id TEXT PRIMARY KEY, revision_id TEXT, tenant_id TEXT, project_id TEXT, artifact_id TEXT, body TEXT, authority TEXT, lifecycle TEXT, source_uri TEXT, start_line INTEGER, end_line INTEGER, locator TEXT UNIQUE);
          CREATE TABLE IF NOT EXISTS audit(event_id TEXT PRIMARY KEY, event_type TEXT, payload TEXT, previous_hash TEXT, event_hash TEXT UNIQUE, created_at REAL);
        ''')
        self.connection.commit()

    def _event(self, kind: str, payload: dict[str, Any]) -> None:
        previous = self.connection.execute('SELECT event_hash FROM audit ORDER BY created_at DESC LIMIT 1').fetchone()
        parent = previous['event_hash'] if previous else 'GENESIS'
        now = time.time(); packed = json.dumps(payload, sort_keys=True)
        event_hash = digest(f'{parent}|{kind}|{packed}|{now}')
        self.connection.execute('INSERT INTO audit VALUES(?,?,?,?,?,?)', (f'evt-{event_hash[:16]}',kind,packed,parent,event_hash,now))

    def ingest(self, *, artifact_id: str, title: str, text: str, authority: Authority, lifecycle: Lifecycle = Lifecycle.CURRENT, source_uri: str = '') -> list[Fragment]:
        artifact_id = slug(artifact_id, 'artifact'); content_hash = digest(text)
        row = self.connection.execute('SELECT * FROM revisions WHERE tenant_id=? AND project_id=? AND artifact_id=? ORDER BY ordinal DESC LIMIT 1',(self.tenant_id,self.project_id,artifact_id)).fetchone()
        if row and row['content_hash'] == content_hash:
            return self.fragments(row['revision_id'])
        ordinal = int(row['ordinal']) + 1 if row else 1
        revision_id = f'r{ordinal}-{content_hash[:12]}'
        self.connection.execute("UPDATE revisions SET lifecycle='superseded' WHERE tenant_id=? AND project_id=? AND artifact_id=? AND lifecycle='current'",(self.tenant_id,self.project_id,artifact_id))
        self.connection.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)',(revision_id,self.tenant_id,self.project_id,artifact_id,ordinal,content_hash,authority.value,lifecycle.value,source_uri,time.time()))
        fragments=[]
        for index, body in enumerate([part.strip() for part in text.split('\n\n') if part.strip()] or [text],1):
            fragment_id=f'f{index}-{digest(body)[:10]}'; locator=SourceLocator(self.tenant_id,self.project_id,artifact_id,revision_id,fragment_id)
            self.connection.execute('INSERT INTO fragments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(fragment_id,revision_id,self.tenant_id,self.project_id,artifact_id,body,authority.value,lifecycle.value,source_uri,1,body.count('\n')+1,locator.canonical))
            fragments.append(Fragment(locator,body,authority,lifecycle,source_uri,1,body.count('\n')+1))
        self._event('ARTIFACT_INGESTED', {'title':title,'artifact_id':artifact_id,'revision_id':revision_id,'count':len(fragments)})
        self.connection.commit(); return fragments

    def fragments(self, revision_id: str) -> list[Fragment]:
        rows=self.connection.execute('SELECT * FROM fragments WHERE revision_id=?',(revision_id,)).fetchall()
        return [Fragment(SourceLocator.parse(r['locator']),r['body'],Authority(r['authority']),Lifecycle(r['lifecycle']),r['source_uri'],r['start_line'],r['end_line']) for r in rows]

    def search(self, query: str, limit: int = 6) -> list[Fragment]:
        terms=[term.lower() for term in query.split() if len(term)>2]
        if not terms:return []
        clause=' OR '.join('LOWER(body) LIKE ?' for _ in terms)
        rows=self.connection.execute(f"SELECT * FROM fragments WHERE tenant_id=? AND project_id=? AND lifecycle != 'historical' AND ({clause}) LIMIT ?",[self.tenant_id,self.project_id,*[f'%{term}%' for term in terms],limit]).fetchall()
        self._event('RECALL_EXECUTED', {'query':query,'hit_count':len(rows)}); self.connection.commit()
        return [Fragment(SourceLocator.parse(r['locator']),r['body'],Authority(r['authority']),Lifecycle(r['lifecycle']),r['source_uri'],r['start_line'],r['end_line']) for r in rows]

    def close(self) -> None:
        self.connection.close()
