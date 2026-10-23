"""Agent-surface registry — where the FRED runtime can be consumed as an agent.

Each entry is a **design contract**, not a live integration. Every surface is
``enabled: false`` and ``approval_required: true`` until an authenticated
gateway, scopes and evidence exist. Nothing here creates an account, holds a
credential, or asserts that a host is connected.

The transport is the runtime's own MCP streamable-http adapter (``/mcp``),
which publishes exactly the capabilities ``RuntimeKernel.list_capabilities()``
authorises for the calling principal.
"""
from __future__ import annotations

from typing import Any

#: Capabilities a governed agent host is allowed to call today.
READ_ONLY_CAPABILITIES: tuple[str, ...] = (
    "runtime.process_turn",
    "s1.cognitive_map",
    "s2.concept_association",
    "runtime.task_planning",
    "sa1.superagent_supervision",
)

AGENT_SURFACES: tuple[dict[str, Any], ...] = (
    {
        "name": "github",
        "host": "GitHub (Copilot coding agent / Actions / custom agent)",
        "transport": "mcp-streamable-http",
        "endpoint_path": "/mcp",
        "auth": {"scheme": "bearer", "secret_env": "FRED_OS_MCP_TOKEN"},
        "enabled": False,
        "approval_required": True,
        "allowed_capabilities": list(READ_ONLY_CAPABILITIES),
        "canonical_state": "external trusted FRED gateway / System-OS, not the host prompt",
        "notes": (
            "Register the FRED MCP endpoint as a repository or organisation MCP server. Read-only "
            "capabilities only; no source export, no credential display and no repository history "
            "transfer without separate explicit authorisation."
        ),
    },
    {
        "name": "supabase",
        "host": "Supabase (project agent / Edge Function MCP client)",
        "transport": "mcp-streamable-http",
        "endpoint_path": "/mcp",
        "auth": {"scheme": "bearer", "secret_env": "FRED_OS_MCP_TOKEN"},
        "enabled": False,
        "approval_required": True,
        "allowed_capabilities": list(READ_ONLY_CAPABILITIES),
        "canonical_state": "external trusted FRED gateway / System-OS, not the database",
        "notes": (
            "Supabase is a data surface, not the canonical System-OS state. Any database write is an "
            "external consequential action and stays behind an independent trusted server-side policy "
            "decision; service-role keys never enter a browser bundle or a Skill."
        ),
    },
    {
        "name": "gemini",
        "host": "Google Gemini (Gemini app / Vertex agent with MCP)",
        "transport": "mcp-streamable-http",
        "endpoint_path": "/mcp",
        "auth": {"scheme": "bearer", "secret_env": "FRED_OS_MCP_TOKEN"},
        "enabled": False,
        "approval_required": True,
        "allowed_capabilities": list(READ_ONLY_CAPABILITIES),
        "canonical_state": "external trusted FRED gateway / System-OS, not the host prompt",
        "notes": (
            "The host foundation model proposes; the runtime validates. Gemini supplies natural-language "
            "inference only — it does not hold FRED memory, authority or evidence."
        ),
    },
    {
        "name": "base44_superagent",
        "host": "Base44 native Superagent (owner-created, private workspace)",
        "transport": "owner-configured connector / custom MCP",
        "endpoint_path": "/mcp",
        "auth": {"scheme": "owner-managed", "secret_env": "BASE44_SUPERAGENT_TOKEN"},
        "enabled": False,
        "approval_required": True,
        "allowed_capabilities": list(READ_ONLY_CAPABILITIES),
        "canonical_state": "external trusted FRED gateway / System-OS, not the host prompt",
        "notes": (
            "Separate product from a Base44 builder app or an in-app agent. Creating it is an owner-side "
            "action in the intended private workspace; this runtime cannot provision one."
        ),
    },
    {
        "name": "superagent_sh",
        "host": "Superagent.sh security workers (optional assurance provider)",
        "transport": "mcp-streamable-http",
        "endpoint_path": "https://www.superagent.sh/mcp",
        "auth": {"scheme": "bearer", "secret_env": "SUPERAGENT_API_KEY"},
        "enabled": False,
        "approval_required": True,
        "allowed_capabilities": ["scan_skill", "scan_mcp", "get_context_score", "scan_package"],
        "canonical_state": "external trusted FRED gateway / System-OS, not the scanner",
        "notes": (
            "Assurance provider, not an agent host and not a Base44-native Superagent. Organisation-wide "
            "keys can grant billable operations; they belong in a server-side secret store. Findings are "
            "reviewable inputs to update-skills, never silent policy changes."
        ),
    },
)


def list_agent_surfaces() -> tuple[dict[str, Any], ...]:
    """Return the registered agent surfaces (deep-copied, so callers cannot mutate the registry)."""
    return tuple({**surface, "auth": dict(surface["auth"]), "allowed_capabilities": list(surface["allowed_capabilities"])} for surface in AGENT_SURFACES)


def get_agent_surface(name: str) -> dict[str, Any]:
    for surface in list_agent_surfaces():
        if surface["name"] == str(name):
            return surface
    raise KeyError(f"Unknown agent surface: {name}")


def surface_summary() -> list[dict[str, Any]]:
    """Compact projection used inside runtime turn output."""
    return [
        {
            "name": surface["name"],
            "transport": surface["transport"],
            "enabled": surface["enabled"],
            "approval_required": surface["approval_required"],
        }
        for surface in AGENT_SURFACES
    ]
