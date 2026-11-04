"""Script -> scenes. Rule-based segmentation (no LLM needed)."""
from __future__ import annotations

import hashlib
import json
import re

from . import config

_ABBR = ["Dr", "Mr", "Mrs", "Ms", "Prof", "St", "vs", "etc", "No", "Fig", "Jr", "Sr"]
_SENT_RE = re.compile(r"(?<=[.!?\u06D4\u061F])\s+(?=\S)")
_HEAD_RE = re.compile(r"^\s*(?:#{1,3}\s*|scene\s*\d*\s*[:\-]\s*)(.+?)\s*$", re.I)


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    for a in _ABBR:
        text = text.replace(f"{a}. ", f"{a}\u2024 ")
    text = re.sub(r"\be\.g\.", "e\u2024g\u2024", text)
    text = re.sub(r"\bi\.e\.", "i\u2024e\u2024", text)
    parts = _SENT_RE.split(text)
    return [p.replace("\u2024", ".").strip() for p in parts if p.strip()]


def new_scene(n: int, heading: str, narration: str, language: str = "en", **extra) -> dict:
    scene = {
        "scene_id": f"s{n:03d}", "heading": heading, "narration": narration, "language": language,
        "visual": {"type": "title_card"}, "background": None, "characters": [],
        "animation": None, "duration_sec": None, "subtitle": {"enabled": True},
        "source_refs": [], "camera": {"move": "slow_zoom_in"}, "dramatized": False,
        "status": "draft",
    }
    scene.update(extra)
    return scene


def script_to_scenes(text: str, language: str = "en", max_words: int = 60) -> list[dict]:
    """Headings start with '#', or 'Scene 3: Title'. Paragraphs are split into
    scenes of at most max_words so each scene stays short and re-renderable."""
    blocks: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    para: list[str] = []

    def flush():
        nonlocal para
        if para:
            blocks.append((heading, para))
            para = []

    for line in text.splitlines():
        m = _HEAD_RE.match(line)
        if m and line.strip():
            flush()
            heading = m.group(1)
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()

    scenes: list[dict] = []
    for head, lines in blocks:
        chunk: list[str] = []
        words = 0
        pieces: list[str] = []
        for sent in split_sentences(" ".join(lines)):
            w = len(sent.split())
            if chunk and words + w > max_words:
                pieces.append(" ".join(chunk))
                chunk, words = [], 0
            chunk.append(sent)
            words += w
        if chunk:
            pieces.append(" ".join(chunk))
        for piece in pieces:
            title = head or " ".join(piece.split()[:6]).rstrip(".,;:")
            scenes.append(new_scene(len(scenes) + 1, title, piece, language))
    return scenes


def scene_hash(scene: dict, settings: dict, project_title: str = "") -> str:
    """Changes whenever anything that affects the rendered clip changes."""
    keys = {
        "v": config.RENDER_VERSION,
        "scene": {k: scene.get(k) for k in
                  ("heading", "narration", "language", "visual", "camera", "subtitle", "characters", "background")},
        "project_title": project_title,
        "settings": {k: settings.get(k) for k in
                     ("voice", "tts_backend", "speed", "pause_sec", "resolution", "aspect", "fps", "theme",
                      "subtitles", "language")},
    }
    return hashlib.sha1(json.dumps(keys, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
