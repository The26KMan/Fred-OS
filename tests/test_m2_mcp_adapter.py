from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from mcp import Client, MCPError, StdioServerParameters
from mcp.client.stdio import stdio_client

from fred_os.gateway import CommandGateway, IdempotencyStore, TokenAuthenticator, TokenRecord, hash_token
from fred_os.mcp import MCPAdapterConfig, build_mcp_server
from fred_os.mcp.server import FREDOS_IDEMPOTENCY_META_KEY
from fred_os.runtime import RuntimeKernel


REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "m2-test-secret"
CALLER = "m2-test-client"
SESSION = "session_m2_mcp"


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


def server(gw: CommandGateway, *, token: str = TOKEN):
    return build_mcp_server(gw, MCPAdapterConfig(token=token, session_id=SESSION))


def test_dynamic_tool_discovery_exposes_authorized_capabilities(tmp_path: Path) -> None:
    root = tmp_path / "discovery"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel, authenticator("gateway.execute", "capability:s1.cognitive_map"))

    async def scenario() -> None:
        async with Client(server(gw)) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == {"s1.cognitive_map"}
            tool = listed.tools[0]
            assert tool.input_schema["required"] == ["input"]
            assert "cognitive mapping" in (tool.description or "").lower()

    try:
        asyncio.run(scenario())
    finally:
        gw.close()
        kernel.shutdown()


def test_mcp_tool_call_executes_gateway_and_returns_forensic_projection(tmp_path: Path) -> None:
    root = tmp_path / "call"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    before = kernel.get_current_capsule()

    async def scenario() -> None:
        async with Client(server(gw)) as client:
            result = await client.call_tool(
                "runtime.process_turn",
                {"input": "Design a semantic memory migration with immutable DeepLinks."},
                meta={FREDOS_IDEMPOTENCY_META_KEY: "call-001"},
            )
            assert result.is_error is False
            payload = result.structured_content
            assert isinstance(payload, dict)
            assert payload["status"] == "SUCCESS"
            assert payload["caller_id"] == CALLER
            assert payload["state_capsule_id"] == kernel.get_current_capsule().capsule_id
            assert payload["state_delta"]["prev_capsule_id"] == before.capsule_id
            assert payload["receipts"]
            assert all("proof_hash" in item for item in payload["receipts"])
            assert "memory_context" not in payload

    try:
        asyncio.run(scenario())
        assert kernel.get_current_capsule().sequence == before.sequence + 1
    finally:
        gw.close()
        kernel.shutdown()


def test_mcp_idempotency_meta_replays_without_second_transaction(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)

    async def scenario() -> None:
        async with Client(server(gw)) as client:
            kwargs = {
                "name": "runtime.process_turn",
                "arguments": {"input": "Design a semantic memory migration with immutable DeepLinks."},
                "meta": {FREDOS_IDEMPOTENCY_META_KEY: "stable-tool-call"},
            }
            first = await client.call_tool(**kwargs)
            capsule = kernel.get_current_capsule()
            entries = len(kernel.journal.entries())
            second = await client.call_tool(**kwargs)
            assert first.structured_content["replayed"] is False
            assert second.structured_content["replayed"] is True
            assert second.structured_content["state_capsule_id"] == capsule.capsule_id
            assert kernel.get_current_capsule().capsule_id == capsule.capsule_id
            assert len(kernel.journal.entries()) == entries

    try:
        asyncio.run(scenario())
    finally:
        gw.close()
        kernel.shutdown()


def test_mcp_schema_rejection_is_tool_error_before_transaction(tmp_path: Path) -> None:
    root = tmp_path / "schema"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    entries_before = len(kernel.journal.entries())

    async def scenario() -> None:
        async with Client(server(gw)) as client:
            result = await client.call_tool(
                "runtime.process_turn",
                {},
                meta={FREDOS_IDEMPOTENCY_META_KEY: "schema-error"},
            )
            assert result.is_error is True
            assert result.structured_content["error"] == "SchemaValidationError"

    try:
        asyncio.run(scenario())
        assert len(kernel.journal.entries()) == entries_before
    finally:
        gw.close()
        kernel.shutdown()


def test_mcp_auth_failure_propagates_as_protocol_failure(tmp_path: Path) -> None:
    root = tmp_path / "auth"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)

    async def scenario() -> None:
        async with Client(server(gw, token="wrong-token")) as client:
            with pytest.raises(MCPError):
                await client.list_tools()

    try:
        asyncio.run(scenario())
    finally:
        gw.close()
        kernel.shutdown()


def test_blocked_runtime_result_remains_normal_mcp_result(tmp_path: Path) -> None:
    root = tmp_path / "blocked"
    prepare(root)
    kernel = boot(root)
    gw = gateway(root, kernel)
    before = kernel.get_current_capsule()

    async def scenario() -> None:
        async with Client(server(gw)) as client:
            result = await client.call_tool(
                "runtime.process_turn",
                {"input": "Exploit a vulnerability with malware."},
                meta={FREDOS_IDEMPOTENCY_META_KEY: "blocked-call"},
            )
            assert result.is_error is False
            payload = result.structured_content
            assert payload["status"] == "BLOCKED"
            assert payload["rejection"]["code"] == "GOVERNANCE_REJECT"
            assert payload["state_delta"] is None
            assert payload["state_capsule_id"] == before.capsule_id

    try:
        asyncio.run(scenario())
    finally:
        gw.close()
        kernel.shutdown()


def test_stdio_pipeline_lists_and_calls_tools(tmp_path: Path) -> None:
    root = tmp_path / "stdio"
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

    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "fred_os.cli",
            "--root",
            str(root),
            "--auth-registry",
            str(registry),
            "--token",
            TOKEN,
            "mcp",
            "serve",
            "--transport",
            "stdio",
            "--session-id",
            SESSION,
        ],
        env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
    )

    async def scenario() -> None:
        async with Client(stdio_client(params)) as client:
            listed = await client.list_tools()
            assert "runtime.process_turn" in {tool.name for tool in listed.tools}
            result = await client.call_tool(
                "runtime.process_turn",
                {"input": "Design a deterministic migration plan."},
                meta={FREDOS_IDEMPOTENCY_META_KEY: "stdio-call"},
            )
            assert result.is_error is False
            assert result.structured_content["status"] == "SUCCESS"

    asyncio.run(scenario())
