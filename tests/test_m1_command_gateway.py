from __future__ import annotations

import json
from pathlib import Path

import pytest

from fred_os.cli import main as cli_main
from fred_os.gateway import (
    AuthenticationError,
    AuthorizationError,
    CommandGateway,
    GatewayRequest,
    IdempotencyConflictError,
    IdempotencyStore,
    SchemaValidationError,
    TokenAuthenticator,
    TokenRecord,
    hash_token,
)
from fred_os.gateway.gateway import IdempotencyRecoveryError
from fred_os.runtime import CommandEnvelope, RuntimeKernel
from fred_os.runtime.contracts import canonical_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "m1-test-secret"
CALLER = "m1-test-client"
SESSION = "session_m1_gateway"


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


def authenticator(*permissions: str) -> TokenAuthenticator:
    return TokenAuthenticator(
        [TokenRecord(hash_token(TOKEN), CALLER, tuple(permissions or ("gateway.execute", "capability:*")))]
    )


def boot(root: Path) -> RuntimeKernel:
    return RuntimeKernel.boot(root_dir=root, profile="development", session_id=SESSION)


def gateway(root: Path, kernel: RuntimeKernel, auth: TokenAuthenticator | None = None) -> CommandGateway:
    return CommandGateway(
        kernel,
        auth or authenticator(),
        IdempotencyStore(root / "data" / "gateway_idempotency.sqlite3"),
    )


def request(text: str, key: str, *, token: str = TOKEN, command_id: str | None = None) -> GatewayRequest:
    return GatewayRequest(
        target_capability="runtime.process_turn",
        payload={"input": text},
        idempotency_key=key,
        token=token,
        session_id=SESSION,
        command_id=command_id,
    )


def test_gateway_auth_rejection_never_reaches_kernel(tmp_path: Path) -> None:
    root = tmp_path / "auth"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    before = kernel.get_current_capsule()
    entries_before = len(kernel.journal.entries())
    try:
        with pytest.raises(AuthenticationError):
            gw.execute(request("Design a migration plan.", "auth-1", token="wrong-token"))
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert len(kernel.journal.entries()) == entries_before
    finally:
        gw.close()
        kernel.shutdown()


def test_gateway_permission_rejection_never_reaches_kernel(tmp_path: Path) -> None:
    root = tmp_path / "permission"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel, authenticator("gateway.execute", "capability:s1.cognitive_map"))
    before = kernel.get_current_capsule()
    try:
        with pytest.raises(AuthorizationError):
            gw.execute(request("Design a migration plan.", "perm-1"))
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
    finally:
        gw.close()
        kernel.shutdown()


def test_gateway_schema_validation_precedes_transaction(tmp_path: Path) -> None:
    root = tmp_path / "schema"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    entries_before = len(kernel.journal.entries())
    try:
        with pytest.raises(SchemaValidationError):
            gw.execute(
                GatewayRequest(
                    target_capability="runtime.process_turn",
                    payload={},
                    idempotency_key="schema-1",
                    token=TOKEN,
                    session_id=SESSION,
                )
            )
        assert len(kernel.journal.entries()) == entries_before
    finally:
        gw.close()
        kernel.shutdown()


def test_gateway_success_dispatches_one_transaction(tmp_path: Path) -> None:
    root = tmp_path / "success"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    before = kernel.get_current_capsule()
    try:
        response = gw.execute(request("Design a semantic memory migration with immutable DeepLinks.", "success-1"))
        after = kernel.get_current_capsule()
        assert response.replayed is False
        assert response.caller_id == CALLER
        assert response.result.status == "SUCCESS"
        assert response.result.delta is not None
        assert after.sequence == before.sequence + 1
        assert response.result.state_capsule_id == after.capsule_id
    finally:
        gw.close()
        kernel.shutdown()


