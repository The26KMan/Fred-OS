from __future__ import annotations

import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from fred_os.runtime import CommandEnvelope, RuntimeJournal, RuntimeKernel, StateStore


REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "session_m2_1_concurrency"
TOKEN = "m2-1-concurrency-secret"


WORKER_CODE = r'''
from __future__ import annotations
import json
from pathlib import Path
import sys
import time

from fred_os.gateway import CommandGateway, GatewayRequest, IdempotencyStore, TokenAuthenticator, TokenRecord, hash_token
from fred_os.runtime import RuntimeKernel

root = Path(sys.argv[1])
key = sys.argv[2]
text = sys.argv[3]
delay = float(sys.argv[4])
start_at = float(sys.argv[5])
lease_seconds = float(sys.argv[6])
wait_seconds = float(sys.argv[7])
session = sys.argv[8]
token = sys.argv[9]

while time.time() < start_at:
    time.sleep(0.002)

kernel = RuntimeKernel.boot(root_dir=root, profile="development", session_id=session)
auth = TokenAuthenticator([
    TokenRecord(hash_token(token), "multiprocess-worker", ("gateway.execute", "capability:*"))
])
store = IdempotencyStore(
    root / "data" / "gateway_idempotency.sqlite3",
    busy_timeout_ms=5000,
    lease_seconds=lease_seconds,
    wait_seconds=wait_seconds,
    poll_seconds=0.01,
)
gateway = CommandGateway(kernel, auth, store)

if delay > 0:
    original = kernel._execute_turn
    def delayed(raw_input, command_id):
        print("TX_ACTIVE " + command_id, flush=True)
        time.sleep(delay)
        return original(raw_input, command_id)
    kernel._execute_turn = delayed

try:
    response = gateway.execute(
        GatewayRequest(
            target_capability="runtime.process_turn",
            payload={"input": text},
            idempotency_key=key,
            token=token,
            session_id=session,
        )
    )
    print("RESULT " + json.dumps(response.to_dict(), sort_keys=True), flush=True)
except BaseException as exc:
    print("ERROR " + exc.__class__.__name__ + ": " + str(exc), flush=True)
    raise
finally:
    gateway.close()
    kernel.shutdown()
'''


