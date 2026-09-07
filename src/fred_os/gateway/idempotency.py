"""Durable idempotency reservations and result replay for the M1 gateway."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time

from .contracts import IdempotencyConflictError, IdempotencyRecord


class IdempotencyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gateway_idempotency (
                caller_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                command_id TEXT,
                result_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (caller_id, idempotency_key)
            )
            """
        )
        self.connection.commit()

    def get(self, caller_id: str, idempotency_key: str) -> IdempotencyRecord | None:
        row = self.connection.execute(
            "SELECT caller_id,idempotency_key,request_hash,status,command_id,result_json "
            "FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
            (caller_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            caller_id=str(row["caller_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            status=str(row["status"]),
            command_id=str(row["command_id"]) if row["command_id"] is not None else None,
            result_json=str(row["result_json"]) if row["result_json"] is not None else None,
        )

    def reserve(self, caller_id: str, idempotency_key: str, request_hash: str, command_id: str) -> IdempotencyRecord:
        existing = self.get(caller_id, idempotency_key)
        if existing is not None:
            self._assert_same_request(existing, request_hash)
            return existing
        now = time.time()
        self.connection.execute(
            "INSERT INTO gateway_idempotency "
            "(caller_id,idempotency_key,request_hash,status,command_id,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (caller_id, idempotency_key, request_hash, "PENDING", command_id, None, now, now),
        )
        self.connection.commit()
        return self.get(caller_id, idempotency_key)  # type: ignore[return-value]

    def finalize(self, caller_id: str, idempotency_key: str, request_hash: str, result_payload: dict) -> IdempotencyRecord:
        existing = self.get(caller_id, idempotency_key)
        if existing is None:
            raise RuntimeError("idempotency reservation missing during finalize")
        self._assert_same_request(existing, request_hash)
        packed = json.dumps(result_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.connection.execute(
            "UPDATE gateway_idempotency SET status='COMPLETE', result_json=?, updated_at=? "
            "WHERE caller_id=? AND idempotency_key=?",
            (packed, time.time(), caller_id, idempotency_key),
        )
        self.connection.commit()
        return self.get(caller_id, idempotency_key)  # type: ignore[return-value]

    def release_pending(self, caller_id: str, idempotency_key: str, request_hash: str) -> None:
        existing = self.get(caller_id, idempotency_key)
        if existing is None:
            return
        self._assert_same_request(existing, request_hash)
        if existing.status == "PENDING":
            self.connection.execute(
                "DELETE FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
                (caller_id, idempotency_key),
            )
            self.connection.commit()

    @staticmethod
    def decode_result(record: IdempotencyRecord) -> dict:
        if record.status != "COMPLETE" or not record.result_json:
            raise RuntimeError("idempotency result is not complete")
        return dict(json.loads(record.result_json))

    @staticmethod
    def _assert_same_request(record: IdempotencyRecord, request_hash: str) -> None:
        if record.request_hash != request_hash:
            raise IdempotencyConflictError(
                f"idempotency key {record.idempotency_key!r} was already used for a different request"
            )

    def close(self) -> None:
        self.connection.close()
