"""Small date helpers shared by the pipeline and the API."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

AMFI_DATE_FORMAT = "%d-%b-%Y"
API_DATE_FORMAT = "%d-%m-%Y"
ISO_DATE_FORMAT = "%Y-%m-%d"


def parse_amfi_date(value: str) -> date:
    """Parse AMFI's ``20-Nov-2026`` style dates."""

    return datetime.strptime(value.strip(), AMFI_DATE_FORMAT).date()


def parse_flexible_date(value: str) -> date:
    """Accept ``YYYY-MM-DD``, ``DD-MM-YYYY`` and AMFI ``DD-Mon-YYYY`` dates."""

    raw = value.strip()
    for fmt in (ISO_DATE_FORMAT, "%d-%m-%Y", AMFI_DATE_FORMAT):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {value!r}. Use YYYY-MM-DD or DD-MM-YYYY.")


def to_iso(value: date) -> str:
    return value.strftime(ISO_DATE_FORMAT)


def from_iso(value: str) -> date:
    return datetime.strptime(value, ISO_DATE_FORMAT).date()


def to_api_date(value: str | date) -> str:
    """Return the DD-MM-YYYY format used by the public API."""

    day = from_iso(value) if isinstance(value, str) else value
    return day.strftime(API_DATE_FORMAT)


def date_chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Split an inclusive date range into chunks of at most ``days`` days."""

    if start > end:
        return []
    days = max(1, days)
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=days - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
