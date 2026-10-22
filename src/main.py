import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.api.demo_routes import router as demo_router
from src.core.config import (
    PROJECT_ROOT,
    get_allowed_origins,
    get_app_mode,
    get_public_url,
    get_workspace_database,
)

logger = logging.getLogger(__name__)


def create_app(mode: str | None = None, *, db_path: Path | None = None) -> FastAPI:
    mode = mode or get_app_mode()
    if mode not in {"application", "demo", "live"}:
        raise RuntimeError("APP_MODE musi mieć wartość application, demo lub live")
    public_url = get_public_url()

    @asynccontextmanager
    async def lifespan(application):
        if mode == "application":
            from src.services.workspace_store import WorkspaceStore

            repository = WorkspaceStore(db_path or get_workspace_database())
            repository.initialize()
            application.state.store = repository

            async def retain_workspaces():
                while True:
                    await asyncio.sleep(300)
                    try:
                        await asyncio.to_thread(repository.cleanup_expired)
                    except Exception:
                        logger.exception("Workspace retention failed")

            await asyncio.to_thread(repository.cleanup_expired)
            cleanup = asyncio.create_task(retain_workspaces())
        try:
            yield
        finally:
            if mode == "application":
                cleanup.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup

    application = FastAPI(
        title="SentinelHub · Flood-aware routing",
        description="Private persistent workspaces, user GeoJSON and protected OSM / WMS imports.",
        version="0.4.0",
        lifespan=lifespan,
        servers=[{"url": public_url}] if public_url else None,
    )
    application.state.mode = mode
    if public_url:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[
                urlsplit(public_url).hostname,
                "localhost",
                "127.0.0.1",
                "api",
            ],
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Key", "Authorization"],
    )

    @application.middleware("http")
    async def request_limits(request: Request, call_next):
        limit = 3 * 1024 * 1024 if request.url.path.startswith("/api/workspaces/") else 4096
        try:
            async with asyncio.timeout(5):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > limit:
                        return JSONResponse(
                            {"detail": f"Limit treści żądania: {limit} bajtów"}, 413
                        )
                    body.extend(chunk)
                request._body = bytes(body)
            async with asyncio.timeout(10 if mode == "demo" else 75):
                response = await call_next(request)
        except TimeoutError:
            logger.warning("Request deadline exceeded: %s %s", request.method, request.url.path)
            return JSONResponse({"detail": "Przekroczono czas obsługi żądania"}, 504)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        policy = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.url.path in {"/docs", "/redoc"}:
            policy = policy.replace(
                "script-src 'self'", "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
            )
            policy = policy.replace(
                "style-src 'self'", "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
            )
        response.headers["Content-Security-Policy"] = policy
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    application.include_router(demo_router, prefix="/api")
    if mode == "demo":

        @application.get("/", include_in_schema=False)
        def sample_home():
            return RedirectResponse("/sample.html")

    if mode == "application":
        from src.api.workspace_routes import install_error_handlers
        from src.api.workspace_routes import router as workspace_router

        application.include_router(workspace_router, prefix="/api")
        install_error_handlers(application)
    if mode == "live":
        from src.api.routes import router as evac_router

        application.include_router(evac_router, prefix="/api")

    @application.get("/health", tags=["system"])
    def healthcheck() -> dict[str, str]:
        return {"status": "ok", "mode": mode, "version": "0.4.0"}

    @application.get("/ready", tags=["system"])
    def readiness():
        if mode == "application":
            import sqlite3

            repository = getattr(application.state, "store", None)
            try:
                if repository is None or not repository.ready():
                    return JSONResponse({"status": "unavailable"}, 503)
            except sqlite3.Error:
                return JSONResponse({"status": "unavailable"}, 503)
        return {"status": "ready", "mode": mode}

    application.mount("/", StaticFiles(directory=PROJECT_ROOT / "frontend", html=True), name="web")
    return application


app = create_app()
