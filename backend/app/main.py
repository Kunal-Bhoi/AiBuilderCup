"""One image, two Cloud Run services. SERVICE_ROLE=api mounts the public /api/v1 routers,
SERVICE_ROLE=worker mounts the Cloud Tasks endpoint, and "all" (local development) mounts both."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, decisions, documents, org, pages, reports, shipments, system
from app.config import get_settings
from app.db.engine import dispose
from app.errors import install_error_handlers
from app.ids import new_id
from app.logging import configure_logging, set_request_context
from app.services.events import broker

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await broker.close()
    await dispose()


def _trace_id(request: Request) -> str | None:
    if tp := request.headers.get("traceparent"):
        parts = tp.split("-")
        if len(parts) >= 2:
            return parts[1]
    if ct := request.headers.get("X-Cloud-Trace-Context"):
        return ct.split("/", 1)[0]
    return None


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(
        title="TradeCheck api-service",
        version=system.VERSION,
        description="Cross-document trade file pre-validation. The system never files anything: it produces "
                    "findings, a licensed human decides, and every decision is logged.",
        lifespan=lifespan,
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or new_id("req")
        set_request_context(rid, _trace_id(request))
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    origins = s.origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Request-Id",
                       "X-Dev-User", "X-Dev-Role", "X-Dev-Org"],
        expose_headers=["X-Request-Id"],
    )

    app.include_router(system.router)
    app.include_router(system.router, prefix=API_PREFIX)
    if s.service_role in ("api", "all"):
        for module in (shipments, documents, analysis, decisions, reports, pages, org):
            app.include_router(module.router, prefix=API_PREFIX)
        if s.storage_mode == "local":
            app.include_router(system.local_router)
    if s.service_role in ("worker", "all"):
        from app.worker.routes import router as worker_router

        app.include_router(worker_router)
    return app


app = create_app()
