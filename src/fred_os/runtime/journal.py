"""Append-only write-ahead journal for atomic FRED OS runtime transactions."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any

from .contracts import canonical_hash


class JournalError(RuntimeError):
    pass


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    entry_type: str
    payload: dict[str, Any]
    timestamp: float
    previous_hash: str
    entry_hash: str


class RuntimeJournal:
    """Durable WAL. State becomes authoritative only through commit markers."""

    COMMIT_TYPES = {"GENESIS_COMMIT", "TX_COMMIT"}

    def __init__(self, journal_path: str | Path) -> None:
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[JournalEntry]:
        if not self.journal_path.exists():
            return []
        result: list[JournalEntry] = []
        previous_hash = "GENESIS"
        with self.journal_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                    entry = JournalEntry(
                        seq=int(record["seq"]),
                        entry_type=str(record["entry_type"]),
                        payload=dict(record.get("payload", {})),
                        timestamp=float(record.get("timestamp", 0.0)),
                        previous_hash=str(record["previous_hash"]),
                        entry_hash=str(record["entry_hash"]),
                    )
                except Exception as exc:
                    raise JournalError(f"Invalid WAL record at line {line_number}: {exc}") from exc
                expected = canonical_hash({
                    "seq": entry.seq,
                    "entry_type": entry.entry_type,
                    "payload": entry.payload,
                    "previous_hash": entry.previous_hash,
                })
                if entry.previous_hash != previous_hash or entry.entry_hash != expected:
                    raise JournalError(f"WAL hash-chain verification failed at line {line_number}")
                result.append(entry)
                previous_hash = entry.entry_hash
        return result

    def append_entry(self, entry_type: str, payload: dict[str, Any]) -> JournalEntry:
        existing = self.entries()
        seq = existing[-1].seq + 1 if existing else 1
        previous_hash = existing[-1].entry_hash if existing else "GENESIS"
        entry_hash = canonical_hash({
            "seq": seq,
            "entry_type": entry_type,
            "payload": payload,
            "previous_hash": previous_hash,
        })
        entry = JournalEntry(seq, entry_type, dict(payload), time.time(), previous_hash, entry_hash)
        record = {
            "seq": entry.seq,
            "entry_type": entry.entry_type,
            "payload": entry.payload,
            "timestamp": entry.timestamp,
            "previous_hash": entry.previous_hash,
            "entry_hash": entry.entry_hash,
        }
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def committed_capsule_ids(self) -> set[str]:
        ids: set[str] = set()
        for entry in self.entries():
            if entry.entry_type in self.COMMIT_TYPES:
                capsule_id = str(entry.payload.get("capsule_id", ""))
                if capsule_id:
                    ids.add(capsule_id)
        return ids

    def latest_commit(self) -> JournalEntry | None:
        commits = [entry for entry in self.entries() if entry.entry_type in self.COMMIT_TYPES]
        return commits[-1] if commits else None

    def uncommitted_transactions(self) -> list[dict[str, Any]]:
        """Return TX_START records that have no matching TX_COMMIT/TX_ABORT."""
        open_transactions: dict[str, JournalEntry] = {}
        for entry in self.entries():
            command_id = str(entry.payload.get("command_id", ""))
            if entry.entry_type == "TX_START" and command_id:
                open_transactions[command_id] = entry
            elif entry.entry_type in {"TX_COMMIT", "TX_ABORT"} and command_id:
                open_transactions.pop(command_id, None)
        return [
            {"command_id": command_id, "start_seq": entry.seq, "entry_hash": entry.entry_hash}
            for command_id, entry in open_transactions.items()
        ]
