"""Project storage: crash-safe save (atomic write + rolling backups)."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import config

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")
MODES = ("educational", "documentary", "creative", "history")
KEEP_BACKUPS = 5


def default_settings() -> dict:
    return {
        "language": "en",            # en | ur | ur-roman
        "voice": "",                 # piper voice name (file stem in vendor/voices) or "sapi:<name>"
        "tts_backend": "auto",       # auto | piper | sapi | espeak | silent
        "speed": 1.0,
        "pause_sec": 0.35,
        "resolution": "720p",
        "aspect": "16:9",
        "fps": 24,
        "theme": "educational",
        "subtitles": {
            "enabled": True, "font": "Arial", "size_ratio": 0.055,
            "primary": "FFFFFF", "outline": "000000", "position": "bottom",
            "highlight_words": [], "highlight_color": "FFD166",
        },
        "music": {"path": None, "volume": 0.15},
    }


def project_dir(pid: str) -> Path:
    if not ID_RE.match(pid):
        raise ValueError(f"Invalid project id: {pid!r}")
    return config.PROJECTS_DIR / pid


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40] or "project"


def create(title: str, mode: str = "educational", **settings) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    pid = f"{slugify(title)}-{datetime.now():%Y%m%d-%H%M%S}"
    base = project_dir(pid)
    for sub in ("source", "audio", "scenes", "cache", "renders", "logs", "backups"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    st = default_settings()
    st["theme"] = mode
    for k, v in settings.items():
        if k in st and v not in (None, ""):
            st[k] = v
    data = {
        "schema_version": config.SCHEMA_VERSION, "id": pid, "title": title, "mode": mode,
        "created": _now(), "updated": _now(), "settings": st,
        "source": {"pdf": None}, "scenes": [],
    }
    save(pid, data)
    return data


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def save(pid: str, data: dict) -> None:
    """Atomic write; the previous version is kept as a rolling backup."""
    base = project_dir(pid)
    base.mkdir(parents=True, exist_ok=True)
    data["updated"] = _now()
    tmp = base / "project.json.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    cur = base / "project.json"
    if cur.exists():
        bdir = base / "backups"
        bdir.mkdir(exist_ok=True)
        shutil.copy2(cur, bdir / f"project-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time()*1000)%1000:03d}.json")
        for old in sorted(bdir.glob("project-*.json"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
    os.replace(tmp, cur)


def load(pid: str) -> dict:
    base = project_dir(pid)
    cur = base / "project.json"
    try:
        data = json.loads(cur.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        backups = sorted((base / "backups").glob("project-*.json"))
        if not backups:
            raise FileNotFoundError(f"Project {pid} not found or unreadable")
        data = json.loads(backups[-1].read_text(encoding="utf-8"))  # recover from crash
    return migrate(data)


def migrate(data: dict) -> dict:
    v = data.get("schema_version", 0)
    if v < 1:
        data.setdefault("settings", default_settings())
        data.setdefault("scenes", [])
        data.setdefault("source", {"pdf": None})
        data["schema_version"] = 1
    merged = default_settings()
    for k, val in data.get("settings", {}).items():
        if isinstance(val, dict) and isinstance(merged.get(k), dict):
            merged[k].update(val)
        else:
            merged[k] = val
    data["settings"] = merged
    return data


def list_projects() -> list[dict]:
    out = []
    if not config.PROJECTS_DIR.exists():
        return out
    for p in sorted(config.PROJECTS_DIR.iterdir(), reverse=True):
        if (p / "project.json").exists() and ID_RE.match(p.name):
            try:
                d = load(p.name)
                out.append({"id": d["id"], "title": d["title"], "mode": d["mode"],
                            "updated": d.get("updated"), "scenes": len(d.get("scenes", []))})
            except Exception:
                continue
    return out
