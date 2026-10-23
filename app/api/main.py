"""FastAPI application. Run with: uvicorn app.api.main:app --port 8000"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.account_routes import admin_router
from app.api.account_routes import router as account_router
from app.api.auth_routes import router as auth_router
from app.api.planning_routes import router as planning_router
from app.api.publishing_routes import router as publishing_router
from app.api.routes import router
from app.api.translation_routes import router as translation_router
from app.services.books import BookError
from app.services.ocr import OcrSetupError
from app.services.review import ReviewError
from app.services.translation.service import NeedsConfirmation

logger = logging.getLogger(__name__)

# Emotion (Chakra UI) writes inline styles, so styles allow 'unsafe-inline'; scripts may only come from this site.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    """Build the API (and serve the built React app when frontend/dist exists)."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    docs = os.getenv("API_DOCS", "false").strip().lower() in ("1", "true", "yes")  # off by default: no public API map
    app = FastAPI(
        title="PathippuAI",
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(NeedsConfirmation)
    async def needs_confirmation(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc), "needs_confirmation": True})

    @app.exception_handler(BookError)
    @app.exception_handler(OcrSetupError)
    @app.exception_handler(ReviewError)
    async def friendly_error(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(admin_router)
    app.include_router(router)
    app.include_router(planning_router)
    app.include_router(translation_router)
    app.include_router(publishing_router)

    if FRONTEND_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            return FileResponse(FRONTEND_DIST / "index.html")

    return app


app = create_app()
