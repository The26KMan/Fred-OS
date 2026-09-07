"""Hashed-token authentication for the M1 Command Gateway."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Iterable

from .contracts import AuthenticationError, AuthorizationError, GatewayPrincipal, TokenRecord


def hash_token(secret: str) -> str:
    if not secret:
        raise ValueError("token secret must be non-empty")
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class TokenAuthenticator:
    def __init__(self, records: Iterable[TokenRecord]) -> None:
        self.records = tuple(records)

    @classmethod
    def from_file(cls, path: str | Path) -> "TokenAuthenticator":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = raw.get("tokens", ()) if isinstance(raw, dict) else ()
        records = [
            TokenRecord(
                token_hash=str(item["token_hash"]),
                caller_id=str(item["caller_id"]),
                permissions=tuple(str(value) for value in item.get("permissions", ())),
            )
            for item in items
        ]
        return cls(records)

    def authenticate(self, token: str) -> GatewayPrincipal:
        digest = hash_token(token)
        for record in self.records:
            if hmac.compare_digest(record.token_hash, digest):
                return GatewayPrincipal(record.caller_id, record.permissions)
        raise AuthenticationError("invalid gateway token")

    @staticmethod
    def authorize(principal: GatewayPrincipal, capability: str, required_permissions: Iterable[str] = ()) -> None:
        permissions = set(principal.permissions)
        if "*" in permissions:
            return
        if "gateway.execute" not in permissions:
            raise AuthorizationError("caller lacks gateway.execute")
        if "capability:*" not in permissions and f"capability:{capability}" not in permissions:
            raise AuthorizationError(f"caller lacks capability permission for {capability}")
        missing = [permission for permission in required_permissions if permission not in permissions]
        if missing:
            raise AuthorizationError(f"caller lacks required permissions: {', '.join(missing)}")
