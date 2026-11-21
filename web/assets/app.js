(() => {
  "use strict";

  const cfg = Object.assign(
    { mode: "server", apiBase: "/api/v1", repoUrl: "" },
    window.MFDATA_CONFIG || {}
  );

  // Detect static mode: explicit flag, file protocol, or non-absolute apiBase
  const STATIC =
    cfg.mode === "static" ||
    location.protocol === "file:" ||
    !String(cfg.apiBase || "").startsWith("/");

  // Endpoints that only exist on the live API (no static .json equivalent)
  const LIVE_ONLY_ENDPOINTS = new Set(["navDate"]);

  const BASE = String(cfg.apiBase || "/api/v1").replace(/\/+$/, "");

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const fmt = new Intl.NumberFormat("en-IN");
  const nf = (value) => (typeof value === "number" ? fmt.format(value) : value || "—");

  function apiUrl(path, params = {}) {
    const url = new URL(BASE + path, document.baseURI);
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && String(value).trim() !== "") {
        url.searchParams.set(key, value);
      }
    });
    return url;
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      ...options,
    });
    const text = await response.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    return { response, data };
  }

  async function copyText(text, button) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    if (button) {
      const original = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => (button.textContent = original), 1400);
    }
  }

  /* ------------------------------------------------------------- navigation */
  function setupNav() {
    const toggle = $(".nav-toggle");
    const links = $(".nav-links");
    if (toggle && links) {
      toggle.addEventListener("click", () => {
        const open = links.classList.toggle("open");
        toggle.setAttribute("aria-expanded", String(open));
      });
    }
    const path = location.pathname.replace(/\/+$/, "");
    $$(".nav-links a").forEach((link) => {
      const href = link.getAttribute("href") || "";
      if (!href || href.startsWith("http") || href.startsWith("#")) return;
      const target = new URL(href, location.href).pathname.replace(/\/+$/, "");
      if (target === path || (target.endsWith("/index.html") && path === "")) {
        link.setAttribute("aria-current", "page");
      }
    });
    $$("[data-year]").forEach((el) => (el.textContent = new Date().getFullYear()));
    if (STATIC) {
      $$("[data-swagger]").forEach((el) => {
        el.hidden = true;
      });
      $$("[data-live-only]").forEach((el) => {
        el.hidden = true;
      });
      $$("[data-static-href]").forEach((el) => {
        el.setAttribute("href", el.getAttribute("data-static-href"));
      });
    }
  }

  /* ------------------------------------------------------------ copy buttons */
  function setupCopyButtons() {
    $$("pre").forEach((pre) => {
      if (pre.querySelector(".copy-pre")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "copy-pre";
      button.textContent = "Copy";
      button.addEventListener("click", () => {
        const code = pre.querySelector("code");
        copyText((code || pre).innerText, button);
      });
      pre.appendChild(button);
    });

    $$("[data-copy]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.getAttribute("data-copy");
        const el = target ? $(target) : null;
        copyText(el ? el.innerText.trim() : button.getAttribute("data-copy-text") || "", button);
      });
    });

    $$("[data-fill-search]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = $("#fund-search");
        if (!input) return;
        input.value = button.getAttribute("data-fill-search") || "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
        input.scrollIntoView({ block: "center", behavior: "smooth" });
      });
    });
  }

  /* ------------------------------------------------------------------ stats */
  async function loadStats() {
    const targets = $$("[data-stat]");
    if (!targets.length) return;
    try {
      const path = STATIC ? "/stats.json" : "/stats";
      const { response, data } = await fetchJson(apiUrl(path));
      if (!response.ok) throw new Error("stats unavailable");
      const map = {
        schemes: data.scheme_count,
        rows: data.nav_rows,
        houses: data.fund_house_count,
        categories: data.category_count,
        latest: data.latest_nav_date,
      };
      targets.forEach((el) => {
        const key = el.getAttribute("data-stat");
        const value = map[key];
        if (value === undefined || value === null) return;
        el.textContent = key === "latest" ? value : nf(value);
      });
      const updated = $("[data-last-updated]");
      if (updated && data.generated_at) {
        updated.textContent = new Date(data.generated_at).toLocaleString("en-IN", {
          dateStyle: "medium",
          timeStyle: "short",
        });
      }
    } catch {
      /* Keep the static fallback values already in the markup. */
    }
  }

  /* ----------------------------------------------------------- home search */
  let schemeIndexPromise = null;
  function schemeIndex() {
    if (!schemeIndexPromise) {
      schemeIndexPromise = fetchJson(apiUrl("/mf.json")).then(({ response, data }) => {
        if (!response.ok) throw new Error("Scheme list unavailable");
        return data;
      });
    }
    return schemeIndexPromise;
  }

  async function searchSchemes(query, limit = 8) {
    if (STATIC) {
      const index = await schemeIndex();
      const needle = query.toLowerCase();
      const results = [];
      for (const item of index) {
        if (
          item.schemeName.toLowerCase().includes(needle) ||
          String(item.schemeCode) === needle
        ) {
          results.push(item);
          if (results.length >= limit) break;
        }
      }
      return results;
    }
    const { response, data } = await fetchJson(
      apiUrl("/mf/search", { q: query, limit })
    );
    if (!response.ok) throw new Error("Search failed");
    return data;
  }

  async function latestFor(code) {
    const path = STATIC ? `/mf/${code}/latest.json` : `/mf/${code}/latest`;
    const { response, data } = await fetchJson(apiUrl(path));
    if (!response.ok) throw new Error("Latest NAV unavailable");
    return data;
  }

  function setupHomeSearch() {
    const input = $("#fund-search");
    const results = $("#search-results");
    const panel = $("#scheme-panel");
    if (!input || !results || !panel) return;

    let timer = null;
    let current = [];

    function closeResults() {
      results.classList.remove("open");
      results.innerHTML = "";
    }

    function renderResults(items) {
      results.innerHTML = "";
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "search-empty";
        empty.textContent = "No schemes matched that search.";
        results.appendChild(empty);
        results.classList.add("open");
        return;
      }
      items.forEach((item) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "search-result";
        const name = document.createElement("span");
        name.className = "name";
        name.textContent = item.schemeName;
        const code = document.createElement("span");
        code.className = "code";
        code.textContent = item.schemeCode;
        button.append(name, code);
        button.addEventListener("click", () => selectScheme(item));
        results.appendChild(button);
      });
      results.classList.add("open");
    }

    async function runSearch() {
      const query = input.value.trim();
      if (query.length < 2) {
        closeResults();
        return;
      }
      results.innerHTML = '<div class="search-empty">Searching…</div>';
      results.classList.add("open");
      try {
        current = await searchSchemes(query, 8);
        renderResults(current);
      } catch {
        results.innerHTML =
          '<div class="search-empty">Search is temporarily unavailable.</div>';
        results.classList.add("open");
      }
    }

    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(runSearch, 220);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (current.length) selectScheme(current[0]);
      }
      if (event.key === "Escape") closeResults();
    });

    document.addEventListener("click", (event) => {
      if (!results.contains(event.target) && event.target !== input) closeResults();
    });

    async function selectScheme(item) {
      input.value = item.schemeName;
      closeResults();
      panel.classList.add("open");

      const nameEl = $("#selected-name");
      const codeEl = $("#selected-code");
      const navEl = $("#selected-nav");
      const apiEl = $("#selected-api-url");
      const latestEl = $("#selected-latest-url");
      const linkEl = $("#selected-link");
      if (nameEl) nameEl.textContent = item.schemeName;
      if (codeEl) codeEl.textContent = `#${item.schemeCode}`;
      if (navEl) navEl.textContent = "Loading latest NAV…";

      const historyUrl = apiUrl(
        STATIC ? `/mf/${item.schemeCode}.json` : `/mf/${item.schemeCode}`
      );
      const latestUrl = apiUrl(
        STATIC ? `/mf/${item.schemeCode}/latest.json` : `/mf/${item.schemeCode}/latest`
      );
      if (apiEl) apiEl.textContent = historyUrl.href;
      if (latestEl) latestEl.textContent = latestUrl.href;
      if (linkEl) linkEl.href = `explorer.html?endpoint=history&code=${item.schemeCode}`;

      try {
        const data = await latestFor(item.schemeCode);
        const point = data.data && data.data[0];
        if (navEl && point) {
          navEl.innerHTML = `Latest NAV <b>${point.nav}</b> on ${point.date}`;
        } else if (navEl) {
          navEl.textContent = "No NAV observations available.";
        }
      } catch {
        if (navEl) navEl.textContent = "Latest NAV is temporarily unavailable.";
      }
    }
  }

  /* ------------------------------------------------------------------- docs */
  function setupDocs() {
    const baseTargets = $$("[data-api-base]");
    if (baseTargets.length) {
      const display = new URL(BASE + "/", document.baseURI);
      baseTargets.forEach((el) => {
        el.textContent = STATIC
          ? display.href.replace(/\/$/, "")
          : display.pathname.replace(/\/$/, "");
      });
    }
    $$("[data-api-base-link]").forEach((el) => {
      el.href = new URL(BASE + "/mf", document.baseURI).href;
    });
    $$("[data-mode]").forEach((el) => {
      el.textContent = STATIC ? "static JSON files" : "live FastAPI service";
    });

    const originBase = STATIC
      ? new URL(".", document.baseURI).href.replace(/\/$/, "")
      : location.origin;
    $$("pre code").forEach((code) => {
      if (code.textContent.includes("https://api.example.com")) {
        code.textContent = code.textContent
          .split("https://api.example.com")
          .join(originBase);
      }
    });

    const sections = $$("[data-doc-section]");
    const links = $$(".docs-sidebar a[href^='#']");
    if (sections.length && links.length && "IntersectionObserver" in window) {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            links.forEach((link) => {
              link.classList.toggle(
                "active",
                link.getAttribute("href") === `#${entry.target.id}`
              );
            });
          });
        },
        { rootMargin: "-20% 0px -70% 0px" }
      );
      sections.forEach((section) => observer.observe(section));
    }
  }

  /* --------------------------------------------------------------- explorer */
  const EXPLORER_ENDPOINTS = {
    list: { label: "GET /mf — all schemes", path: "/mf", fields: ["limit", "offset"] },
    search: { label: "GET /mf/search — search schemes", path: "/mf/search", fields: ["q", "limit"] },
    history: {
      label: "GET /mf/{code} — NAV history",
      path: "/mf/{code}",
      fields: ["code", "startDate", "endDate"],
    },
    latest: {
      label: "GET /mf/{code}/latest — latest NAV",
      path: "/mf/{code}/latest",
      fields: ["code"],
    },
    meta: { label: "GET /mf/{code}/meta — metadata", path: "/mf/{code}/meta", fields: ["code"] },
    allLatest: { label: "GET /mf/latest — latest NAVs", path: "/mf/latest", fields: ["limit", "offset"] },
    houses: { label: "GET /fund-houses — fund houses", path: "/fund-houses", fields: [] },
    categories: { label: "GET /categories — categories", path: "/categories", fields: [] },
    navDate: { label: "GET /nav/{date} — NAVs by date", path: "/nav/{date}", fields: ["date", "limit"] },
    stats: { label: "GET /stats — dataset statistics", path: "/stats", fields: [] },
    health: { label: "GET /health — health check", path: "/health", fields: [] },
  };

  function setupExplorer() {
    const form = $("#explorer-form");
    const select = $("#endpoint-select");
    if (!form || !select) return;

    const params = new URLSearchParams(location.search);
    if (params.get("endpoint") && EXPLORER_ENDPOINTS[params.get("endpoint")]) {
      select.value = params.get("endpoint");
    }

    const inputs = {
      code: $("#field-code"),
      q: $("#field-q"),
      date: $("#field-date"),
      limit: $("#field-limit"),
      offset: $("#field-offset"),
      start: $("#field-start"),
      end: $("#field-end"),
    };
    const wrappers = {
      code: $("#wrap-code"),
      q: $("#wrap-q"),
      date: $("#wrap-date"),
      limit: $("#wrap-limit"),
      offset: $("#wrap-offset"),
      startDate: $("#wrap-start"),
      endDate: $("#wrap-end"),
    };

    const initial = {
      code: params.get("code"),
      q: params.get("q"),
      date: params.get("date"),
      limit: params.get("limit"),
      offset: params.get("offset"),
      start: params.get("startDate"),
      end: params.get("endDate"),
    };
    Object.entries(initial).forEach(([key, value]) => {
      if (value && inputs[key]) inputs[key].value = value;
    });

    function syncFields() {
      const config = EXPLORER_ENDPOINTS[select.value];
      Object.entries(wrappers).forEach(([name, wrapper]) => {
        if (!wrapper) return;
        wrapper.hidden = !config.fields.includes(name);
      });
      updatePreview();
    }

    function values() {
      return {
        code: inputs.code ? inputs.code.value.trim() : "",
        q: inputs.q ? inputs.q.value.trim() : "",
        date: inputs.date ? inputs.date.value.trim() : "",
        limit: inputs.limit ? inputs.limit.value.trim() : "",
        offset: inputs.offset ? inputs.offset.value.trim() : "",
        startDate: inputs.start ? inputs.start.value.trim() : "",
        endDate: inputs.end ? inputs.end.value.trim() : "",
      };
    }

    function buildUrl() {
      const config = EXPLORER_ENDPOINTS[select.value];
      const v = values();
      let path = config.path;
      if (path.includes("{code}")) {
        if (!v.code) return null;
        path = path.replace("{code}", encodeURIComponent(v.code));
      }
      if (path.includes("{date}")) {
        if (!v.date) return null;
        path = path.replace("{date}", encodeURIComponent(v.date));
      }
      const query = {};
      ["q", "limit", "offset", "startDate", "endDate"].forEach((key) => {
        if (config.fields.includes(key) && v[key]) query[key] = v[key];
      });
      return { url: apiUrl(path, query), config, values: v };
    }

    function updatePreview() {
      const built = buildUrl();
      const target = $("#request-url");
      if (!target) return;
      if (!built) {
        target.textContent = "Enter the required parameters…";
        return;
      }
      if (STATIC) {
        const staticUrl = staticRequest(built);
        target.textContent = staticUrl
          ? staticUrl.href
          : "This endpoint is not available in static mode.";
      } else {
        target.textContent = built.url.href;
      }
    }

    function staticRequest(built) {
      const v = built.values;
      switch (select.value) {
        case "list":
          return apiUrl("/mf.json");
        case "search":
          return apiUrl("/mf.json");
        case "history":
          return apiUrl(`/mf/${encodeURIComponent(v.code)}.json`);
        case "latest":
          return apiUrl(`/mf/${encodeURIComponent(v.code)}/latest.json`);
        case "meta":
          return apiUrl(`/mf/${encodeURIComponent(v.code)}.json`);
        case "allLatest":
          return apiUrl("/mf/latest.json");
        case "houses":
          return apiUrl("/fund-houses.json");
        case "categories":
          return apiUrl("/categories.json");
        case "stats":
          return apiUrl("/stats.json");
        case "health":
          return apiUrl("/health.json");
        case "navDate":
          return null;
        default:
          return built.url;
      }
    }

    function slicePage(items, v) {
      const offset = Math.max(0, parseInt(v.offset || "0", 10) || 0);
      const limit = v.limit ? Math.max(1, parseInt(v.limit, 10) || 0) : null;
      return limit ? items.slice(offset, offset + limit) : items.slice(offset);
    }

    function parseApiDate(value) {
      const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
      if (match) return new Date(+match[3], +match[2] - 1, +match[1]);
      return new Date(value);
    }

    function transformStatic(endpoint, data, v) {
      switch (endpoint) {
        case "list":
          return slicePage(data, v);
        case "search": {
          const needle = (v.q || "").toLowerCase();
          const found = data.filter(
            (item) =>
              item.schemeName.toLowerCase().includes(needle) ||
              String(item.schemeCode) === needle
          );
          return slicePage(found, v);
        }
        case "history": {
          if (v.startDate || v.endDate) {
            const start = v.startDate ? new Date(`${v.startDate}T00:00:00`) : null;
            const end = v.endDate ? new Date(`${v.endDate}T23:59:59`) : null;
            data.data = data.data.filter((point) => {
              const day = parseApiDate(point.date);
              return (!start || day >= start) && (!end || day <= end);
            });
          }
          return data;
        }
        case "allLatest":
          return slicePage(data, v);
        case "meta":
          return data.meta;
        case "health":
          return data;
        case "navDate":
          throw new Error(
            "The by-date endpoint is only available on the live API. Use /mf/{code} for static history."
          );
        default:
          return data;
      }
    }

    async function send(event) {
      event.preventDefault();
      const built = buildUrl();
      const responseEl = $("#response-body");
      const metaEl = $("#response-meta");
      if (!built) {
        if (responseEl) responseEl.textContent = "Fill in the required path parameters first.";
        return;
      }

      const button = $("#send-request");
      if (button) {
        button.disabled = true;
        button.textContent = "Requesting…";
      }
      if (metaEl) metaEl.innerHTML = '<span class="status-dot"></span> Waiting for response…';
      if (responseEl) responseEl.textContent = "";

      const started = performance.now();
      let url = built.url;
      if (STATIC) {
        const staticUrl = staticRequest(built);
        if (!staticUrl) {
          if (responseEl) responseEl.textContent = "This endpoint is not available in static mode.";
          if (metaEl) metaEl.innerHTML = '<span class="status-dot err"></span> Not available';
          if (button) {
            button.disabled = false;
            button.textContent = "Send request";
          }
          return;
        }
        url = staticUrl;
      }

      try {
        const { response, data } = await fetchJson(url);
        let payload = data;
        if (STATIC && response.ok) {
          payload = transformStatic(select.value, data, built.values);
        }
        const elapsed = Math.round(performance.now() - started);
        const text = JSON.stringify(payload, null, 2);
        if (responseEl) responseEl.textContent = text;
        if (metaEl) {
          metaEl.innerHTML = `<span class="status-dot ${response.ok ? "ok" : "err"}"></span>
            HTTP ${response.status} · ${elapsed} ms · ${nf(text.length)} bytes
            <span class="muted">${STATIC ? "static JSON" : url.pathname}</span>`;
        }
        $("#download-response").onclick = () => {
          const blob = new Blob([text], { type: "application/json" });
          const link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = "mfdata-response.json";
          link.click();
          URL.revokeObjectURL(link.href);
        };
        $("#copy-response").onclick = (event) =>
          copyText(text, event.currentTarget);
      } catch (error) {
        if (responseEl) responseEl.textContent = String(error.message || error);
        if (metaEl) metaEl.innerHTML = '<span class="status-dot err"></span> Request failed';
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "Send request";
        }
      }
    }

    select.addEventListener("change", syncFields);
    Object.values(inputs).forEach(
      (field) => field && field.addEventListener("input", updatePreview)
    );
    form.addEventListener("submit", send);
    syncFields();
  }

  /* ----------------------------------------------------------------- status */
  async function setupStatus() {
    const banner = $("#status-banner-text");
    if (!banner) return;
    const statTargets = $$("[data-status-field]");
    try {
      const statsPath = STATIC ? "/stats.json" : "/stats";
      const { response, data } = await fetchJson(apiUrl(statsPath));
      if (!response.ok) throw new Error("unavailable");
      const map = {
        status: "Operational",
        latest: data.latest_nav_date,
        schemes: nf(data.scheme_count),
        rows: nf(data.nav_rows),
        generated: data.generated_at
          ? new Date(data.generated_at).toLocaleString("en-IN", {
              dateStyle: "medium",
              timeStyle: "short",
            })
          : "—",
        source: data.source,
      };
      statTargets.forEach((el) => {
        const key = el.getAttribute("data-status-field");
        if (map[key] !== undefined) el.textContent = map[key];
      });
      banner.textContent = `All systems operational. Latest NAV in the dataset: ${data.latest_nav_date}.`;
      $("#status-banner").classList.add("ok");
    } catch {
      banner.textContent = "Status data could not be loaded. The API may be starting up.";
      $("#status-banner").classList.add("err");
    }
  }

  /* -------------------------------------------------------------------- init */
  document.addEventListener("DOMContentLoaded", () => {
    setupNav();
    setupCopyButtons();
    loadStats();
    setupHomeSearch();
    setupDocs();
    setupExplorer();
    setupStatus();
  });
})();
