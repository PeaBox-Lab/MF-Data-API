"""Configuration helpers for the MF Data API ingestion pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT_DIR / "data"

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
NAV_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (ROOT_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    """Runtime settings for downloads, storage and exports."""

    data_dir: Path = DEFAULT_DATA_DIR
    db_override: Path | None = None
    navall_url: str = NAVALL_URL
    history_url: str = NAV_HISTORY_URL
    request_timeout: float = 120.0
    retries: int = 3
    chunk_days: int = 30
    bootstrap_days: int = 1095
    incremental_days: int = 7
    raw_retention_days: int = 90
    user_agent: str = (
        "MFDataAPI/1.0 (+https://github.com/; open-source mutual fund NAV API)"
    )

    @property
    def db_path(self) -> Path:
        return self.db_override or (self.data_dir / "mfdata.db")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def status_path(self) -> Path:
        return self.data_dir / "status.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Build settings from environment variables (safe to call repeatedly)."""

    data_dir = _env_path("MFDATA_DATA_DIR", DEFAULT_DATA_DIR)
    db_override: Path | None = None
    raw_db = os.getenv("MFDATA_DB")
    if raw_db and raw_db.strip():
        db_override = Path(raw_db).expanduser()
        if not db_override.is_absolute():
            db_override = (ROOT_DIR / db_override).resolve()

    return Settings(
        data_dir=data_dir,
        db_override=db_override,
        request_timeout=_env_float("MFDATA_REQUEST_TIMEOUT", 120.0),
        retries=max(1, _env_int("MFDATA_RETRIES", 3)),
        chunk_days=max(1, min(90, _env_int("MFDATA_CHUNK_DAYS", 30))),
        bootstrap_days=max(1, _env_int("MFDATA_BOOTSTRAP_DAYS", 1095)),
        incremental_days=max(0, _env_int("MFDATA_INCREMENTAL_DAYS", 7)),
        raw_retention_days=max(0, _env_int("MFDATA_RAW_RETENTION_DAYS", 90)),
        user_agent=os.getenv("MFDATA_USER_AGENT", Settings.user_agent),
    )
