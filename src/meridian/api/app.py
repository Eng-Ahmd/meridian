"""FastAPI application factory."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from meridian.api.routes import router
from meridian.core.config import Settings, get_settings
from meridian.core.logging import configure_logging
from meridian.store.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    init_db(settings.database_url)

    app = FastAPI(
        title="Meridian",
        description="Agentic AI operations layer for supply chains.",
        version="0.1.0",
    )
    app.state.settings = settings
    app.include_router(router)

    web_dir = os.path.join(os.path.dirname(settings.data_dir.rstrip("/")) or ".", "web")
    if not os.path.isdir(web_dir):
        # Fall back to the web/ directory next to the repo root layout.
        web_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "web"))
    if os.path.isdir(web_dir):
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


app = create_app()
