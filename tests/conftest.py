"""
Test environment bootstrap.

Sets isolated env vars and a temp SQLite DB *before* any nabdh_* module is
imported, so tests never touch the real nabdh.db. This module-level code
runs at collection time (before any fixtures), which matters because
config.py reads os.environ at import time.
"""
import os
import pathlib
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

_tmp_dir = tempfile.mkdtemp(prefix="nabdh_test_")
_TEST_DB_PATH = str(pathlib.Path(_tmp_dir) / "test_nabdh.db")

_TEST_ENV = {
    "DATABASE_PATH":        _TEST_DB_PATH,
    "JWT_SECRET_KEY":       "test-secret-key-not-for-production-use-only-in-pytest",
    "ADMIN_USERNAME":       "admin",
    "ADMIN_PASSWORD":       "TestAdmin@123",
    "OPERATOR_USERNAME":    "operator",
    "OPERATOR_PASSWORD":    "TestOperator@123",
    "VIEWER_USERNAME":      "viewer",
    "VIEWER_PASSWORD":      "TestViewer@123",
    "REDIS_URL":            "",
    "ALERT_WEBHOOK_URL":    "",
    "ALLOWED_ORIGINS":      "http://localhost:8501",
}
for _k, _v in _TEST_ENV.items():
    os.environ[_k] = _v

import database  # noqa: E402

database.init_db()

from alembic.config import Config  # noqa: E402
from alembic import command  # noqa: E402

_alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        yield c


def _login(client, username, password):
    resp = client.post("/auth/login", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_token(client):
    return _login(client, _TEST_ENV["ADMIN_USERNAME"], _TEST_ENV["ADMIN_PASSWORD"])


@pytest.fixture(scope="session")
def operator_token(client):
    return _login(client, _TEST_ENV["OPERATOR_USERNAME"], _TEST_ENV["OPERATOR_PASSWORD"])


@pytest.fixture(scope="session")
def viewer_token(client):
    return _login(client, _TEST_ENV["VIEWER_USERNAME"], _TEST_ENV["VIEWER_PASSWORD"])


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
