"""Process-safe idempotency reservations and result replay for the M1 gateway."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Iterator

from .contracts import IdempotencyConflictError, IdempotencyRecord


class IdempotencyStore:
    """SQLite WAL-backed gateway reservation store.

    Connections are operation-scoped so the store is safe to use from lease
    heartbeat threads and from separate worker processes. A PENDING row has an
    explicit owner token and renewable lease; another worker may take ownership
    only after that lease expires.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        busy_timeout_ms: int = 10_000,
        lease_seconds: float = 30.0,
        wait_seconds: float = 30.0,
        poll_seconds: float = 0.025,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.lease_seconds = float(lease_seconds)
        self.wait_seconds = float(wait_seconds)
        self.poll_seconds = float(poll_seconds)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=max(self.busy_timeout_ms / 1000.0, 0.001),
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_idempotency (
                    caller_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    command_id TEXT,
                    result_json TEXT,
                    owner_token TEXT,
                    lease_expires_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (caller_id, idempotency_key)
                )
                """
            )
            columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(gateway_idempotency)")}
            if "owner_token" not in columns:
                connection.execute("ALTER TABLE gateway_idempotency ADD COLUMN owner_token TEXT")
            if "lease_expires_at" not in columns:
                connection.execute("ALTER TABLE gateway_idempotency ADD COLUMN lease_expires_at REAL")

    @staticmethod
    def new_owner_token() -> str:
        return f"owner-{uuid.uuid4().hex}"

    @staticmethod
    def _record(row: sqlite3.Row | None) -> IdempotencyRecord | None:
        if row is None:
            return None
        return IdempotencyRecord(
            caller_id=str(row["caller_id"]),
            idempotency_key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            status=str(row["status"]),
            command_id=str(row["command_id"]) if row["command_id"] is not None else None,
            result_json=str(row["result_json"]) if row["result_json"] is not None else None,
            owner_token=str(row["owner_token"]) if row["owner_token"] is not None else None,
            lease_expires_at=float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
        )

    def _get_with(self, connection: sqlite3.Connection, caller_id: str, idempotency_key: str) -> IdempotencyRecord | None:
        row = connection.execute(
            "SELECT caller_id,idempotency_key,request_hash,status,command_id,result_json,owner_token,lease_expires_at "
            "FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
            (caller_id, idempotency_key),
        ).fetchone()
        return self._record(row)

    def get(self, caller_id: str, idempotency_key: str) -> IdempotencyRecord | None:
        with self._connect() as connection:
            return self._get_with(connection, caller_id, idempotency_key)

    def reserve_owned(
        self,
        caller_id: str,
        idempotency_key: str,
        request_hash: str,
        command_id: str,
        owner_token: str,
    ) -> tuple[IdempotencyRecord, bool]:
        """Atomically create a reservation; return ``(record, acquired)``."""
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_with(connection, caller_id, idempotency_key)
            if existing is not None:
                self._assert_same_request(existing, request_hash)
                connection.execute("COMMIT")
                return existing, False
            connection.execute(
                "INSERT INTO gateway_idempotency "
                "(caller_id,idempotency_key,request_hash,status,command_id,result_json,owner_token,lease_expires_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    caller_id,
                    idempotency_key,
                    request_hash,
                    "PENDING",
                    command_id,
                    None,
                    owner_token,
                    now + self.lease_seconds,
                    now,
                    now,
                ),
            )
            record = self._get_with(connection, caller_id, idempotency_key)
            connection.execute("COMMIT")
            assert record is not None
            return record, True

    def reserve(self, caller_id: str, idempotency_key: str, request_hash: str, command_id: str) -> IdempotencyRecord:
        """Backward-compatible reservation API used by existing M1 tests."""
        record, _ = self.reserve_owned(
            caller_id,
            idempotency_key,
            request_hash,
            command_id,
            owner_token=f"legacy:{command_id}",
        )
        return record

    def claim_if_expired(
        self,
        caller_id: str,
        idempotency_key: str,
        request_hash: str,
        command_id: str,
        owner_token: str,
    ) -> bool:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_with(connection, caller_id, idempotency_key)
            if existing is None:
                connection.execute("COMMIT")
                return False
            self._assert_same_request(existing, request_hash)
            if existing.status != "PENDING" or (existing.lease_expires_at or 0.0) > now:
                connection.execute("COMMIT")
                return False
            cursor = connection.execute(
                "UPDATE gateway_idempotency SET command_id=?, owner_token=?, lease_expires_at=?, updated_at=? "
                "WHERE caller_id=? AND idempotency_key=? AND status='PENDING' AND COALESCE(lease_expires_at,0)<=?",
                (
                    command_id,
                    owner_token,
                    now + self.lease_seconds,
                    now,
                    caller_id,
                    idempotency_key,
                    now,
                ),
            )
            acquired = cursor.rowcount == 1
            connection.execute("COMMIT")
            return acquired

    def renew_lease(self, caller_id: str, idempotency_key: str, request_hash: str, owner_token: str) -> bool:
        now = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_idempotency SET lease_expires_at=?, updated_at=? "
                "WHERE caller_id=? AND idempotency_key=? AND request_hash=? AND status='PENDING' AND owner_token=?",
                (now + self.lease_seconds, now, caller_id, idempotency_key, request_hash, owner_token),
            )
            return cursor.rowcount == 1

    @contextmanager
    def lease_guard(
        self,
        caller_id: str,
        idempotency_key: str,
        request_hash: str,
        owner_token: str,
    ) -> Iterator[None]:
        stop = threading.Event()
        interval = max(min(self.lease_seconds / 3.0, 5.0), 0.05)

        def heartbeat() -> None:
            while not stop.wait(interval):
                if not self.renew_lease(caller_id, idempotency_key, request_hash, owner_token):
                    return

        thread = threading.Thread(target=heartbeat, name="fred-idempotency-lease", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=max(interval * 2.0, 0.1))

    def wait_for_change(self, caller_id: str, idempotency_key: str, request_hash: str) -> IdempotencyRecord | None:
        deadline = time.monotonic() + self.wait_seconds
        while True:
            record = self.get(caller_id, idempotency_key)
            if record is None:
                return None
            self._assert_same_request(record, request_hash)
            if record.status == "COMPLETE":
                return record
            if (record.lease_expires_at or 0.0) <= time.time():
                return record
            if time.monotonic() >= deadline:
                return record
            time.sleep(self.poll_seconds)

    def finalize_owned(
        self,
        caller_id: str,
        idempotency_key: str,
        request_hash: str,
        owner_token: str,
        result_payload: dict,
    ) -> IdempotencyRecord:
        packed = json.dumps(result_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE gateway_idempotency SET status='COMPLETE', result_json=?, lease_expires_at=NULL, updated_at=? "
                "WHERE caller_id=? AND idempotency_key=? AND request_hash=? AND status='PENDING' AND owner_token=?",
                (packed, time.time(), caller_id, idempotency_key, request_hash, owner_token),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("idempotency reservation ownership lost during finalize")
        record = self.get(caller_id, idempotency_key)
        assert record is not None
        return record

    def finalize(self, caller_id: str, idempotency_key: str, request_hash: str, result_payload: dict) -> IdempotencyRecord:
        existing = self.get(caller_id, idempotency_key)
        if existing is None:
            raise RuntimeError("idempotency reservation missing during finalize")
        self._assert_same_request(existing, request_hash)
        packed = json.dumps(result_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "UPDATE gateway_idempotency SET status='COMPLETE', result_json=?, lease_expires_at=NULL, updated_at=? "
                "WHERE caller_id=? AND idempotency_key=?",
                (packed, time.time(), caller_id, idempotency_key),
            )
        record = self.get(caller_id, idempotency_key)
        assert record is not None
        return record

    def release_owned(self, caller_id: str, idempotency_key: str, request_hash: str, owner_token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=? AND request_hash=? "
                "AND status='PENDING' AND owner_token=?",
                (caller_id, idempotency_key, request_hash, owner_token),
            )

    def release_pending(self, caller_id: str, idempotency_key: str, request_hash: str) -> None:
        existing = self.get(caller_id, idempotency_key)
        if existing is None:
            return
        self._assert_same_request(existing, request_hash)
        if existing.status == "PENDING":
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
                    (caller_id, idempotency_key),
                )

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
        """Operation-scoped connections require no persistent close action."""
        return None
