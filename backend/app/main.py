from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import engine
from app.logging_config import configure_logging, request_id_var
from app.routers import agents, api_keys, execution, graphs, mcp_servers, runs

configure_logging(settings.log_level)
log = logging.getLogger(__name__)

# Path to the backend package root — used to locate alembic.ini regardless of
# the working directory when the process starts.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


# ---------------------------------------------------------------------------
# Alembic migration runner (synchronous — run in a thread from lifespan)
# ---------------------------------------------------------------------------

def _run_alembic_upgrade() -> None:
    """
    Apply any pending Alembic migrations. Safe to call on every startup:
    Alembic is idempotent — it skips revisions already applied.
    """
    from alembic import command as alembic_command
    from alembic.config import Config

    cfg = Config(os.path.join(_BACKEND_DIR, "alembic.ini"))
    # Pass the live settings value directly so we never rely on ambient os.environ
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    alembic_command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# Lifespan — startup order: migrations → seed (debug only) → serve
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", extra={"event": "startup", "debug": settings.debug})

    log.info("running_migrations", extra={"event": "migrations_start"})
    await asyncio.to_thread(_run_alembic_upgrade)
    log.info("migrations_complete", extra={"event": "migrations_done"})

    if settings.debug:
        from app.seed import seed
        await seed()

    yield

    log.info("shutdown", extra={"event": "shutdown"})
    await engine.dispose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent Platform API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphs.router, prefix="/api/v1")
app.include_router(execution.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(mcp_servers.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(api_keys.router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Error handlers — consistent schema, no stack trace leakage
# ---------------------------------------------------------------------------

def _error_body(message: str) -> dict:
    return {"error": message, "request_id": request_id_var.get("") or None}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    log.warning("http_exception", extra={"status": exc.status_code, "detail": exc.detail})
    return JSONResponse(status_code=exc.status_code, content=_error_body(str(exc.detail)))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    log.warning("validation_error", extra={"errors": exc.errors()})
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": exc.errors(),
            "request_id": request_id_var.get("") or None,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_exception")
    return JSONResponse(status_code=500, content=_error_body("Internal server error"))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
