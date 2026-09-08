"""What the database itself refuses -- raw SQL, no HTTP.

Each `match=` pins the specific constraint that must fire. Without it a test
passes on *any* IntegrityError, so an unrelated new NOT NULL column would make
all of these pass green while the real CHECKs were gone.
"""

import sqlite3

import pytest


def add_active(db, slot, title="A thing"):
    db.execute(
        "INSERT INTO commitment (title, done_when, lane, status, active_slot, created_at) "
        "VALUES (?, 'x', 'learning', 'active', ?, '2026-09-08T00:00:00+00:00')",
        (title, slot),
    )
    db.commit()


def fill_all_three_slots(db):
    for slot in (1, 2, 3):
        add_active(db, slot)


def test_a_commitment_needs_a_done_when(db):
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed"):
        db.execute(
            "INSERT INTO commitment (title, done_when, lane, active_slot, created_at) "
            "VALUES ('A thing', NULL, 'learning', 1, '2026-09-08T00:00:00+00:00')"
        )


def test_the_lane_must_be_one_of_the_three(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed: lane IN"):
        db.execute(
            "INSERT INTO commitment (title, done_when, lane, active_slot, created_at) "
            "VALUES ('A thing', 'x', 'personal', 1, '2026-09-08T00:00:00+00:00')"
        )


def test_the_status_must_be_known(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed: status IN"):
        db.execute(
            "INSERT INTO commitment (title, done_when, lane, status, active_slot, created_at) "
            "VALUES ('A thing', 'x', 'learning', 'paused', 1, '2026-09-08T00:00:00+00:00')"
        )


def test_a_killed_commitment_needs_a_reason(db):
    with pytest.raises(
        sqlite3.IntegrityError, match="status <> 'killed' OR kill_reason IS NOT NULL"
    ):
        db.execute(
            "INSERT INTO commitment (title, done_when, lane, status, active_slot, created_at) "
            "VALUES ('A thing', 'x', 'learning', 'killed', NULL, '2026-09-08T00:00:00+00:00')"
        )


def test_a_finished_commitment_frees_its_slot(db):
    add_active(db, 2)
    db.execute("UPDATE commitment SET status = 'done', active_slot = NULL WHERE active_slot = 2")
    db.commit()

    add_active(db, 2, title="the next thing")

    rows = db.execute("SELECT status, active_slot FROM commitment ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("done", None), ("active", 2)]


@pytest.mark.parametrize(
    "slot, refusal",
    [
        (None, "status <> 'active' OR active_slot IS NOT NULL"),
        (0, "active_slot BETWEEN 1 AND 3"),
        (4, "active_slot BETWEEN 1 AND 3"),
        (1, "UNIQUE constraint failed"),
        (2, "UNIQUE constraint failed"),
        (3, "UNIQUE constraint failed"),
    ],
)
def test_a_fourth_active_commitment_is_refused(db, slot, refusal):
    fill_all_three_slots(db)
    with pytest.raises(sqlite3.IntegrityError, match=refusal):
        add_active(db, slot, title="The fourth thing")


def test_a_slot_is_only_guarded_while_the_commitment_is_active(db):
    """The unique index is partial: WHERE status = 'active'.

    test_a_finished_commitment_frees_its_slot cannot prove this -- finishing
    also NULLs the slot, and a unique index allows unlimited NULLs either way.
    Here the done row *keeps* slot 2, so only the WHERE clause lets slot 2 be
    reused. Drop it from the index and this is the test that goes red.
    """
    add_active(db, 2)
    db.execute("UPDATE commitment SET status = 'done' WHERE active_slot = 2")
    db.commit()

    add_active(db, 2, title="the next thing")

    held = db.execute(
        "SELECT count(*) AS n FROM commitment WHERE status = 'active' AND active_slot = 2"
    ).fetchone()["n"]
    assert held == 1
