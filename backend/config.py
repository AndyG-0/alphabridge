import os
from pathlib import Path
from typing import ClassVar

BASE_DIR = Path(__file__).resolve().parent


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR.parent / 'data' / 'alphabridge.db'}")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "")
    APP_SECRET = os.getenv("APP_SECRET", "dev-insecure-secret-change-me")
    FRED_API_KEY = os.getenv("FRED_API_KEY", "")
    EDGAR_IDENTITY = os.getenv("EDGAR_IDENTITY", "AlphaBridge user@example.com")
    ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "0") == "1"
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    # Same-origin by default (nginx and the Vite dev proxy both serve UI and API from one origin). Comma-separated allowlist.
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # json | text
    CORS_ORIGINS: ClassVar[list[str]] = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    AUTH_MAX_FAILURES = int(os.getenv("AUTH_MAX_FAILURES", "10"))
    AUTH_WINDOW_SECONDS = float(os.getenv("AUTH_WINDOW_SECONDS", "60"))
    TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"  # behind nginx: trust one hop of X-Forwarded-For
