"""What the API refuses, and the few things it must allow.

Everything here goes through real HTTP via TestClient. The raw-SQL rules live
in test_schema.py; these are the rules Python enforces on top of them.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


def bangkok_today():
    """Today's date where Laww actually is -- computed independently of app code."""
    return datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()


# --- capture and the vault ---------------------------------------------------


def test_capturing_an_idea_puts_it_in_the_vault_frozen(client):
    res = client.post("/api/ideas", json={"text": "Ship the thing"})
    assert res.status_code == 200
    idea_id = res.json()["id"]

    vault = client.get("/api/ideas").json()
    assert [(i["id"], i["text"], i["ready"]) for i in vault] == [
        (idea_id, "Ship the thing", False)
    ]


def test_an_empty_idea_is_refused(client):
    assert client.post("/api/ideas", json={"text": ""}).status_code == 422
    assert client.post("/api/ideas", json={}).status_code == 422
    assert client.get("/api/ideas").json() == []


def test_an_idea_past_its_freeze_shows_as_ready(client, ready_idea):
    ready_idea()
    assert [i["ready"] for i in client.get("/api/ideas").json()] == [True]


def test_a_promoted_idea_leaves_the_vault(client, ready_idea, promote):
    assert promote(ready_idea()).status_code == 200
    assert client.get("/api/ideas").json() == []


# --- promote: every refusal --------------------------------------------------


def test_a_fresh_idea_cannot_be_promoted_yet(client, promote):
    idea_id = client.post("/api/ideas", json={"text": "Too soon"}).json()["id"]
    res = promote(idea_id)
    assert res.status_code == 409
    assert res.json()["detail"].startswith("Frozen until ")


def test_promoting_an_unknown_idea_is_404(promote):
    res = promote(999)
    assert res.status_code == 404
    assert res.json()["detail"] == "No such idea"


def test_an_idea_cannot_be_promoted_twice(ready_idea, promote):
    idea_id = ready_idea()
    assert promote(idea_id).status_code == 200

    res = promote(idea_id)
    assert res.status_code == 409
    assert res.json()["detail"] == "That idea is already a commitment"


def test_a_dropped_idea_cannot_be_promoted(db, ready_idea, promote):
    idea_id = ready_idea()
    db.execute("UPDATE idea SET dropped_at = '2026-09-08T00:00:00+00:00' WHERE id = ?", (idea_id,))
    db.commit()

    res = promote(idea_id)
    assert res.status_code == 409
    assert res.json()["detail"] == "That idea was dropped"


def test_the_lane_must_be_a_real_lane(ready_idea, promote):
    assert promote(ready_idea(), lane="personal").status_code == 422


def test_a_commitment_needs_a_finish_line(ready_idea, promote):
    assert promote(ready_idea(), done_when="").status_code == 422


# --- the cap, through the API ------------------------------------------------


def test_promotes_fill_slots_one_two_three_in_order(ready_idea, promote):
    slots = [promote(ready_idea(f"Idea {n}")).json()["slot"] for n in range(3)]
    assert slots == [1, 2, 3]


def test_only_three_commitments_can_be_active(ready_idea, promote):
    for n in range(3):
        assert promote(ready_idea(f"Idea {n}")).status_code == 200

    fourth = promote(ready_idea("One too many"))
    assert fourth.status_code == 409
    assert fourth.json()["detail"] == "All 3 slots are full - finish or kill one first"


# --- finish ------------------------------------------------------------------


def test_finishing_clears_the_slot_and_frees_it_for_reuse(client, ready_idea, promote):
    ids = [promote(ready_idea(f"Idea {n}")).json()["commitment_id"] for n in range(3)]

    assert client.post(f"/api/commitments/{ids[1]}/finish").status_code == 200

    done = next(c for c in client.get("/api/commitments").json() if c["id"] == ids[1])
    assert done["status"] == "done"
    assert done["active_slot"] is None
    assert done["finished_at"] is not None

    assert promote(ready_idea("Takes the free slot")).json()["slot"] == 2


def test_finishing_twice_is_refused(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]
    assert client.post(f"/api/commitments/{cid}/finish").status_code == 200

    res = client.post(f"/api/commitments/{cid}/finish")
    assert res.status_code == 409
    assert res.json()["detail"] == "No active commitment with that id"


def test_finishing_an_unknown_commitment_is_refused(client):
    assert client.post("/api/commitments/999/finish").status_code == 409


# --- kill --------------------------------------------------------------------


