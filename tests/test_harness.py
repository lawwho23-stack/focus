"""Tests about the tests: proof the suite cannot touch the real database."""

from pathlib import Path

from app.db import DEFAULT_DB_PATH, db_path


def test_the_suite_never_uses_the_real_database():
    assert Path(db_path()).resolve() != DEFAULT_DB_PATH.resolve()


def test_each_test_gets_an_empty_database(db):
    for table in ("idea", "commitment", "day"):
        count = db.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
        assert count == 0, f"{table} was not empty at the start of a test"


def test_ping(client):
    res = client.get("/api/ping")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
