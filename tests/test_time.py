"""The clock. The day must flip at Bangkok midnight, not UTC midnight.

main.py stores timestamps in UTC (now_iso) but decides *which day it is* in
Asia/Bangkok (today_str). Before Step 0 both were UTC, so anything captured
between midnight and 07:00 local filed itself to yesterday.
"""

from datetime import datetime, timedelta, timezone

import app.main
from app.main import FREEZE_DAYS, now_iso, today_str

# 18:30 UTC on the 8th is 01:30 on the 9th in Bangkok (+07).
# Code that reads the date in UTC says the 8th here, and is wrong.
FIXED = datetime(2026, 9, 8, 18, 30, tzinfo=timezone.utc)


class FrozenClock:
    """Stands in for the `datetime` name inside app.main."""

    @staticmethod
    def now(tz=None):
        return FIXED.astimezone(tz) if tz else FIXED.replace(tzinfo=None)


def test_today_str_uses_bangkok_not_utc(monkeypatch):
    monkeypatch.setattr(app.main, "datetime", FrozenClock)

    assert today_str() == "2026-09-09"
    # ...while the stored timestamp stays UTC. Both must be true at once.
    assert now_iso().startswith("2026-09-08T18:30")


def test_the_day_row_is_written_with_the_bangkok_date(
    client, db, ready_idea, promote, monkeypatch
):
    cid = promote(ready_idea()).json()["commitment_id"]

    monkeypatch.setattr(app.main, "datetime", FrozenClock)
    client.post("/api/today/primary", json={"commitment_id": cid})

    assert db.execute("SELECT date FROM day").fetchone()["date"] == "2026-09-09"


def test_capturing_freezes_an_idea_for_seven_days(client, db):
    assert FREEZE_DAYS == 7

    client.post("/api/ideas", json={"text": "A new idea"})
    row = db.execute("SELECT created_at, unfreeze_at FROM idea").fetchone()

    created = datetime.fromisoformat(row["created_at"])
    unfreeze = datetime.fromisoformat(row["unfreeze_at"])
    assert unfreeze - created == timedelta(days=7)
    assert unfreeze > datetime.now(timezone.utc)
