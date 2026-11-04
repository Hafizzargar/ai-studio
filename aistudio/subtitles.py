"""SRT (export) and ASS (styled burn-in) subtitle writers."""
from __future__ import annotations

import re
import textwrap
from pathlib import Path


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_srt(cues: list[dict], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(c['start'])} --> {_srt_time(c['end'])}", c["text"], ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _bgr(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#").upper().rjust(6, "0")
    return f"{h[4:6]}{h[2:4]}{h[0:2]}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def write_ass(cues: list[dict], path: Path, width: int, height: int, style: dict) -> None:
    size = max(18, round(height * float(style.get("size_ratio", 0.055))))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(style.get("position", "bottom"), 2)
    margin_v = round(height * 0.06)
    per_line = max(16, int(width / (size * 0.55)))
    hl = [w for w in style.get("highlight_words", []) if w]
    hl_re = re.compile("(" + "|".join(re.escape(w) for w in hl) + ")", re.I) if hl else None
    hl_col = _bgr(style.get("highlight_color", "FFD166"))
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.get('font', 'Arial')},{size},&H00{_bgr(style.get('primary', 'FFFFFF'))},&H000000FF,"
        f"&H00{_bgr(style.get('outline', '000000'))},&H64000000,0,0,0,0,100,100,0,0,1,{max(2, size // 16)},1,"
        f"{align},{round(width * 0.06)},{round(width * 0.06)},{margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for c in cues:
        body = r"\N".join(textwrap.wrap(c["text"], per_line) or [""])
        body = _escape(body)
        if hl_re:
            body = hl_re.sub(lambda m: "{\\c&H" + hl_col + "&}" + m.group(0) + "{\\r}", body)
        rows.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{body}")
    Path(path).write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
