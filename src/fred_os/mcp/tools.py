"""Dynamic CapabilityDescriptor -> MCP Tool projection."""
from __future__ import annotations

from typing import Any, Mapping

import mcp.types as mcp_types

from fred_os.gateway import AuthorizationError, TokenAuthenticator
from fred_os.runtime import RuntimeKernel


def capability_to_mcp_tool(descriptor: Mapping[str, Any]) -> mcp_types.Tool:
    """Translate one runtime capability manifest into an MCP Tool exactly once."""
    schema = descriptor.get("input_schema", {"type": "object", "properties": {}})
    if not isinstance(schema, Mapping):
        schema = {"type": "object", "properties": {}}
    return mcp_types.Tool(
        name=str(descriptor["name"]),
        title=str(descriptor.get("name", "")),
        description=str(descriptor.get("description", "")),
        input_schema=dict(schema),
    )


def list_authorized_tools(
    kernel: RuntimeKernel,
    authenticator: TokenAuthenticator,
    token: str,
) -> list[mcp_types.Tool]:
    """Expose only capabilities the configured MCP principal may execute."""
    principal = authenticator.authenticate(token)
    tools: list[mcp_types.Tool] = []
    for descriptor in kernel.list_capabilities():
        capability = str(descriptor.get("name", ""))
        try:
            authenticator.authorize(
                principal,
                capability,
                descriptor.get("required_permissions", ()),
            )
        except AuthorizationError:
            continue
        tools.append(capability_to_mcp_tool(descriptor))
    return tools
