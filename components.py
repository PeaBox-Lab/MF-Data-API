"""Reusable components for building the MF Data API site."""

from __future__ import annotations

from pathlib import Path


def nav() -> str:
    """Return the navigation HTML string."""
    return """<nav class="nav-links" id="site-nav" aria-label="Main navigation">
  <a href="index.html">Features</a>
  
  <div class="dropdown">
    <a href="docs.html">API reference ▼</a>
    <div class="dropdown-content">
      <a href="docs.html">API reference</a>
      <a href="docs.html#static-mode">Static JSON</a>
      <a href="docs.html#updates">Update schedule</a>
      <a href="docs.html#license">License & attribution</a>
    </div>
  </div>
  
  <div class="dropdown">
    <a href="#">Funds ▼</a>
    <div class="dropdown-content">
      <a href="schemes.html">Schemes</a>
      <a href="fund-houses.html">Fund Houses</a>
      <a href="categories.html">Categories</a>
    </div>
  </div>
  
  <a href="explorer.html">Explorer</a>
  <a href="status.html">Status</a>
  <a href="analytics.html">Analytics</a>
  <a href="data-sources.html">Sources</a>
</nav>"""


def header() -> str:
    """Return the site header HTML string."""
    return f"""<header class="site-header">
  <div class="container header-inner">
    <a class="brand" href="index.html" aria-label="MF Data API home">
      <span class="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 17l5-6 4 3 5-7 4 4"></path>
          <path d="M3 21h18"></path>
        </svg>
      </span>
      <span>MF Data API<small>Indian mutual fund NAV</small></span>
    </a>

    {nav()}

    <div class="nav-actions">
      <a class="btn btn-ghost btn-sm" data-swagger href="docs.html">API reference</a>
      <a class="btn btn-primary btn-sm" href="docs.html#quick-start">Get started</a>
      <button class="nav-toggle" type="button" aria-label="Toggle navigation" aria-expanded="false" aria-controls="site-nav">☰</button>
    </div>
  </div>
</header>"""


def footer() -> str:
    """Return the site footer HTML string."""
    return """<footer class="site-footer">
  <div class="container footer-grid">
    <div class="footer-brand">
      <a class="brand" href="index.html">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 17l5-6 4 3 5-7 4 4"></path><path d="M3 21h18"></path>
          </svg>
        </span>
        <span>MF Data API<small>Indian mutual fund NAV</small></span>
      </a>
      <p>Free and open JSON access to Indian mutual fund NAV data, built from the official AMFI India feed.</p>
    </div>
    <div class="footer-col">
      <h4>Product</h4>
      <a href="explorer.html">API explorer</a>
      <a href="status.html">Status</a>
    </div>
    <div class="footer-col">
      <h4>API</h4>
      <a href="docs.html#endpoint-list">All schemes</a>
      <a href="docs.html#endpoint-history">NAV history</a>
      <a href="docs.html#static-mode">Static JSON</a>
    </div>
    <div class="footer-col">
      <h4>Data</h4>
      <a href="https://www.amfiindia.com/net-asset-value/nav-download" rel="noopener">AMFI India source</a>
      <a href="docs.html#updates">Update schedule</a>
      <a href="docs.html#license">License &amp; attribution</a>
    </div>
  </div>
  <div class="container footer-bottom">
    <span>© <span data-year>2026</span> MF Data API. Data sourced from AMFI India.</span>
    <span><a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · Not affiliated with AMFI or any AMC.</span>
  </div>
</footer>"""


def page(
    title: str,
    description: str = "",
    content: str = "",
    extra_head: str = "",
) -> str:
    """Build a complete HTML page with header, content, and footer."""
    meta_desc = f'<meta name="description" content="{description}">' if description else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  {meta_desc}
  <meta name="theme-color" content="#060b16">
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/style.css">
  {extra_head}
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  {header()}
  <main id="main">
    {content}
  </main>
  {footer()}
  <script src="assets/config.js"></script>
  <script src="assets/app.js"></script>
</body>
</html>"""