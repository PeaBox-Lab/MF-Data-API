"""Download and parse the AMFI India NAV feeds.

Two public text feeds are used:

* ``NAVAll.txt`` - the latest NAV for every scheme (one line per scheme).
* ``DownloadNAVHistoryReport_Po.aspx`` - historical NAV rows for a date range
  (maximum 90 days per request, all scheme types when ``tp`` is omitted).

Both feeds share the same row shape and are documented in ``docs`` on the site.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date

import httpx

from .config import Settings
from .dates import AMFI_DATE_FORMAT, parse_amfi_date

log = logging.getLogger(__name__)

SECTION_RE = re.compile(
    r"^(Open Ended Schemes|Close Ended Schemes|Interval Fund Schemes)\s*\((.*)\)\s*$",
    re.IGNORECASE,
)
HEADER_PREFIX = "scheme code"
FUND_HOUSE_SUFFIX = "mutual fund"


@dataclass(slots=True)
class SchemeRecord:
    """A single NAV observation together with its scheme metadata."""

    scheme_code: int
    scheme_name: str
    fund_house: str
    scheme_type: str
    scheme_category: str
    isin_growth: str | None
    isin_div_reinvestment: str | None
    nav: float
    nav_date: date


def decode_bytes(raw: bytes) -> str:
    """AMFI serves UTF-8, but a few legacy files are Windows-1252."""

    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(value: str) -> str:
    return " ".join(value.replace("\ufeff", "").split())


def _isin(value: str) -> str | None:
    value = value.strip()
    if not value or value in {"-", "N.A.", "NA", "N/A"}:
        return None
    return value


def _build_name(*parts: str) -> str:
    seen: list[str] = []
    for part in parts:
        part = _clean(part)
        if part and part.lower() not in {item.lower() for item in seen}:
            seen.append(part)
    return " - ".join(seen)


def _parse_nav(value: str) -> float | None:
    value = value.strip().replace(",", "")
    if not value or value.upper() in {"N.A.", "NA", "N/A", "-"}:
        return None
    try:
        nav = float(value)
    except ValueError:
        return None
    if nav <= 0:
        return None
    return nav


def _split_row(line: str) -> list[str] | None:
    parts = [part.strip() for part in line.split(";")]
    if len(parts) < 8:
        return None
    if len(parts) > 8:
        # Very rare: a scheme name containing a semicolon. The last four
        # columns are always nav/date for history and nav/date at the end for
        # NAVAll, so fold the extra columns into the name.
        head = parts[:3]
        tail = parts[-4:]
        parts = head + [" ".join(parts[3:-4])] + tail
    return parts


def _iter_records(text: str, *, source: str) -> Iterator[SchemeRecord]:
    scheme_type = ""
    scheme_category = ""
    fund_house = ""

    for raw_line in text.splitlines():
        line = _clean(raw_line)
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith(HEADER_PREFIX):
            continue

        section = SECTION_RE.match(line)
        if section:
            scheme_type = _clean(section.group(1))
            scheme_category = _clean(section.group(2)).strip("- ")
            continue

        if ";" not in line:
            # AMC headings ("HDFC Mutual Fund") are the only other content.
            if lowered.endswith(FUND_HOUSE_SUFFIX):
                fund_house = line
            continue

        parts = _split_row(line)
        if parts is None:
            continue

        try:
            scheme_code = int(parts[0])
        except ValueError:
            continue

        if source == "navall":
            isin_growth = _isin(parts[1])
            isin_div = _isin(parts[2])
            base_name, plan, option = parts[3], parts[4], parts[5]
            scheme_name = _build_name(base_name, plan, option)
            nav_value, date_value = parts[6], parts[7]
        else:
            base_name, plan, option = parts[1], parts[2], parts[3]
            isin_growth = _isin(parts[4])
            isin_div = _isin(parts[5])
            scheme_name = _build_name(base_name)
            if not scheme_name:
                scheme_name = _build_name(base_name, plan, option)
            nav_value, date_value = parts[6], parts[7]

        nav = _parse_nav(nav_value)
        if nav is None:
            continue
        try:
            nav_date = parse_amfi_date(date_value)
        except ValueError:
            continue
        if not scheme_name:
            continue

        yield SchemeRecord(
            scheme_code=scheme_code,
            scheme_name=scheme_name,
            fund_house=fund_house,
            scheme_type=scheme_type,
            scheme_category=scheme_category,
            isin_growth=isin_growth,
            isin_div_reinvestment=isin_div,
            nav=nav,
            nav_date=nav_date,
        )


def parse_navall(text: str) -> Iterator[SchemeRecord]:
    """Parse the semicolon separated ``NAVAll.txt`` feed."""

    return _iter_records(text, source="navall")


def parse_history(text: str) -> Iterator[SchemeRecord]:
    """Parse the AMFI NAV history report feed."""

    return _iter_records(text, source="history")


def download_text(
    url: str,
    *,
    settings: Settings,
    params: dict[str, str] | None = None,
    expect_header: bool = True,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Download a text feed with retries and basic content validation."""

    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/plain,text/csv,*/*",
    }
    last_error: Exception | None = None

    for attempt in range(1, settings.retries + 1):
        try:
            with httpx.Client(
                timeout=settings.request_timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                text = decode_bytes(response.content)
            if expect_header and "scheme code" not in text[:2000].lower():
                raise ValueError("AMFI response did not contain a scheme table header")
            return text
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < settings.retries:
                delay = 2 ** attempt
                if log_fn:
                    log_fn(f"  retry {attempt}/{settings.retries - 1} after {delay}s: {exc}")
                time.sleep(delay)

    raise RuntimeError(f"Failed to download {url}: {last_error}") from last_error


def fetch_navall(settings: Settings, log_fn: Callable[[str], None] | None = None) -> str:
    """Download the complete latest NAV report."""

    return download_text(settings.navall_url, settings=settings, log_fn=log_fn)


def fetch_history(
    settings: Settings,
    start: date,
    end: date,
    *,
    scheme_type: str | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> str:
    """Download historical NAV rows for an inclusive date range (<= 90 days)."""

    params = {
        "frmdt": start.strftime(AMFI_DATE_FORMAT),
        "todt": end.strftime(AMFI_DATE_FORMAT),
    }
    if scheme_type:
        # 1 = open ended, 2 = close ended, 3 = interval funds
        params["tp"] = scheme_type
    return download_text(
        settings.history_url,
        settings=settings,
        params=params,
        log_fn=log_fn,
    )
