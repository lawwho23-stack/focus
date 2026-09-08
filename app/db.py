import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent.parent / "focus.db"
SCHEMA_PATH = Path (__file__).parent / "schema.sql"

def db_path():
    return os.environ.get("FOCUS_DB", DEFAULT_DB_PATH)



def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()
    try:
        conn.executescript(SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()
        
            