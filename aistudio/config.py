"""Paths, tool discovery and frame-size helpers."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = Path(os.environ.get("AISTUDIO_PROJECTS", ROOT / "projects"))
VENDOR_DIR = ROOT / "vendor"
VOICES_DIR = VENDOR_DIR / "voices"
FONTS_DIR = ROOT / "assets" / "fonts"
IS_WINDOWS = os.name == "nt"

# Bump when rendering output changes, so cached scene clips are invalidated.
RENDER_VERSION = 4
SCHEMA_VERSION = 1

_RES = {"720p": 720, "1080p": 1080}
ASPECTS = ("16:9", "9:16", "1:1")


def find_exe(name: str) -> str | None:
    """Look in vendor/ first (bundled tools), then on PATH."""
    exe = name + (".exe" if IS_WINDOWS else "")
    for cand in (VENDOR_DIR / exe, VENDOR_DIR / name / exe):
        if cand.exists():
            return str(cand)
    return shutil.which(name)


def frame_size(resolution: str = "720p", aspect: str = "16:9") -> tuple[int, int]:
    short = _RES.get(resolution, 720)
    if aspect == "9:16":
        return short, round(short * 16 / 9 / 2) * 2
    if aspect == "1:1":
        return short, short
    return round(short * 16 / 9 / 2) * 2, short


def tool_report() -> dict:
    from . import tts
    return {
        "ffmpeg": find_exe("ffmpeg"),
        "ffprobe": find_exe("ffprobe"),
        "piper": find_exe("piper"),
        "piper_voices": tts.piper_voices(),
        "tts_backends": tts.available_backends(),
        "projects_dir": str(PROJECTS_DIR),
    }
