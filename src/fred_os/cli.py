"""Command-line clients and transport entrances for FRED OS."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from fred_os.gateway import CommandGateway, GatewayRequest, IdempotencyStore, TokenAuthenticator
from fred_os.runtime import RuntimeKernel
from fred_os.superagent import ACTORS, SUPPORTED_TARGET_KINDS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fred", description="FRED OS gateway and MCP transport client")
    parser.add_argument("--root", default=".", help="FRED OS runtime root")
    parser.add_argument("--profile", default="development", help="runtime configuration profile")
    parser.add_argument("--auth-registry", default=None, help="JSON registry containing SHA-256 token hashes")
    parser.add_argument("--token", default=None, help="gateway token; prefer FRED_OS_TOKEN environment variable")
    parser.add_argument("--idempotency-store", default=None, help="SQLite idempotency store path")

    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute one capability")
    run.add_argument("--capability", default="runtime.process_turn")
    run.add_argument("--input", required=True)
    run.add_argument("--idempotency-key", default=None)
    run.add_argument("--command-id", default=None)
    run.add_argument("--session-id", default=None)

    mcp = subparsers.add_parser("mcp", help="Model Context Protocol transport adapter")
    mcp_subparsers = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_subparsers.add_parser("serve", help="serve authorized FRED OS capabilities over MCP")
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument("--session-id", default=None)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    superagent = subparsers.add_parser(
        "superagent",
        help="Superagent Integration Fabric tools (offline, plan-only; no kernel boot)",
    )
    superagent_sub = superagent.add_subparsers(dest="superagent_command", required=True)

    preflight = superagent_sub.add_parser(
        "preflight", help="plan an approval-gated security review; never dispatches a scan"
    )
    preflight.add_argument("--kind", required=True, choices=list(SUPPORTED_TARGET_KINDS))
    preflight.add_argument("--target", required=True)
    preflight.add_argument("--sensitivity", default="public")
    preflight.add_argument("--owner-approved", action="store_true")
    preflight.add_argument("--reason", default="")

    surfaces = superagent_sub.add_parser("surfaces", help="list registered agent surfaces")
    surfaces.add_argument("--name", default=None)

    caseweave = superagent_sub.add_parser(
        "caseweave", help="compose a review-only CaseWeave draft note and supervise it"
    )
    caseweave.add_argument("--actor", default="HACLA", choices=sorted(ACTORS))
    caseweave.add_argument("--case-file", default=None, help="JSON case fixture; defaults to the synthetic DEMO fixture")
    caseweave.add_argument("--consent", action="store_true")
    caseweave.add_argument("--review-approved", action="store_true")

    supervise = superagent_sub.add_parser(
        "supervise", help="run K/P/G supervision over a JSON trace bundle"
    )
    supervise.add_argument("--bundle", default="-", help="path to a JSON bundle, or - for stdin")
    return parser


def _run_superagent(args: argparse.Namespace) -> int:
    """Offline, plan-only Superagent Fabric tools. No kernel, gateway or network."""
    from fred_os.superagent import (
        ScanRequest,
        compose_agency_note,
        get_agent_surface,
        list_agent_surfaces,
        plan_security_check,
        supervise,
        supervise_caseweave,
    )

    if args.superagent_command == "preflight":
        plan = plan_security_check(
            ScanRequest(
                kind=args.kind,
                target=args.target,
                sensitivity=args.sensitivity,
                owner_approved_external_submission=args.owner_approved,
                reason=args.reason,
            )
        )
        payload = {
            "target_kind": plan.target_kind,
            "target": plan.target,
            "recommended_interface": plan.recommended_interface,
            "status": plan.status,
            "can_dispatch": plan.can_dispatch,
            "evidence_status": plan.evidence_status,
            "note": plan.note,
            "dispatch_available": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    if args.superagent_command == "surfaces":
        if args.name:
            print(json.dumps(get_agent_surface(args.name), indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print(json.dumps(list(list_agent_surfaces()), indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    if args.superagent_command == "caseweave":
        case_data = None
        if args.case_file:
            case_data = json.loads(Path(args.case_file).read_text(encoding="utf-8"))
        note = compose_agency_note(
            args.actor,
            case_data,
            consent_to_share=args.consent,
            review_approved=args.review_approved,
        )
        report = supervise_caseweave(
            case_data,
            actor_id=args.actor,
            consent_to_share=args.consent,
            review_approved=args.review_approved,
        )
        print(
            json.dumps(
                {"actor": args.actor, "note": note, "supervision": report},
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        return 0

    if args.superagent_command == "supervise":
        raw = sys.stdin.read() if args.bundle == "-" else Path(args.bundle).read_text(encoding="utf-8")
        bundle = json.loads(raw or "{}")
        print(json.dumps(supervise(bundle, bundle_id=str(bundle.get("bundle_id", "cli"))), indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    return 2


def _build_gateway(args: argparse.Namespace, token: str) -> tuple[RuntimeKernel, CommandGateway]:
    root = Path(args.root).resolve()
    session_id = getattr(args, "session_id", None)
    kernel = RuntimeKernel.boot(root_dir=root, profile=args.profile, session_id=session_id)
    store_path = Path(args.idempotency_store) if args.idempotency_store else root / "data" / "gateway_idempotency.sqlite3"
    gateway = CommandGateway(
        kernel,
        TokenAuthenticator.from_file(args.auth_registry),
        IdempotencyStore(
            store_path,
            busy_timeout_ms=int(kernel.config.get("gateway.idempotency_busy_timeout_ms", 10_000)),
            lease_seconds=float(kernel.config.get("gateway.idempotency_lease_seconds", 30.0)),
            wait_seconds=float(kernel.config.get("gateway.idempotency_wait_seconds", 30.0)),
            poll_seconds=float(kernel.config.get("gateway.idempotency_poll_seconds", 0.025)),
        ),
    )
    gateway.authenticator.authenticate(token)
    return kernel, gateway


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    # The Superagent Fabric tools are offline and plan-only: they need no token,
    # no auth registry, no kernel boot and no network.
    if args.command == "superagent":
        try:
            return _run_superagent(args)
        except Exception as exc:
            print(json.dumps({"error": exc.__class__.__name__, "message": str(exc)}), file=sys.stderr)
            return 2

    if not args.auth_registry:
        print(json.dumps({"error": "--auth-registry is required"}), file=sys.stderr)
        return 2

    token = args.token or os.environ.get("FRED_OS_TOKEN", "")
    if not token:
        print(json.dumps({"error": "gateway token required via FRED_OS_TOKEN or --token"}), file=sys.stderr)
        return 2

    kernel: RuntimeKernel | None = None
    gateway: CommandGateway | None = None
    try:
        kernel, gateway = _build_gateway(args, token)
        if args.command == "run":
            response = gateway.execute(
                GatewayRequest(
                    target_capability=args.capability,
                    payload={"input": args.input},
                    idempotency_key=args.idempotency_key or f"ik-{uuid.uuid4().hex}",
                    token=token,
                    session_id=args.session_id,
                    command_id=args.command_id,
                )
            )
            print(json.dumps(response.to_dict(), sort_keys=True, ensure_ascii=False))
            return 0

        if args.command == "mcp" and args.mcp_command == "serve":
            from fred_os.mcp import MCPAdapterConfig, build_mcp_server, build_streamable_http_app, run_stdio_server

            server = build_mcp_server(
                gateway,
                MCPAdapterConfig(token=token, session_id=args.session_id),
            )
            if args.transport == "stdio":
                asyncio.run(run_stdio_server(server))
                return 0

            try:
                import uvicorn
            except ImportError as exc:  # pragma: no cover - packaging path
                raise RuntimeError("streamable-http requires `pip install 'fred-os[http]'`") from exc
            uvicorn.run(build_streamable_http_app(server), host=args.host, port=args.port, workers=1)
            return 0
        return 2
    except Exception as exc:
        print(json.dumps({"error": exc.__class__.__name__, "message": str(exc)}), file=sys.stderr)
        return 2
    finally:
        if gateway is not None:
            gateway.close()
        if kernel is not None:
            kernel.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
