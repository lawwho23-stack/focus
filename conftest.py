import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# This block MUST run before "from app.main import app" below.
#
# app/main.py calls init_db() at import time, so a database is opened and the
# schema is written the instant that import happens -- at whatever path
# FOCUS_DB points to *then*. A monkeypatch.setenv inside a fixture runs later,
# which is too late: the real focus.db would already have been touched.
_IMPORT_GUARD_DB = Path(tempfile.mkdtemp(prefix="focus-tests-")) / "import-guard.db"
os.environ["FOCUS_DB"] = str(_IMPORT_GUARD_DB)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Give every test its own empty database.

    This works because db.py calls db_path() *inside* connect(), on every
    request -- so swapping the env var mid-test really does redirect the app.
    """
    monkeypatch.setenv("FOCUS_DB", str(tmp_path / "focus.db"))
    init_db()


@pytest.fixture
def client(fresh_db):
    """The app, talking to this test's database."""
    return TestClient(app)


@pytest.fixture
def db(fresh_db):
    """A direct connection, for seeding rows and checking what really landed."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def ready_idea(db):
    """Insert an idea whose 7-day freeze has already lifted; return its id.

    unfreeze_at is a full offset-aware ISO string on purpose. promote_idea and
    list_ideas compare these as plain text, so seeding a bare "2026-09-01"
    would make the assertions pass for the wrong reason.
    """

    def _insert(text="A ready idea"):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        cur = db.execute(
            "INSERT INTO idea (text, created_at, unfreeze_at) VALUES (?, ?, ?)",
            (text, past, past),
        )
        db.commit()
        return cur.lastrowid

    return _insert


@pytest.fixture
def promote(client):
    """Promote an idea through the real API."""

    def _promote(idea_id, lane="learning", done_when="It is shipped"):
        return client.post(
            f"/api/ideas/{idea_id}/promote",
            json={"done_when": done_when, "lane": lane},
        )

    return _promote
