"""Scene background images (Pillow). Rendered at 1.5x output size so slow zoom stays sharp."""
from __future__ import annotations

from collections import Counter
import re
import textwrap
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont, features

from . import config
from .pdfio import find_highlights
from .scenes import split_sentences

SUPERSAMPLE = 1.5
THEMES = {  # top colour, bottom colour, accent
    "educational": ((16, 42, 67), (14, 94, 102), (255, 209, 102)),
    "documentary": ((28, 28, 32), (66, 52, 40), (242, 169, 59)),
    "creative": ((58, 28, 94), (181, 78, 64), (255, 224, 138)),
    "history": ((52, 30, 24), (110, 72, 40), (235, 200, 120)),
}
_WIN_FONTS = ["segoeui.ttf", "arial.ttf", "tahoma.ttf"]
_LINUX_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
_DIAGRAM_CARD = (8, 25, 40)
_DIAGRAM_STOPWORDS = frozenset(
    "a about again all also always an and are around as at back be because been begins being "
    "becomes billions both but by called can could changes cool cools depending did do does during "
    "each eventually fall falls first for form from further gather gathers grow had has have heats "
    "heavy here how into invisible is it its keep known lesson life liquid make makes may melting "
    "more most moving much movement of on or our out possible process release releases remember "
    "returns rises same she short so soaks some steps such than that the their them then there these "
    "they this through to together too turn turns under up uses was we welcome were what when which "
    "while who will with within would you your flow flows".split()
)
_DIAGRAM_PRIORITY = frozenset(
    "chlorophyll cloud clouds collection condensation droplets evaporation food groundwater hail lake lakes "
    "leaves light ocean oceans planet precipitation rain river rivers sea sky sleet snow stream "
    "streams sun transpiration vapour vapor water".split()
)
_DIAGRAM_ROOT_IGNORES = frozenset(
    "ai phase project sample sapi studio test video".split()
)
_DIAGRAM_COLORS = (
    (68, 210, 230),
    (255, 176, 75),
    (116, 220, 148),
    (194, 143, 255),
    (255, 126, 158),
)
_DIAGRAM_MUTED = (61, 82, 101)
_DIAGRAM_TEXT_MUTED = (139, 158, 174)


def _font_path(bold: bool = False) -> str | None:
    cands = sorted(config.FONTS_DIR.glob("*.ttf")) + sorted(config.FONTS_DIR.glob("*.otf"))
    pref = [p for p in cands if ("Bold" in p.name) == bold] or cands
    if pref:
        return str(pref[0])
    if config.IS_WINDOWS:
        for n in (["segoeuib.ttf"] if bold else []) + _WIN_FONTS:
            p = Path("C:/Windows/Fonts") / n
            if p.exists():
                return str(p)
    for p in _LINUX_FONTS:
        if Path(p).exists():
            return p
    return None


def _font(size: int, bold: bool = False):
    path = _font_path(bold)
    engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
    try:
        return ImageFont.truetype(path, size, layout_engine=engine) if path else ImageFont.load_default()
    except OSError:
        return ImageFont.load_default()


def _gradient(size, top, bottom) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def _wrap(draw, text, font, max_w) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _diagram_root(project_title: str) -> str:
    words = [
        match.group()
        for match in re.finditer(r"[A-Za-z][A-Za-z'-]*", project_title)
        if match.group().casefold() not in _DIAGRAM_ROOT_IGNORES
    ]
    return " ".join(words[:3])


