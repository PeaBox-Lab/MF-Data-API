"""Generate a Google/Bing-compatible XML sitemap from the static site pages.

Usage:
    python scripts/build_sitemap.py --web-dir web --out web/sitemap.xml

The sitemap follows the sitemaps.org 0.9 protocol: UTF-8 XML, absolute HTTPS
loc values, optional W3C-date lastmod values, changefreq and priority. Error
pages and non-HTML assets are deliberately excluded, and index.html is emitted
as the site root so the loc values are canonical.
"""

from __future__ import annotations

import argparse
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
DEFAULT_BASE_URL = "https://mfdata.peabox.in"

ET.register_namespace("", SITEMAP_NS)

# Pages are small and stable; these hints are valid for both Google and Bing.
PAGE_RULES: dict[str, tuple[str, str]] = {
    "index.html": ("daily", "1.0"),
    "docs.html": ("weekly", "0.9"),
    "explorer.html": ("weekly", "0.9"),
    "analytics.html": ("weekly", "0.9"),
    "schemes.html": ("weekly", "0.8"),
    "fund-houses.html": ("weekly", "0.8"),
    "fund-house.html": ("weekly", "0.7"),
    "categories.html": ("weekly", "0.7"),
    "data-sources.html": ("weekly", "0.7"),
    "status.html": ("daily", "0.7"),
    "about.html": ("monthly", "0.5"),
    "privacy.html": ("yearly", "0.3"),
    "terms.html": ("yearly", "0.3"),
}

EXCLUDED_PAGES = {"404.html"}


def _tag(name: str) -> str:
    return f"{{{SITEMAP_NS}}}{name}"


def _git_lastmod(relative_path: str) -> str | None:
    """Return the last committed date for a tracked source file."""

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", relative_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


def page_url(base_url: str, filename: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/" if filename == "index.html" else f"{base}/{filename}"


def write_sitemap(
    web_dir: Path,
    out: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
    fallback_date: str | None = None,
) -> list[dict[str, str]]:
    """Write sitemap.xml and return the entries that were emitted."""

    web_dir = Path(web_dir)
    out = Path(out)
    fallback = fallback_date or datetime.now(UTC).date().isoformat()

    entries: list[dict[str, str]] = []
    for path in sorted(web_dir.glob("*.html")):
        if path.name in EXCLUDED_PAGES:
            continue
        changefreq, priority = PAGE_RULES.get(path.name, ("monthly", "0.5"))
        try:
            relative_path = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            lastmod = fallback
        else:
            lastmod = _git_lastmod(relative_path) or fallback
        entries.append(
            {
                "loc": page_url(base_url, path.name),
                "lastmod": lastmod,
                "changefreq": changefreq,
                "priority": priority,
            }
        )

    urlset = ET.Element(_tag("urlset"))
    for entry in entries:
        url = ET.SubElement(urlset, _tag("url"))
        for key in ("loc", "lastmod", "changefreq", "priority"):
            ET.SubElement(url, _tag(key)).text = entry[key]

    ET.indent(urlset, space="  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(urlset, encoding="utf-8", xml_declaration=False)
        + b"\n"
    )
    out.write_bytes(xml)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-dir", type=Path, default=ROOT / "web")
    parser.add_argument("--out", type=Path, default=ROOT / "web" / "sitemap.xml")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    entries = write_sitemap(args.web_dir, args.out, base_url=args.base_url)
    print(f"Wrote {len(entries)} URLs to {args.out} ({args.base_url})")


if __name__ == "__main__":
    main()
