"""FastAPI Application factory and lifespan initialization.

ZERO DEFAULTS Document Reader Backend.
"""

import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_auth import router as auth_router
from app.api.routes_documents import router as documents_router
from app.core.providers import close_shared_client, validate_provider_configs
from app.core.settings import get_app_settings, validate_production_safety
from app.models.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database schema
    init_db()
    validate_provider_configs()
    yield
    # Gracefully close shared HTTP client
    await close_shared_client()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Document Reader API",
        description="Dynamic document reading and field extraction matching demo.html",
        version="2.0.0",
        lifespan=lifespan,
    )

    settings = get_app_settings()
    validate_production_safety(settings)

    cors_origins_raw = os.getenv("CORS_ORIGINS", getattr(settings, "CORS_ORIGINS", "")).strip()
    if cors_origins_raw:
        origins = [orig.strip() for orig in cors_origins_raw.split(",") if orig.strip()]
    else:
        origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    # In production, disallow wildcard origin regexes; only allow strictly configured origins
    is_prod = os.getenv("APP_ENV", getattr(settings, "APP_ENV", "local")).lower() == "production"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=None if is_prod else r"^https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(documents_router)

    return app


app = create_app()
