"""M2 Model Context Protocol adapter for FRED OS."""

from .server import MCPAdapterConfig, build_mcp_server, build_streamable_http_app, run_stdio_server
from .tools import capability_to_mcp_tool, list_authorized_tools
from .translator import format_gateway_response_for_mcp, mcp_call_to_gateway_request

__all__ = [
    "MCPAdapterConfig",
    "build_mcp_server",
    "build_streamable_http_app",
    "run_stdio_server",
    "capability_to_mcp_tool",
    "list_authorized_tools",
    "mcp_call_to_gateway_request",
    "format_gateway_response_for_mcp",
]