def prepare(root: Path) -> None:
    (root / "config" / "profiles").mkdir(parents=True)
    (root / "config" / "systemos_base.toml").write_text(
        (REPO_ROOT / "config" / "systemos_base.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "config" / "profiles" / "development.toml").write_text(
        (REPO_ROOT / "config" / "profiles" / "development.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def spawn_worker(
    root: Path,
    key: str,
    text: str,
    *,
    delay: float = 0.0,
    start_at: float | None = None,
    lease_seconds: float = 2.0,
    wait_seconds: float = 5.0,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            WORKER_CODE,
            str(root),
            key,
            text,
            str(delay),
            str(start_at or 0.0),
            str(lease_seconds),
            str(wait_seconds),
            SESSION,
            TOKEN,
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def collect(proc: subprocess.Popen[str], *, timeout: float = 30.0) -> tuple[dict, str, str]:
    stdout, stderr = proc.communicate(timeout=timeout)
    if proc.returncode != 0:
        pytest.fail(f"worker exited {proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}")
    result_lines = [line[len("RESULT ") :] for line in stdout.splitlines() if line.startswith("RESULT ")]
    if not result_lines:
        pytest.fail(f"worker produced no RESULT line\nstdout:\n{stdout}\nstderr:\n{stderr}")
    return json.loads(result_lines[-1]), stdout, stderr


def test_simultaneous_process_dispatch_produces_contiguous_capsule_chain(tmp_path: Path) -> None:
    root = tmp_path / "simultaneous"
    prepare(root)
    start_at = time.time() + 0.75
    workers = [
        spawn_worker(
            root,
            f"unique-{index}",
            f"Design semantic memory migration stage {index} with immutable DeepLinks.",
            start_at=start_at,
        )
        for index in range(4)
    ]
    results = [collect(worker)[0] for worker in workers]
    assert all(item["result"]["status"] == "SUCCESS" for item in results)
    assert all(item["replayed"] is False for item in results)

    kernel = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    try:
        assert kernel.get_current_capsule().sequence == 4
        journal_entries = kernel.journal.entries()  # also verifies the hash chain
        commits = [entry for entry in journal_entries if entry.entry_type == "TX_COMMIT"]
        assert [int(entry.payload["capsule_sequence"]) for entry in commits] == [1, 2, 3, 4]
        assert len({entry.payload["capsule_id"] for entry in commits}) == 4

        committed_ids = kernel.journal.committed_capsule_ids()
        capsules = sorted(
            [capsule for capsule in kernel.state_store.all() if capsule.capsule_id in committed_ids],
            key=lambda capsule: capsule.sequence,
        )
        assert [capsule.sequence for capsule in capsules] == [0, 1, 2, 3, 4]
        for previous, current in zip(capsules, capsules[1:]):
            assert current.parent_capsule_id == previous.capsule_id
    finally:
        kernel.shutdown()


def test_same_idempotency_key_race_executes_exactly_once(tmp_path: Path) -> None:
    root = tmp_path / "same-key"
    prepare(root)
    start_at = time.time() + 0.75
    text = "Design a semantic memory migration with immutable DeepLinks."
    workers = [
        spawn_worker(root, "shared-key", text, start_at=start_at, lease_seconds=2.0, wait_seconds=5.0)
        for _ in range(2)
    ]
    results = [collect(worker)[0] for worker in workers]

    assert [item["result"]["status"] for item in results] == ["SUCCESS", "SUCCESS"]
    assert sorted(item["replayed"] for item in results) == [False, True]
    assert len({item["result"]["command_id"] for item in results}) == 1
    assert len({item["result"]["state_capsule_id"] for item in results}) == 1

    kernel = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    try:
        assert kernel.get_current_capsule().sequence == 1
        commits = [entry for entry in kernel.journal.entries() if entry.entry_type == "TX_COMMIT"]
        assert len(commits) == 1
    finally:
        kernel.shutdown()


def test_stale_worker_refreshes_before_dispatch_and_cas_rejects_stale_parent(tmp_path: Path) -> None:
    root = tmp_path / "cas"
    prepare(root)
    first = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    second = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    stale = second.get_current_capsule()
    try:
        result1 = first.dispatch(
            CommandEnvelope(
                command_id="cas-first",
                target_capability="runtime.process_turn",
                payload={"input": "Design semantic memory migration stage one with immutable DeepLinks."},
                session_id=SESSION,
                idempotency_key="cas-first",
            )
        )
        assert result1.status == "SUCCESS"
        with pytest.raises(RuntimeError, match="STATE_CAS_MISMATCH"):
            second._assert_authoritative_tail(stale)

        result2 = second.dispatch(
            CommandEnvelope(
                command_id="cas-second",
                target_capability="runtime.process_turn",
                payload={"input": "Design semantic memory migration stage two with immutable DeepLinks."},
                session_id=SESSION,
                idempotency_key="cas-second",
            )
        )
        assert result2.status == "SUCCESS"
        assert second.get_current_capsule().sequence == 2
        assert result2.delta is not None
        assert result2.delta.prev_capsule_id == result1.state_capsule_id
    finally:
        first.shutdown()
        second.shutdown()


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL/flock recovery proof is POSIX-specific")
def test_sigkill_during_active_transaction_releases_lock_and_recovers_after_lease_expiry(tmp_path: Path) -> None:
    root = tmp_path / "sigkill"
    prepare(root)
    text = "Design a semantic memory migration with immutable DeepLinks."
    crashed = spawn_worker(
        root,
        "crash-key",
        text,
        delay=60.0,
        lease_seconds=0.4,
        wait_seconds=2.0,
    )
    assert crashed.stdout is not None

    ready, _, _ = select.select([crashed.stdout], [], [], 15.0)
    if not ready:
        crashed.kill()
        stdout, stderr = crashed.communicate(timeout=5)
        pytest.fail(f"worker never entered transaction\nstdout:\n{stdout}\nstderr:\n{stderr}")
    marker = crashed.stdout.readline().strip()
    assert marker.startswith("TX_ACTIVE ")
    crashed_command_id = marker.split(" ", 1)[1]

    os.kill(crashed.pid, signal.SIGKILL)
    crashed.wait(timeout=5)
    time.sleep(0.65)  # allow the dead gateway reservation lease to expire

    retry = spawn_worker(
        root,
        "crash-key",
        text,
        lease_seconds=0.4,
        wait_seconds=2.0,
    )
    retry_result, _, _ = collect(retry, timeout=30)
    assert retry_result["result"]["status"] == "SUCCESS"
    assert retry_result["replayed"] is False

    kernel = RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)
    try:
        assert kernel.get_current_capsule().sequence == 1
        interrupted = kernel.reconcile_wal()
        assert any(item["command_id"] == crashed_command_id for item in interrupted)
        commits = [entry for entry in kernel.journal.entries() if entry.entry_type == "TX_COMMIT"]
        assert len(commits) == 1
        assert commits[0].payload["capsule_sequence"] == 1
    finally:
        kernel.shutdown()

    with sqlite3.connect(root / "data" / "gateway_idempotency.sqlite3") as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        row = connection.execute(
            "SELECT status,result_json FROM gateway_idempotency WHERE caller_id=? AND idempotency_key=?",
            ("multiprocess-worker", "crash-key"),
        ).fetchone()
    assert str(mode).lower() == "wal"
    assert row is not None and row[0] == "COMPLETE" and row[1]
