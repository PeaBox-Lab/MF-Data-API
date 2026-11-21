"""Application configuration for the FastAPI service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pipeline.config import ROOT_DIR, Settings, load_settings

WEB_DIR = ROOT_DIR / "web"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class AppSettings:
    db_path: Path
    web_dir: Path = WEB_DIR
    title: str = "MF Data API"
    version: str = "1.0.0"
    description: str = (
        "Free, open JSON API for Indian mutual fund NAV data, sourced daily from "
        "AMFI India."
    )
    rate_limit: int = 120
    rate_window: int = 60
    cache_ttl: int = 300
    cors_origins: tuple[str, ...] = ("*",)
    api_prefix: str = "/api/v1"

    @classmethod
    def from_env(cls, pipeline_settings: Settings | None = None) -> AppSettings:
        base = pipeline_settings or load_settings()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("MFDATA_CORS_ORIGINS", "*").split(",")
            if origin.strip()
        ) or ("*",)
        return cls(
            db_path=base.db_path,
            title=os.getenv("MFDATA_TITLE", cls.title),
            version=os.getenv("MFDATA_VERSION", cls.version),
            rate_limit=max(0, _env_int("MFDATA_RATE_LIMIT", 120)),
            rate_window=max(1, _env_int("MFDATA_RATE_WINDOW", 60)),
            cache_ttl=max(0, _env_int("MFDATA_CACHE_TTL", 300)),
            cors_origins=origins,
        )
