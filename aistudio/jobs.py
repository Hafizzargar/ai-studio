"""Per-project job state in SQLite. Enables resume after a crash or failed scene."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing

from .project import project_dir


def _conn(pid: str) -> sqlite3.Connection:
    c = sqlite3.connect(project_dir(pid) / "jobs.db", timeout=30)
    c.execute("""CREATE TABLE IF NOT EXISTS scene_jobs(
        scene_id TEXT PRIMARY KEY, hash TEXT, status TEXT, error TEXT, duration REAL, updated REAL)""")
    return c


def get(pid: str, scene_id: str) -> dict | None:
    with closing(_conn(pid)) as c:
        r = c.execute("SELECT scene_id,hash,status,error,duration FROM scene_jobs WHERE scene_id=?",
                      (scene_id,)).fetchone()
    return dict(zip(("scene_id", "hash", "status", "error", "duration"), r)) if r else None


def set_status(pid: str, scene_id: str, hash_: str, status: str, error: str = "", duration: float | None = None):
    with closing(_conn(pid)) as c:
        c.execute("INSERT OR REPLACE INTO scene_jobs VALUES(?,?,?,?,?,?)",
                  (scene_id, hash_, status, error, duration, time.time()))
        c.commit()


def all_jobs(pid: str) -> list[dict]:
    with closing(_conn(pid)) as c:
        rows = c.execute("SELECT scene_id,hash,status,error,duration FROM scene_jobs ORDER BY scene_id").fetchall()
    return [dict(zip(("scene_id", "hash", "status", "error", "duration"), r)) for r in rows]


def reset_running(pid: str):
    """After a crash, anything left 'running' is treated as pending."""
    with closing(_conn(pid)) as c:
        c.execute("UPDATE scene_jobs SET status='pending' WHERE status='running'")
        c.commit()


def read_progress(pid: str) -> dict:
    p = project_dir(pid) / "progress.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "idle", "done": 0, "total": 0}
    if d.get("status") == "running" and time.time() - d.get("heartbeat", 0) > 60:
        d["status"] = "interrupted"   # render process died without finishing
    return d
