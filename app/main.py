import sqlite3
from pathlib import Path
from typing import Literal
from fastapi.staticfiles import StaticFiles
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from app.db import connect, init_db
from zoneinfo import ZoneInfo
app = FastAPI()
init_db()

FREEZE_DAYS = 7
LOCAL_TZ = ZoneInfo("Asia/Bangkok")

class NewIdea(BaseModel):
    text: str = Field(min_length=1, max_length=500)

class PromoteIdea(BaseModel):
    done_when: str = Field(min_length=1, max_length=500)
    lane: Literal["learning", "income", "client"]

class KillCommitment(BaseModel):
    reason: str = Field(min_length=1,max_length=500)

class SetPrimary(BaseModel):
    commitment_id: int

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def today_str():
    return datetime.now(LOCAL_TZ).date().isoformat()





@app.get("/api/ping")
def ping():
    return {"ok": True}



@app.post("/api/ideas")
def create_idea(new: NewIdea):
    now = datetime.now(timezone.utc)
    unfreeze = now + timedelta(days=FREEZE_DAYS)
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO idea(text, created_at, unfreeze_at) VALUES (?, ?, ?)",
            (new.text, now.isoformat(), unfreeze.isoformat()),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()

@app.get("/api/ideas")
def list_ideas():
    now = now_iso()
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, text, created_at, unfreeze_at FROM idea "
            "WHERE dropped_at IS NULL AND promoted_commitment_id IS NULL "
            "ORDER BY id DESC"
        ).fetchall()
        return [dict(r) | {"ready": r["unfreeze_at"] <= now} for r in rows]
    finally:
        conn.close()


@app.post("/api/ideas/{idea_id}/promote")
def promote_idea(idea_id: int, body: PromoteIdea):
    now = now_iso()
    conn = connect()
    try:
        idea = conn.execute(
            "SELECT id, text, unfreeze_at, promoted_commitment_id, dropped_at "
            "FROM idea WHERE id = ?",
            (idea_id,),
        ).fetchone()
        if idea is None:
            raise HTTPException(404, "No such idea")
        if idea["dropped_at"] is not None:
            raise HTTPException(409, "That idea was dropped")
        if idea["promoted_commitment_id"] is not None:
            raise HTTPException(409, "That idea is already a commitment")
        if idea["unfreeze_at"] > now:
            raise HTTPException(409, f"Frozen until {idea['unfreeze_at'][:10]}")
        taken = {
            r["active_slot"]
            for r in conn.execute("SELECT active_slot FROM commitment WHERE status = 'active'")
                                  
        }
        free = next((s for s in (1, 2, 3) if s not in taken), None)
        if free is None:
            raise HTTPException(409, "All 3 slots are full - finish or kill one first")

        cur = conn.execute(
            "INSERT INTO commitment "
            "(title, done_when, lane, active_slot, created_at, last_touched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (idea["text"], body.done_when, body.lane, free, now, now),
        )
        conn.execute(
            "UPDATE idea SET promoted_commitment_id = ? WHERE id = ?",
            (cur.lastrowid, idea_id),
        )
        conn.commit()
        return {"commitment_id": cur.lastrowid, "slot": free}
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(409, "The slots changed while you were promoting - try again")
    finally:
        conn.close()

@app.get("/api/commitments")
def list_commitments():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, title, done_when, lane, status, active_slot, kill_reason, "
            "created_at, finished_at, last_touched_at "
            "FROM commitment ORDER BY active_slot, id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

@app.post("/api/commitments/{commitment_id}/finish")
def finish_commitment(commitment_id: int):
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE commitment SET status = 'done', finished_at = ?, active_slot = NULL "
            "WHERE id = ? AND status = 'active'",
            (now_iso(), commitment_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "No active commitment with that id")
        conn.commit()
        return {"id": commitment_id, "status": "done"}
    finally:
        conn.close()

@app.post("/api/commitments/{commitment_id}/kill")
def kill_commitment(commitment_id: int, body: KillCommitment):
    conn = connect()
    try:
        cur = conn.execute(
            "UPDATE commitment SET status = 'killed', kill_reason = ?, finished_at = ?, "
            "active_slot = NULL "
            "WHERE id = ? AND status = 'active'",
            (body.reason, now_iso(), commitment_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "No active commitment with that id")
        conn.commit()
        return {"id": commitment_id, "status": "killed"}
    finally:
        conn.close()


@app.post("/api/today/primary")
def set_primary(body: SetPrimary):
    today = today_str()
    conn = connect()
    try:
        active = conn.execute(
            "SELECT id FROM commitment WHERE id = ? AND status = 'active'",
            (body.commitment_id,),
        ).fetchone()
        if active is None:
            raise HTTPException(409, "That is not an active commitment")
        conn.execute(
            "INSERT INTO day (date, primary_commitment_id) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET primary_commitment_id = excluded.primary_commitment_id",
            (today, body.commitment_id),
        )
        conn.execute(
            "UPDATE commitment SET last_touched_at = ? WHERE id = ?",
            (now_iso(), body.commitment_id),
        )
        conn.commit()
        return {"date": today, "primary_commitment_id": body.commitment_id}
    finally:
        conn.close()

@app.get("/api/today")
def get_today():
    today = today_str()
    conn = connect()
    try:
        day = conn.execute(
            "SELECT date, primary_commitment_id, primary_moved, energy, note, closed_at "
            "FROM day WHERE date = ?",
            (today,),
        ).fetchone()
        active = [
            dict(r)
            for r in conn.execute(
                "SELECT id, title, done_when, lane, active_slot, last_touched_at "
                "FROM commitment WHERE status = 'active' ORDER BY active_slot"
            )

        ]
        primary_id = day["primary_commitment_id"] if day else None
        primary = next((c for c in active if c["id"] == primary_id), None)
        return {"date": today, "primary": primary, "active": active}
    finally:
        conn.close()

STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True),
name="static")