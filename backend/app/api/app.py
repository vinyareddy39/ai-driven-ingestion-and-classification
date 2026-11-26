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

    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"^https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(documents_router)

    return app


app = create_app()