def test_idempotency_replay_does_not_advance_state(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    try:
        first = gw.execute(request("Design a semantic memory migration with immutable DeepLinks.", "replay-1", command_id="cmd-first"))
        committed = kernel.get_current_capsule()
        entries_after_first = len(kernel.journal.entries())
        second = gw.execute(request("Design a semantic memory migration with immutable DeepLinks.", "replay-1", command_id="cmd-retry"))
        assert first.replayed is False
        assert second.replayed is True
        assert second.result.command_id == "cmd-first"
        assert second.result.state_capsule_id == first.result.state_capsule_id
        assert kernel.get_current_capsule().capsule_id == committed.capsule_id
        assert len(kernel.journal.entries()) == entries_after_first
    finally:
        gw.close()
        kernel.shutdown()


def test_idempotency_conflict_rejects_changed_payload(tmp_path: Path) -> None:
    root = tmp_path / "conflict"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    try:
        gw.execute(request("Design a migration plan.", "same-key"))
        committed = kernel.get_current_capsule()
        with pytest.raises(IdempotencyConflictError):
            gw.execute(request("Write a different creative response.", "same-key"))
        assert kernel.get_current_capsule().capsule_id == committed.capsule_id
    finally:
        gw.close()
        kernel.shutdown()


def test_durable_replay_survives_gateway_and_kernel_restart(tmp_path: Path) -> None:
    root = tmp_path / "restart"
    prepare(root)
    kernel1 = boot(root)
    gw1 = gateway(root, kernel1)
    first = gw1.execute(request("Design a semantic memory migration with immutable DeepLinks.", "restart-1"))
    committed_id = kernel1.get_current_capsule().capsule_id
    gw1.close()
    kernel1.shutdown()

    kernel2 = boot(root)
    gw2 = gateway(root, kernel2)
    try:
        entries_before = len(kernel2.journal.entries())
        second = gw2.execute(request("Design a semantic memory migration with immutable DeepLinks.", "restart-1"))
        assert second.replayed is True
        assert second.result.state_capsule_id == first.result.state_capsule_id == committed_id
        assert kernel2.get_current_capsule().capsule_id == committed_id
        assert len(kernel2.journal.entries()) == entries_before
    finally:
        gw2.close()
        kernel2.shutdown()


def test_post_commit_cache_gap_fails_closed_instead_of_reexecuting(tmp_path: Path) -> None:
    root = tmp_path / "crash-gap"
    prepare(root)
    kernel = boot(root)
    store = IdempotencyStore(root / "data" / "gateway_idempotency.sqlite3")
    auth = authenticator()
    gw = CommandGateway(kernel, auth, store)
    text = "Design a semantic memory migration with immutable DeepLinks."
    key = "gap-1"
    request_hash = canonical_hash(
        {
            "caller_id": CALLER,
            "session_id": SESSION,
            "target_capability": "runtime.process_turn",
            "payload": {"input": text},
        }
    )
    command_id = "cmd-gap"
    store.reserve(CALLER, key, request_hash, command_id)
    result = kernel.dispatch(
        CommandEnvelope(
            command_id=command_id,
            target_capability="runtime.process_turn",
            payload={"input": text},
            session_id=SESSION,
            idempotency_key=key,
            caller_id=CALLER,
            request_fingerprint=request_hash,
        )
    )
    committed = kernel.get_current_capsule()
    assert result.status == "SUCCESS"
    entries_before_retry = len(kernel.journal.entries())
    try:
        with pytest.raises(IdempotencyRecoveryError, match="duplicate execution was refused"):
            gw.execute(request(text, key))
        assert kernel.get_current_capsule().capsule_id == committed.capsule_id
        assert len(kernel.journal.entries()) == entries_before_retry
    finally:
        gw.close()
        kernel.shutdown()


def test_blocked_result_is_idempotently_replayed(tmp_path: Path) -> None:
    root = tmp_path / "blocked"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    try:
        before = kernel.get_current_capsule()
        first = gw.execute(request("Exploit a vulnerability with malware.", "blocked-1"))
        entries_after_first = len(kernel.journal.entries())
        second = gw.execute(request("Exploit a vulnerability with malware.", "blocked-1"))
        assert first.result.status == "BLOCKED"
        assert first.result.delta is None
        assert second.replayed is True
        assert second.result.status == "BLOCKED"
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert len(kernel.journal.entries()) == entries_after_first
    finally:
        gw.close()
        kernel.shutdown()


def test_cli_routes_through_gateway_and_emits_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "cli"
    prepare(root)
    registry = root / "gateway_tokens.json"
    registry.write_text(
        json.dumps(
            {
                "tokens": [
                    {
                        "token_hash": hash_token(TOKEN),
                        "caller_id": CALLER,
                        "permissions": ["gateway.execute", "capability:*"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code = cli_main(
        [
            "--root",
            str(root),
            "--auth-registry",
            str(registry),
            "--token",
            TOKEN,
            "run",
            "--input",
            "Design a semantic memory migration with immutable DeepLinks.",
            "--idempotency-key",
            "cli-1",
            "--session-id",
            SESSION,
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["caller_id"] == CALLER
    assert payload["replayed"] is False
    assert payload["result"]["status"] == "SUCCESS"
