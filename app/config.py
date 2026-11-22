"""
Centralized configuration for the Codeforces MCP Server.

All settings are loaded from environment variables (optionally via a .env
file) and exposed with typed defaults. No credentials are required: this
server is a strictly read-only consumer of the public Codeforces API.
"""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


class Config:
    """Application configuration loaded from environment variables."""

    # ── Codeforces API ─────────────────────────────────────────────
    CODEFORCES_API_URL: str = os.getenv("CODEFORCES_API_URL", "https://codeforces.com/api")
    CODEFORCES_BASE_URL: str = "https://codeforces.com"

    # Codeforces returns Russian problem/contest names unless lang=en is sent.
    CODEFORCES_LANG: str = os.getenv("CODEFORCES_LANG", "en")

    # ── Server ─────────────────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # ── HTTP behaviour ─────────────────────────────────────────────
    REQUEST_TIMEOUT: float = float(os.getenv("REQUEST_TIMEOUT", "30.0"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

    # Codeforces allows roughly one request every two seconds per client.
    MIN_REQUEST_INTERVAL: float = float(os.getenv("MIN_REQUEST_INTERVAL", "1.1"))

    # ── Caching ────────────────────────────────────────────────────
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "600"))              # 10 minutes
    PROBLEMSET_TTL: int = int(os.getenv("PROBLEMSET_TTL", "1800"))   # 30 minutes
    MAX_CACHE_ENTRIES: int = int(os.getenv("MAX_CACHE_ENTRIES", "64"))

    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "codeforces-mcp/1.0 (+https://github.com/iamrudhresh/mcp-server-codeforces)",
    )

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return a list of human-readable warnings."""
        warnings: list[str] = []
        if cls.MIN_REQUEST_INTERVAL < 1.0:
            warnings.append(
                "MIN_REQUEST_INTERVAL is below 1.0s; Codeforces may reply "
                "'call limit exceeded'."
            )
        if cls.REQUEST_TIMEOUT < 5:
            warnings.append("REQUEST_TIMEOUT is very low; large responses may time out.")
        return warnings


config = Config()
