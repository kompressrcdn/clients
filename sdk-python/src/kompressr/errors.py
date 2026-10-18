"""Safe error metadata; response bodies and request credentials are never retained."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal, NoReturn

ErrorKind = Literal["validation", "api", "network", "timeout", "cancelled", "invalid_response", "processing"]


class KompressrError(Exception):
    def __init__(self, message: str, *, kind: ErrorKind, code: str,
                 status: int | None = None, retry_after_ms: float | None = None,
                 asset_id: int | None = None, may_have_succeeded: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.status = status
        self.retry_after_ms = retry_after_ms
        self.asset_id = asset_id
        self.may_have_succeeded = may_have_succeeded

    def to_dict(self) -> dict[str, Any]:
        return {"name": type(self).__name__, "message": str(self), "kind": self.kind,
                "code": self.code, "status": self.status, "retry_after_ms": self.retry_after_ms,
                "asset_id": self.asset_id, "may_have_succeeded": self.may_have_succeeded}


class KompressrCancelledError(asyncio.CancelledError):
    """Native task cancellation remains cancellation, with safe recovery metadata."""

    def __init__(self, *, code: str = "REQUEST_CANCELLED", asset_id: int | None = None,
                 status: int | None = None, retry_after_ms: float | None = None, may_have_succeeded: bool = False) -> None:
        super().__init__("Operation cancelled; accepted server work is not rolled back.")
        self.kind: ErrorKind = "cancelled"
        self.code = code
        self.asset_id = asset_id
        self.status = status
        self.retry_after_ms = retry_after_ms
        self.may_have_succeeded = may_have_succeeded

    def to_dict(self) -> dict[str, Any]:
        return {"name": type(self).__name__, "message": str(self), "kind": self.kind,
                "code": self.code, "status": self.status, "retry_after_ms": self.retry_after_ms,
                "asset_id": self.asset_id, "may_have_succeeded": self.may_have_succeeded}


def invalid(message: str) -> NoReturn:
    raise KompressrError(message, kind="validation", code="INVALID_ARGUMENT")


def invalid_response(message: str = "The API returned an invalid response.") -> NoReturn:
    raise KompressrError(message, kind="invalid_response", code="INVALID_RESPONSE")


def safe_message(message: object, secret: str = "") -> str:
    if not isinstance(message, str):
        return "Kompressr request failed."
    value = message.replace(secret, "[redacted]") if secret else message
    value = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", value, flags=re.I)
    value = re.sub(r"https?://[^\s<>\"']+", "[URL redacted]", value, flags=re.I)
    value = re.sub(r"\b(?:api_key|password|token|secret|signature)\s*[=:]\s*\S+",
                   "[credential redacted]", value, flags=re.I)
    return value[:500]
