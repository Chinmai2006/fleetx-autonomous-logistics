import hmac
from typing import Literal

from fastapi import Header, HTTPException

from app.core.config import settings
from app.services.audit_log import audit_log


def require_role(authorization: str | None = Header(default=None)) -> Literal["operator", "admin"]:
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else ""
    admin_token = settings.API_ADMIN_TOKEN
    operator_token = settings.API_OPERATOR_TOKEN
    if not admin_token and not operator_token:
        raise HTTPException(status_code=503, detail="Agent administration is disabled until API role tokens are configured")
    if admin_token and hmac.compare_digest(token, admin_token):
        return "admin"
    if operator_token and hmac.compare_digest(token, operator_token):
        return "operator"
    audit_log.record(
        event_type="security.authorization_denied",
        actor="unauthenticated",
        result="denied",
        summary="Unauthorized agent-management request",
        details={},
    )
    raise HTTPException(status_code=401, detail="A valid operator or admin bearer token is required")


def require_admin(authorization: str | None = Header(default=None)) -> Literal["admin"]:
    role = require_role(authorization)
    if role != "admin":
        audit_log.record(
            event_type="security.authorization_denied",
            actor="operator",
            result="denied",
            summary="Operator attempted an admin-only agent operation",
            details={},
        )
        raise HTTPException(status_code=403, detail="Admin role required")
    return "admin"


def require_operator_if_configured(authorization: str | None = Header(default=None)) -> str:
    if not settings.API_ADMIN_TOKEN and not settings.API_OPERATOR_TOKEN:
        return "local-development"
    return require_role(authorization)