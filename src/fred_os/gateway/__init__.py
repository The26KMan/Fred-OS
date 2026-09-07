"""M1 Command Gateway public interface."""

from .auth import TokenAuthenticator, hash_token
from .contracts import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotFoundError,
    GatewayError,
    GatewayPrincipal,
    GatewayRequest,
    GatewayResponse,
    IdempotencyConflictError,
    IdempotencyRecord,
    SchemaValidationError,
    TokenRecord,
)
from .gateway import CommandGateway
from .idempotency import IdempotencyStore

__all__ = [
    "CommandGateway",
    "GatewayRequest",
    "GatewayResponse",
    "GatewayPrincipal",
    "TokenRecord",
    "TokenAuthenticator",
    "IdempotencyStore",
    "IdempotencyRecord",
    "hash_token",
    "GatewayError",
    "AuthenticationError",
    "AuthorizationError",
    "SchemaValidationError",
    "CapabilityNotFoundError",
    "IdempotencyConflictError",
]