def _diagram_labels(scene: dict, limit: int = 4, project_title: str = "") -> list[str]:
    text = scene.get("narration", "")
    root = _diagram_root(project_title)
    root_words = {word.casefold() for word in root.split()}
    matches = list(re.finditer(r"[A-Za-z][A-Za-z'-]{2,}", text))
    words = [(m.group(), m.group().casefold(), m.start(), m.end()) for m in matches]
    heading_words = {
        match.group().casefold()
        for match in re.finditer(r"[A-Za-z][A-Za-z'-]{2,}", scene.get("heading", ""))
    }
    content = [word for word in words
               if word[1] not in _DIAGRAM_STOPWORDS and word[1] not in heading_words
               and word[1] not in root_words]
    content.extend(word for word in words
                   if word[1] in heading_words and word[1] in _DIAGRAM_PRIORITY
                   and word[1] not in root_words and word not in content)
    if not content:
        content = [(m.group(), m.group().casefold(), m.start(), m.end())
                   for m in re.finditer(r"[A-Za-z][A-Za-z'-]{2,}", scene.get("heading", ""))]
    if not content:
        return [root] if root else []

    counts = Counter(word[1] for word in content)
    candidates: list[tuple[str, tuple[str, ...], float, int]] = []
    for i, (display, normalized, start, end) in enumerate(content):
        score = 2 + counts[normalized] * 2 + min(len(normalized), 10) / 10
        if normalized in _DIAGRAM_PRIORITY:
            score += 4
        if normalized in heading_words:
            score += 16
        candidates.append((display, (normalized,), score, start))
        if i + 1 < len(content):
            next_display, next_normalized, next_start, _ = content[i + 1]
            if text[end:next_start].isspace():
                phrase = f"{display} {next_display}"
                phrase_key = (normalized, next_normalized)
                phrase_score = 5 + sum(counts[word] for word in phrase_key) + min(
                    len(phrase), 16
                ) / 16
                phrase_score += sum(word in _DIAGRAM_PRIORITY for word in phrase_key) * 2
                candidates.append((phrase, phrase_key, phrase_score, start))

    candidates.sort(key=lambda item: (-item[2], -len(item[1]), item[3]))
    selected: list[tuple[str, tuple[str, ...], int]] = []
    used_words: set[str] = set()
    for label, key, _, start in candidates:
        if used_words.isdisjoint(key):
            selected.append((label, key, start))
            used_words.update(key)
            if len(selected) == limit:
                break
    concepts = [label for label, _, _ in sorted(selected, key=lambda item: item[2])]
    return ([root] if root else []) + concepts


def _diagram_layout(size: tuple[int, int], labels: list[str]) -> list[tuple[int, int, int, int]]:
    width, height = size
    has_root = len(labels) > 1
    if width / height > 1.2 and has_root:
        root_box_height = round(height * 0.16)
        child_height = round(height * 0.09)
        child_gap = round(height * 0.025)
        child_left = round(width * 0.56)
        child_width = round(width * 0.38)
        child_top = round(height * 0.39)
        boxes = [
            (child_left, child_top + i * (child_height + child_gap),
             child_left + child_width, child_top + i * (child_height + child_gap) + child_height)
            for i in range(len(labels) - 1)
        ]
        root_center = round((boxes[0][1] + boxes[-1][3]) / 2)
        root_left = round(width * 0.07)
        root_width = round(width * 0.29)
        root_top = root_center - root_box_height // 2
        return [(root_left, root_top, root_left + root_width, root_top + root_box_height), *boxes]

    if width / height > 1.2:
        card_width, card_height = round(width * 0.72), round(height * 0.09)
        left, top = (width - card_width) // 2, round(height * 0.39)
        gap = round(height * 0.025)
    else:
        card_width, card_height = round(width * 0.78), round(height * 0.075)
        left, top = (width - card_width) // 2, round(height * 0.45)
        gap = round(height * 0.018)
    return [
        (left, top + i * (card_height + gap), left + card_width,
         top + i * (card_height + gap) + card_height)
        for i in range(len(labels))
    ]


