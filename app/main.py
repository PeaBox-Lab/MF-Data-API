"""FastAPI application entry point.

Run locally with:

    python -m pipeline serve
    # or
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from pipeline.store import Store

from .config import AppSettings
from .deps import ApiError
from .middleware import CacheHeadersMiddleware, RateLimitMiddleware
from .routes import router

log = logging.getLogger(__name__)

TAGS_METADATA = [
    {"name": "Schemes", "description": "Scheme master data and search."},
    {"name": "NAV", "description": "Latest and historical net asset values."},
    {"name": "Reference", "description": "Fund houses and categories."},
    {"name": "Meta", "description": "Dataset freshness, statistics and health."},
]

DESCRIPTION = """
**MF Data API** provides free, open JSON access to Indian mutual fund NAV data.

* **Source:** AMFI India (`portal.amfiindia.com`) — the official NAV feed.
* **Coverage:** every scheme published by AMFI, with multi-year NAV history.
* **Updates:** automatically refreshed twice a day by a GitHub Actions workflow.
* **Auth:** none. No API keys, no registration.
* **Rate limit:** 120 requests/minute per IP by default.

Compatible endpoints are available both under `/api/v1` and at the site root
(for example `/mf/125497`), mirroring the well-known MFapi.in URL layout.
"""


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_env()
    web_dir = settings.web_dir
    store = Store(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if store.has_data():
            counts = store.counts()
            log.info(
                "MF Data API ready: %s schemes, latest NAV %s",
                counts.get("scheme_count"),
                counts.get("latest_date"),
            )
        else:
            log.warning(
                "No NAV database at %s. Run 'python -m pipeline sync' to populate it.",
                settings.db_path,
            )
        yield

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=DESCRIPTION,
        contact={
            "name": "MF Data API",
            "url": "https://github.com/",
        },
        license_info={"name": "MIT"},
        openapi_tags=TAGS_METADATA,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        swagger_ui_parameters={
            "docExpansion": "list",
            "defaultModelsExpandDepth": -1,
            "tryItOutEnabled": True,
        },
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store

    origins = list(settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CacheHeadersMiddleware, default_ttl=settings.cache_ttl)
    app.add_middleware(
        RateLimitMiddleware, limit=settings.rate_limit, window=settings.rate_window
    )

    # Primary, documented API plus root-level compatibility aliases.
    app.include_router(router, prefix=settings.api_prefix)
    app.include_router(router, include_in_schema=False)

    # ------------------------------------------------------------------ errors
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": exc.status, "message": exc.message},
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        is_api = path.startswith(("/api/", "/mf", "/nav/", "/fund-houses", "/stats"))
        if exc.status_code == 404 and not is_api:
            not_found = web_dir / "404.html"
            if not_found.exists():
                return FileResponse(not_found, status_code=404)
        if is_api:
            status = "NOT_FOUND" if exc.status_code == 404 else "ERROR"
            return JSONResponse(
                status_code=exc.status_code,
                content={"status": status, "message": str(exc.detail)},
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": "ERROR", "message": str(exc.detail)},
        )

    # -------------------------------------------------------------------- site
    @app.get("/api", include_in_schema=False)
    def api_index():
        return {
            "name": settings.title,
            "version": settings.version,
            "documentation": "/docs",
            "openapi": "/api/openapi.json",
            "swagger": "/api/docs",
            "base_url": settings.api_prefix,
            "endpoints": {
                "schemes": f"{settings.api_prefix}/mf",
                "search": f"{settings.api_prefix}/mf/search?q=hdfc",
                "scheme": f"{settings.api_prefix}/mf/{{scheme_code}}",
                "latest": f"{settings.api_prefix}/mf/{{scheme_code}}/latest",
                "all_latest": f"{settings.api_prefix}/mf/latest",
                "stats": f"{settings.api_prefix}/stats",
                "health": f"{settings.api_prefix}/health",
                "movers": f"{settings.api_prefix}/movers/latest",
                "movers-search": f"{settings.api_prefix}/movers/search",
                "fund-houses/{name}": f"{settings.api_prefix}/fund-houses/{{fund_house}}/stats",
                "categories": f"{settings.api_prefix}/categories",
                "compare": f"{settings.api_prefix}/compare",
                "data-sources": f"{settings.api_prefix}/data-sources",
            },
        }

    def page(name: str) -> FileResponse:
        return FileResponse(web_dir / name)

    @app.get("/", include_in_schema=False)
    def index():
        return page("index.html")

    @app.get("/docs", include_in_schema=False)
    def docs_page():
        return page("docs.html")

    @app.get("/explorer", include_in_schema=False)
    def explorer_page():
        return page("explorer.html")

    @app.get("/about", include_in_schema=False)
    def about_page():
        return page("about.html")

    @app.get("/schemes", include_in_schema=False)
    def schemes_page():
        return page("schemes.html")

    @app.get("/fund-houses", include_in_schema=False)
    def fund_houses_page():
        return page("fund-houses.html")

    @app.get("/fund-house", include_in_schema=False)
    def fund_house_detail_page(fund_house: str = Query(default=None, alias="name")):
        return page("fund-house.html")

    @app.get("/categories", include_in_schema=False)
    def categories_page():
        return page("categories.html")

    @app.get("/privacy", include_in_schema=False)
    def privacy_page():
        return page("privacy.html")

    @app.get("/terms", include_in_schema=False)
    def terms_page():
        return page("terms.html")

    @app.get("/status", include_in_schema=False)
    def status_page():
        return page("status.html")

    if (web_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=web_dir / "assets"), name="assets")
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="site")

    return app


app = create_app()