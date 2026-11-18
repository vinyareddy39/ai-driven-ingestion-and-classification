"""FastAPI Application factory and lifespan initialization."""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes_ingest import router as ingest_router
from app.api.routes_review import router as review_router
from app.api.routes_reprocess import router as reprocess_router
from app.api.routes_observability import router as observability_router
from app.core.config import get_pipeline_config
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(ingest_router)
    app.include_router(review_router)
    app.include_router(reprocess_router)
    app.include_router(observability_router)

    return app


app = create_app()