def _mix_color(base: tuple[int, int, int], color: tuple[int, int, int],
               amount: float) -> tuple[int, int, int]:
    return tuple(round(base[i] * (1 - amount) + color[i] * amount) for i in range(3))


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int],
           color: tuple[int, int, int], width: int) -> None:
    draw.line((*start, *end), fill=color, width=width)
    x, y = end
    size = max(8, width * 3)
    draw.polygon(((x, y), (x - size, y - size // 2), (x - size, y + size // 2)), fill=color)


def _draw_concept_diagram(draw: ImageDraw.ImageDraw, scene: dict, size: tuple[int, int],
                          accent: tuple[int, int, int], project_title: str = "",
                          highlighted_index: int | None = None) -> None:
    width, height = size
    labels = _diagram_labels(scene, project_title=project_title)
    if not labels:
        return

    heading_font = _font(max(20, round(height * 0.026)), bold=True)
    draw.text((round(width * 0.08), round(height * 0.34)), "CONCEPT MAP",
              font=heading_font, fill=accent)
    boxes = _diagram_layout(size, labels)
    root_color = _DIAGRAM_COLORS[0]
    root_center = ((boxes[0][0] + boxes[0][2]) // 2, (boxes[0][1] + boxes[0][3]) // 2)
    line_width = max(3, round(height * 0.004))

    if len(labels) > 1 and boxes[0][2] < boxes[1][0]:
        trunk_x = round(width * 0.48)
        child_centers = [(box[1] + box[3]) // 2 for box in boxes[1:]]
        trunk_color = root_color if highlighted_index == 0 else _DIAGRAM_MUTED
        draw.line((boxes[0][2], root_center[1], trunk_x, root_center[1]),
                  fill=trunk_color, width=line_width)
        draw.line((trunk_x, child_centers[0], trunk_x, child_centers[-1]),
                  fill=_DIAGRAM_MUTED, width=line_width)
        for index, box in enumerate(boxes[1:], 1):
            color = _DIAGRAM_COLORS[index % len(_DIAGRAM_COLORS)]
            active = highlighted_index == index
            edge = color if active else _DIAGRAM_MUTED
            _arrow(draw, (trunk_x, (box[1] + box[3]) // 2),
                   (box[0], (box[1] + box[3]) // 2), edge, line_width + (2 if active else 0))
    elif len(labels) > 1:
        centers = [((box[0] + box[2]) // 2, (box[1] + box[3]) // 2) for box in boxes]
        for index in range(1, len(boxes)):
            color = _DIAGRAM_COLORS[index % len(_DIAGRAM_COLORS)]
            edge = color if highlighted_index == index else _DIAGRAM_MUTED
            _arrow(draw, (centers[index - 1][0], boxes[index - 1][3]),
                   (centers[index][0], boxes[index][1]), edge, line_width)

    for index, (label, box) in enumerate(zip(labels, boxes)):
        active = highlighted_index == index
        color = root_color if index == 0 else _DIAGRAM_COLORS[index % len(_DIAGRAM_COLORS)]
        fill = _mix_color(_DIAGRAM_CARD, color, 0.28 if active else 0.08)
        outline = color if active else _DIAGRAM_MUTED
        text_color = (248, 251, 255) if active else _DIAGRAM_TEXT_MUTED
        border_width = max(4, round(height * (0.007 if active else 0.003)))
        if active:
            draw.rounded_rectangle(
                (box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6),
                radius=round((box[3] - box[1]) * 0.23),
                outline=_mix_color(color, (255, 255, 255), 0.3), width=max(2, border_width // 2),
            )
        draw.rounded_rectangle(box, radius=round((box[3] - box[1]) * 0.22),
                               fill=fill, outline=outline, width=border_width)
        font_size = max(20, round(height * (0.032 if index == 0 else 0.03)))
        label_font = _font(font_size, bold=True)
        inner_width = box[2] - box[0] - round((box[2] - box[0]) * 0.15)
        lines = _wrap(draw, label, label_font, inner_width)[:2]
        line_height = round(label_font.size * 1.2) if hasattr(label_font, "size") else font_size
        y = (box[1] + box[3] - line_height * len(lines)) // 2
        for line in lines:
            x = (box[0] + box[2] - draw.textlength(line, font=label_font)) / 2
            draw.text((x, y), line, font=label_font, fill=text_color)
            y += line_height


def diagram_timeline(scene: dict, cues: list[dict],
                     project_title: str = "") -> list[tuple[float, int, int | None]]:
    """Return visual states and their durations, estimating keyword timing from sentence cues."""
    labels = _diagram_labels(scene, project_title=project_title)
    events: list[tuple[float, int]] = []
    for index, label in enumerate(labels):
        pattern = re.compile(r"(?<!\w)" + re.escape(label) + r"(?!\w)", re.I)
        for cue in cues:
            text = cue.get("text", "")
            if not text:
                continue
            match = pattern.search(text)
            if match:
                fraction = (match.start() + match.end()) / (2 * len(text))
                at = float(cue["start"]) + (float(cue["end"]) - float(cue["start"])) * fraction
                events.append((at, index))
                break

    end_time = max((float(cue["end"]) for cue in cues), default=0.0)
    if not labels or not events:
        return [(end_time, len(labels), None)]

    events.sort()
    states: list[tuple[float, int, int | None]] = []
    highlighted: int | None = None
    current_time = 0.0
    for at, index in events:
        at = max(current_time, at)
        if at > current_time:
            states.append((at - current_time, len(labels), highlighted))
        highlighted = index
        current_time = at
    if end_time > current_time:
        states.append((end_time - current_time, len(labels), highlighted))
    return states


def animated_title_card(scene: dict, idx: int, total: int, project_title: str,
                        size: tuple[int, int], theme: str, cues: list[dict],
                        out_dir: Path) -> list[tuple[Path, float]]:
    """Render one title-card image per spoken concept, in reveal order."""
    W, H = round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE)
    states = diagram_timeline(scene, cues, project_title)
    frames: list[tuple[Path, float]] = []
    for frame_index, (duration, next_visible, next_highlight) in enumerate(states):
        path = out_dir / f"diagram_{frame_index:03d}.png"
        top, bottom, accent = THEMES.get(theme, THEMES["educational"])
        image = _gradient((W, H), top, bottom)
        draw = ImageDraw.Draw(image)
        pad = round(min(W, H) * 0.08)
        rtl = scene.get("language", "en").startswith("ur") and features.check("raqm")
        draw.rectangle([pad, pad, pad + round(W * 0.09), pad + round(H * 0.012)], fill=accent)
        heading_font = _font(round(min(W, H) * 0.075), bold=True)
        lines = _wrap(draw, scene["heading"], heading_font, W - 2 * pad)[:4]
        y = pad + round(H * 0.06)
        for line in lines:
            x = W - pad - draw.textlength(line, font=heading_font) if rtl else pad
            draw.text((x, y), line, font=heading_font, fill=(255, 255, 255))
            y += round(heading_font.size * 1.25) if hasattr(heading_font, "size") else 60
        small = _font(round(min(W, H) * 0.032))
        caption = f"{project_title}   |   Scene {idx} of {total}"
        draw.text((W - pad - draw.textlength(caption, font=small), pad), caption,
                  font=small, fill=(220, 228, 236))
        _draw_concept_diagram(draw, scene, (W, H), accent, project_title, next_highlight)
        image.save(path)
        frames.append((path, duration))
    if not frames:
        path = out_dir / "diagram_000.png"
        title_card(scene, idx, total, project_title, size, theme, path)
        return [(path, max((float(cue["end"]) for cue in cues), default=1.0))]
    return frames


def title_card(scene: dict, idx: int, total: int, project_title: str, size: tuple[int, int],
               theme: str, out: Path) -> None:
    W, H = round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE)
    top, bot, accent = THEMES.get(theme, THEMES["educational"])
    img = _gradient((W, H), top, bot)
    d = ImageDraw.Draw(img)
    pad = round(min(W, H) * 0.08)
    rtl = scene.get("language", "en").startswith("ur") and features.check("raqm")
    d.rectangle([pad, pad, pad + round(W * 0.09), pad + round(H * 0.012)], fill=accent)
    head_font = _font(round(min(W, H) * 0.075), bold=True)
    lines = _wrap(d, scene["heading"], head_font, W - 2 * pad)[:4]
    y = pad + round(H * 0.06)
    for ln in lines:
        x = W - pad - d.textlength(ln, font=head_font) if rtl else pad
        d.text((x, y), ln, font=head_font, fill=(255, 255, 255))
        y += round(head_font.size * 1.25) if hasattr(head_font, "size") else 60
    small = _font(round(min(W, H) * 0.032))
    cap = f"{project_title}   |   Scene {idx} of {total}"
    d.text((W - pad - d.textlength(cap, font=small), pad), cap, font=small, fill=(220, 228, 236))
    for ref in scene.get("source_refs", [])[:1]:
        if ref.get("type") == "pdf":
            line = f"Source: PDF page {ref.get('page')}"
            d.text((W - pad - d.textlength(line, font=small), pad + round(H * 0.05)), line, font=small, fill=accent)
    _draw_concept_diagram(d, scene, (W, H), accent, project_title)
    img.save(out)


def pdf_page_card(scene: dict, pdf_path: Path, size: tuple[int, int], theme: str, out: Path) -> None:
    W, H = round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE)
    top, bot, accent = THEMES.get(theme, THEMES["educational"])
    img = _gradient((W, H), top, bot)
    doc = pymupdf.open(str(pdf_path))
    pno = int(scene["visual"].get("page", 1))
    page = doc[max(0, min(pno - 1, len(doc) - 1))]
    zoom = min(W * 0.94 / page.rect.width, H * 0.9 / page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    pg = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    over = Image.new("RGBA", pg.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(over)
    for r in find_highlights(page, split_sentences(scene["narration"])):
        od.rectangle([r.x0 * zoom, r.y0 * zoom, r.x1 * zoom, r.y1 * zoom], fill=(255, 214, 10, 105))
    pg = Image.alpha_composite(pg, over).convert("RGB")
    img.paste(pg, ((W - pg.width) // 2, (H - pg.height) // 2))
    ImageDraw.Draw(img).text((round(W * 0.03), round(H * 0.015)), f"Page {pno}", font=_font(round(H * 0.03)), fill=accent)
    img.save(out)
