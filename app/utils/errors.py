"""
Error taxonomy shared by every Codeforces MCP code path.

Mirrors `src/errors.js` exactly so both runtimes report identical codes.
"""

from typing import Optional


class CodeforcesError(Exception):
    """A Codeforces API or validation failure with a stable machine code."""

    def __init__(
        self,
        message: str,
        code: str = "ERROR",
        status: Optional[int] = None,
        retryable: bool = False,
        retry_after_ms: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms

    def to_dict(self) -> dict:
        """Render the error as a JSON-serializable tool result."""
        return {
            "status": "error",
            "code": self.code,
            "message": self.message,
            "layer": error_layer(self.code),
            "retryable": self.retryable,
            "retryAfterMs": self.retry_after_ms,
        }


def error_layer(code: str) -> str:
    """Which architectural layer an error code belongs to."""
    if code == "NETWORK_TIMEOUT":
        return "transport"
    if code in {"RATE_LIMITED", "NOT_FOUND", "UPSTREAM", "SCHEMA_CHANGED"}:
        return "upstream"
    return "broker"


def is_retryable_code(code: str) -> bool:
    """Whether a backoff retry is worthwhile for this code."""
    return code in {"RATE_LIMITED", "NETWORK_TIMEOUT", "UPSTREAM"}
