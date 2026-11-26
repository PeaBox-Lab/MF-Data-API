from __future__ import annotations

import xml.etree.ElementTree as ET

from scripts.build_sitemap import SITEMAP_NS, page_url, write_sitemap


def _tag(name: str) -> str:
    return f"{{{SITEMAP_NS}}}{name}"


def test_generated_sitemap_follows_search_engine_protocol(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    for name in ("index.html", "docs.html", "analytics.html", "404.html"):
        (web / name).write_text("<!doctype html><title>test</title>", encoding="utf-8")

    out = tmp_path / "sitemap.xml"
    entries = write_sitemap(web, out, base_url="https://example.com", fallback_date="2026-11-27")

    assert [entry["loc"] for entry in entries] == [
        "https://example.com/analytics.html",
        "https://example.com/docs.html",
        "https://example.com/",
    ]
    assert not out.read_bytes().startswith(b"\xef\xbb\xbf")

    root = ET.fromstring(out.read_bytes())
    assert root.tag == _tag("urlset")
    urls = root.findall(_tag("url"))
    assert len(urls) == 3

    first = urls[0]
    assert first.findtext(_tag("loc")) == "https://example.com/analytics.html"
    assert first.findtext(_tag("lastmod")) == "2026-11-27"
    assert first.findtext(_tag("changefreq")) == "weekly"
    assert first.findtext(_tag("priority")) == "0.9"

    assert all(url.findtext(_tag("loc")) != "https://example.com/404.html" for url in urls)


def test_canonical_root_url():
    assert page_url("https://example.com/", "index.html") == "https://example.com/"
    assert page_url("https://example.com", "docs.html") == "https://example.com/docs.html"
