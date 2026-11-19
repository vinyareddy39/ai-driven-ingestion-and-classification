"""FastAPI Application factory and lifespan initialization."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes_ingest import router as ingest_router
from app.api.routes_review import router as review_router
from app.api.routes_reprocess import router as reprocess_router
from app.api.routes_observability import router as observability_router
from app.api.routes_v1 import router as v1_router
from app.core.config import get_app_settings, get_pipeline_config
from app.core.security import setup_secure_logging
from app.models.db import init_db

logger = setup_secure_logging("ecm.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and load configuration
    logger.info("Initializing ECM Ingestion Engine...")
    init_db()
    cfg = get_pipeline_config()
    logger.info(f"Loaded pipeline config version {cfg.pipeline.get('version', '1.0.0')}")

    import threading
    from app.workers.pipeline import run_pipeline_worker

    worker_thread = threading.Thread(
        target=run_pipeline_worker,
        kwargs={"queue_type": "live"},
        daemon=True,
    )
    worker_thread.start()
    logger.info("Pipeline background worker thread started for live queue.")

    yield
    logger.info("Shutting down ECM Ingestion Engine...")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="ECM Document Ingestion and Classification Pipeline",
        description="Reference implementation of AI-driven document ingestion, Presidio PII tagging, and Nuxeo ECM routing",
        version="1.0.0",
        lifespan=lifespan,
    )

    settings = get_app_settings()
    cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-User-Role"],
    )

    app.include_router(ingest_router)
    app.include_router(review_router)
    app.include_router(reprocess_router)
    app.include_router(observability_router)
    app.include_router(v1_router)

    return app


app = create_app()
