"""Shared test fixtures: seeded sample data, isolated SQLite DB, test client."""
from __future__ import annotations

import os
import tempfile

# The app module builds the app (and its database) at import time, so point
# it at a throwaway database before that import. Otherwise test collection
# would create the real ./data/meridian.db in the checkout.
os.environ.setdefault(
    "MERIDIAN_DATABASE_URL",
    f"sqlite:///{tempfile.mkdtemp(prefix='meridian-test-')}/import.db",
)

import pytest
from fastapi.testclient import TestClient

from meridian.api.app import create_app
from meridian.core.config import Settings
from meridian.data.generate_sample_data import generate
from meridian.store.db import init_db


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    generate(str(d))
    return str(d)


@pytest.fixture(scope="session")
def settings(data_dir, tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    return Settings(
        database_url=f"sqlite:///{db_path}",
        data_dir=data_dir,
        llm_provider="none",
    )


@pytest.fixture(scope="session")
def client(settings):
    init_db(settings.database_url)
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
