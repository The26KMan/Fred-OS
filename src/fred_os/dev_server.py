"""Minimal dev server: HTML status page at / plus MCP streamable-http at /mcp.

This is a development convenience so the runtime is visible in a browser. It
boots the real RuntimeKernel and CommandGateway and delegates MCP traffic to
the production streamable-http ASGI app.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import time
from pathlib import Path
from typing import Any

from fred_os.gateway import CommandGateway, IdempotencyStore, TokenAuthenticator
from fred_os.mcp import MCPAdapterConfig, build_mcp_server, build_streamable_http_app
from fred_os.runtime import RuntimeKernel


def _write_auth_registry(token: str, path: Path) -> None:
    """Generate a one-token auth registry from the dev token."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    registry = {
        "tokens": [
            {
                "token_hash": token_hash,
                "caller_id": "dev",
                "permissions": ["gateway.execute", "capability:*"],
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _render_status_page(kernel: RuntimeKernel, capabilities: tuple[dict[str, Any], ...]) -> str:
    systems = []
    for system_id in kernel.config.get("systems.enabled"):
        maturity = kernel.config.get(f"systems.maturity.{system_id}", "candidate")
        systems.append((system_id, maturity))

    uptime = time.time() - kernel.booted_at

    cap_rows = "\n".join(
        f"<tr><td><code>{html.escape(c['name'])}</code></td>"
        f"<td>{html.escape(c.get('description', ''))}</td>"
        f"<td><span class='badge'>{html.escape(c.get('version', ''))}</span></td></tr>"
        for c in capabilities
    )
    sys_rows = "\n".join(
        f"<tr><td><code>{sid}</code></td><td><span class='badge {maturity}'>{maturity}</span></td></tr>"
        for sid, maturity in systems
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRED OS — Runtime Status</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --border:#30363d; --text:#c9d1d9;
           --dim:#8b949e; --accent:#58a6ff; --green:#3fb950; --yellow:#d29922; --red:#f85149; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
          background:var(--bg); color:var(--text); line-height:1.6; padding:2rem; max-width:860px; margin:0 auto; }}
  h1 {{ font-size:1.6rem; font-weight:600; margin-bottom:.25rem; }}
  h1 span {{ color:var(--accent); }}
  .subtitle {{ color:var(--dim); font-size:.9rem; margin-bottom:1.5rem; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-bottom:1.5rem; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:1rem 1.25rem; }}
  .card .label {{ color:var(--dim); font-size:.75rem; text-transform:uppercase; letter-spacing:.05em; }}
  .card .value {{ font-size:1.1rem; font-weight:600; margin-top:.25rem; }}
  .card .value.green {{ color:var(--green); }}
  table {{ width:100%; border-collapse:collapse; margin-top:.5rem; }}
  th {{ text-align:left; color:var(--dim); font-size:.75rem; text-transform:uppercase;
       letter-spacing:.05em; padding:.5rem; border-bottom:1px solid var(--border); }}
  td {{ padding:.5rem; border-bottom:1px solid var(--border); font-size:.9rem; }}
  code {{ font-family:'SF Mono',Monaco,monospace; color:var(--accent); font-size:.85rem; }}
  .badge {{ font-size:.75rem; padding:.1rem .5rem; border-radius:99px;
            background:var(--border); color:var(--dim); }}
  .badge.implemented {{ background:#1a3a2a; color:var(--green); }}
  .badge.implemented_adapter {{ background:#1a3a2a; color:var(--green); }}
  .badge.kernel_governance {{ background:#2a1a3a; color:#a371f7; }}
  .badge.tested_prototype_adapter {{ background:#3a3a1a; color:var(--yellow); }}
  .badge.candidate {{ background:#3a1a1a; color:var(--red); }}
  .section-title {{ font-size:1.1rem; font-weight:600; margin:1.5rem 0 .5rem; }}
  .mcp-note {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
               padding:1rem 1.25rem; margin-top:1.5rem; }}
  .mcp-note code {{ color:var(--green); }}
  footer {{ margin-top:2rem; color:var(--dim); font-size:.8rem; }}
</style>
</head>
<body>
  <h1>FRED OS <span>vNext</span></h1>
  <p class="subtitle">Evidence-governed System-OS runtime with Semantic Memory Lake and immutable DeepLinks.</p>

  <div class="grid">
    <div class="card"><div class="label">Status</div><div class="value green">{html.escape(kernel.status)}</div></div>
    <div class="card"><div class="label">Profile</div><div class="value">{html.escape(kernel.config.get('meta.profile', ''))}</div></div>
    <div class="card"><div class="label">Uptime</div><div class="value">{uptime:.1f}s</div></div>
    <div class="card"><div class="label">Config Hash</div><div class="value" style="font-size:.8rem;font-family:monospace">{html.escape(kernel.config.config_hash[:16])}…</div></div>
  </div>

  <div class="section-title">Capabilities</div>
  <table><thead><tr><th>Name</th><th>Description</th><th>Version</th></tr></thead><tbody>{cap_rows}</tbody></table>

  <div class="section-title">Systems</div>
  <table><thead><tr><th>System</th><th>Maturity</th></tr></thead><tbody>{sys_rows}</tbody></table>

  <div class="mcp-note">
    <strong>MCP endpoint:</strong> <code>POST /mcp</code><br>
    <span style="color:var(--dim);font-size:.85rem">Streamable-HTTP transport for authorized FRED OS capabilities.</span>
  </div>

  <footer>FRED OS vNext — runtime booted from frozen TOML configuration.</footer>
</body>
</html>"""


def build_app() -> Any:
    """Boot the kernel + gateway and return a combined ASGI app."""
    root = Path(os.environ.get("FRED_OS_ROOT", ".")).resolve()
    profile = os.environ.get("FRED_OS_PROFILE", "development")
    token = os.environ["FRED_OS_TOKEN"]

    auth_path = root / "config" / "auth_registry.json"
    _write_auth_registry(token, auth_path)

    kernel = RuntimeKernel.boot(root_dir=root, profile=profile)
    gateway = CommandGateway(
        kernel,
        TokenAuthenticator.from_file(auth_path),
        IdempotencyStore(
            root / "data" / "gateway_idempotency.sqlite3",
            busy_timeout_ms=int(kernel.config.get("gateway.idempotency_busy_timeout_ms", 10_000)),
            lease_seconds=float(kernel.config.get("gateway.idempotency_lease_seconds", 30.0)),
            wait_seconds=float(kernel.config.get("gateway.idempotency_wait_seconds", 30.0)),
            poll_seconds=float(kernel.config.get("gateway.idempotency_poll_seconds", 0.025)),
        ),
    )
    gateway.authenticator.authenticate(token)

    mcp_server = build_mcp_server(gateway, MCPAdapterConfig(token=token))
    mcp_app = build_streamable_http_app(mcp_server)
    capabilities = kernel.list_capabilities()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            if path in ("/", "/health"):
                body = _render_status_page(kernel, capabilities).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/html; charset=utf-8"]],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await mcp_app(scope, receive, send)

    return app