def test_killing_requires_a_reason(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]

    assert client.post(f"/api/commitments/{cid}/kill", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/commitments/{cid}/kill", json={}).status_code == 422

    # and the refusal changed nothing
    assert [c["id"] for c in client.get("/api/today").json()["active"]] == [cid]


def test_killing_records_the_reason_and_frees_the_slot(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]

    res = client.post(f"/api/commitments/{cid}/kill", json={"reason": "Wrong bet"})
    assert res.status_code == 200

    killed = next(c for c in client.get("/api/commitments").json() if c["id"] == cid)
    assert killed["status"] == "killed"
    assert killed["kill_reason"] == "Wrong bet"
    assert killed["active_slot"] is None

    assert promote(ready_idea("Takes the free slot")).json()["slot"] == 1


def test_a_finished_commitment_cannot_be_killed(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]
    client.post(f"/api/commitments/{cid}/finish")

    res = client.post(f"/api/commitments/{cid}/kill", json={"reason": "Too late"})
    assert res.status_code == 409


# --- today -------------------------------------------------------------------


def test_today_is_empty_before_anything_happens(client):
    today = client.get("/api/today").json()
    assert today == {"date": bangkok_today(), "primary": None, "active": []}


def test_setting_the_primary_writes_the_day_row(client, db, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]

    res = client.post("/api/today/primary", json={"commitment_id": cid})
    assert res.status_code == 200

    rows = db.execute("SELECT date, primary_commitment_id FROM day").fetchall()
    assert len(rows) == 1
    assert rows[0]["date"] == bangkok_today()
    assert rows[0]["primary_commitment_id"] == cid


def test_setting_the_primary_twice_updates_one_row(client, db, ready_idea, promote):
    first = promote(ready_idea("A")).json()["commitment_id"]
    second = promote(ready_idea("B")).json()["commitment_id"]

    client.post("/api/today/primary", json={"commitment_id": first})
    client.post("/api/today/primary", json={"commitment_id": second})

    rows = db.execute("SELECT primary_commitment_id FROM day").fetchall()
    assert len(rows) == 1, "the ON CONFLICT upsert should update, not insert a second day"
    assert rows[0]["primary_commitment_id"] == second


def test_setting_the_primary_touches_the_commitment(client, db, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]
    read = "SELECT last_touched_at FROM commitment WHERE id = ?"
    before = db.execute(read, (cid,)).fetchone()["last_touched_at"]

    client.post("/api/today/primary", json={"commitment_id": cid})

    assert db.execute(read, (cid,)).fetchone()["last_touched_at"] > before


def test_only_an_active_commitment_can_be_the_primary(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]
    client.post(f"/api/commitments/{cid}/finish")

    res = client.post("/api/today/primary", json={"commitment_id": cid})
    assert res.status_code == 409
    assert res.json()["detail"] == "That is not an active commitment"


def test_today_returns_the_primary_and_the_active_list(client, ready_idea, promote):
    ids = [promote(ready_idea(f"Idea {n}")).json()["commitment_id"] for n in range(3)]
    client.post("/api/today/primary", json={"commitment_id": ids[2]})

    today = client.get("/api/today").json()
    assert today["primary"]["id"] == ids[2]
    assert [c["id"] for c in today["active"]] == ids
    assert [c["active_slot"] for c in today["active"]] == [1, 2, 3]


def test_a_finished_primary_disappears_from_today(client, ready_idea, promote):
    cid = promote(ready_idea()).json()["commitment_id"]
    client.post("/api/today/primary", json={"commitment_id": cid})
    client.post(f"/api/commitments/{cid}/finish")

    today = client.get("/api/today").json()
    assert today["primary"] is None
    assert today["active"] == []


# --- routing -----------------------------------------------------------------

ROUTES = [
    ("GET", "/api/ping"),
    ("POST", "/api/ideas"),
    ("GET", "/api/ideas"),
    ("POST", "/api/ideas/1/promote"),
    ("GET", "/api/commitments"),
    ("POST", "/api/commitments/1/finish"),
    ("POST", "/api/commitments/1/kill"),
    ("POST", "/api/today/primary"),
    ("GET", "/api/today"),
]


@pytest.mark.parametrize("method, path", ROUTES)
def test_the_static_mount_does_not_shadow_the_api(client, method, path):
    """StaticFiles is mounted at "/". A route defined below that mount in
    main.py never matches, and StaticFiles answers instead -- 405 for a POST,
    404 for a GET. Both have already cost real debugging time here.
    """
    res = client.request(method, path, json={})
    assert res.status_code not in (404, 405), (
        f"{method} {path} fell through to the static mount -- is the route "
        "defined below app.mount('/') at the bottom of main.py?"
    )
