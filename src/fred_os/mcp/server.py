"""Low-level MCP transport adapter over the M1 CommandGateway.

The low-level SDK is intentional: FRED OS already owns capability schemas, so
M2 publishes those exact schemas rather than re-deriving them from Python type
hints. Cognitive and state semantics remain entirely below CommandGateway.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

import mcp.server.stdio
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

from fred_os.gateway import CommandGateway, GatewayError

from .service import ProbeASGIApp, ServiceDrainingError, ServiceLifecycle, ServiceReadinessProbe
from .tools import list_authorized_tools
from .translator import format_gateway_response_for_mcp, mcp_call_to_gateway_request


FREDOS_IDEMPOTENCY_META_KEY = "fredos/idempotencyKey"


@dataclass(frozen=True)
class MCPAdapterConfig:
    token: str
    session_id: str | None = None
    server_name: str = "fred-os"
    server_version: str = "0.2.2"


def build_mcp_server(
    gateway: CommandGateway,
    config: MCPAdapterConfig,
    *,
    lifecycle: ServiceLifecycle | None = None,
) -> Server[Any]:
    """Build one MCP server whose tools are authorized runtime capabilities."""
    dispatch_lock = asyncio.Lock()
    process_lifecycle = lifecycle or ServiceLifecycle()
    # In-process/stdio callers that do not supply lifecycle ownership are ready
    # immediately. HTTP supplies an explicit STARTING lifecycle; its runner marks
    # READY only after the ASGI socket/lifespan startup has completed.
    if lifecycle is None:
        process_lifecycle.mark_ready()

    async def list_tools(
        _ctx: ServerRequestContext[Any],
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        tools = list_authorized_tools(
            gateway.kernel,
            gateway.authenticator,
            config.token,
        )
        return ListToolsResult(tools=tools)

    async def call_tool(
        ctx: ServerRequestContext[Any],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        arguments = params.arguments or {}
        meta = params.meta or {}
        host_idempotency = meta.get(FREDOS_IDEMPOTENCY_META_KEY)
        tool_call_id = str(host_idempotency) if host_idempotency else str(ctx.request_id)
        request = mcp_call_to_gateway_request(
            tool_name=params.name,
            arguments=arguments,
            token=config.token,
            tool_call_id=tool_call_id,
            session_id=config.session_id,
        )
        try:
            # M2.1 makes shared runtime/idempotency state safe across processes.
            # M2.2 adds drain accounting: once SIGTERM/SIGINT marks this worker
            # DRAINING, no new request may enter this scope, while an already
            # active synchronous gateway call is allowed to reach TX_COMMIT or
            # TX_ABORT before the HTTP worker exits.
            async with dispatch_lock:
                with process_lifecycle.request_scope():
                    response = gateway.execute(request)
        except (GatewayError, ServiceDrainingError) as exc:
            failure = {
                "status": "ERROR",
                "error": exc.__class__.__name__,
                "message": str(exc),
            }
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(failure, sort_keys=True))],
                structured_content=failure,
                is_error=True,
            )

        payload = format_gateway_response_for_mcp(response)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload, sort_keys=True, ensure_ascii=False))],
            structured_content=payload,
            is_error=False,
        )

    server = Server(
        config.server_name,
        version=config.server_version,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    setattr(server, "fred_os_lifecycle", process_lifecycle)
    return server


async def run_stdio_server(server: Server[Any]) -> None:
    """Run one client-spawned MCP stdio server process."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def build_streamable_http_app(
    server: Server[Any],
    *,
    lifecycle: ServiceLifecycle | None = None,
    readiness: ServiceReadinessProbe | None = None,
):
    """Return the MCP ASGI app, optionally wrapped with service probes."""
    app = server.streamable_http_app()
    if lifecycle is None or readiness is None:
        return app
    return ProbeASGIApp(app, lifecycle, readiness)
