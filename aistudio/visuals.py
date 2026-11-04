"""Scene background images (Pillow). Rendered at 1.5x output size so slow zoom stays sharp."""
from __future__ import annotations

from collections import Counter
import math
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


def water_cycle_phase(heading: str) -> str:
    heading = heading.casefold()
    for phase, words in (
        ("evaporation", ("evaporation", "transpiration")),
        ("condensation", ("condensation", "cloud")),
        ("precipitation", ("precipitation", "rain", "snow", "hail")),
        ("collection", ("collection", "runoff", "groundwater")),
    ):
        if any(word in heading for word in words):
            return phase
    if "summary" in heading or "cycle" in heading:
        return "all"
    return "all"


def _draw_drop(draw: ImageDraw.ImageDraw, x: int, y: int, radius: int,
               color: tuple[int, int, int]) -> None:
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    draw.polygon(((x - radius, y), (x, y - round(radius * 1.9)),
                  (x + radius, y)), fill=color)


def _draw_water_cycle_frame(scene: dict, project_title: str, size: tuple[int, int],
                            theme: str, phase: str, progress: float,
                            out: Path) -> None:
    width, height = size
    top, bottom, accent = THEMES.get(theme, THEMES["educational"])
    image = _gradient(size, top, bottom)
    draw = ImageDraw.Draw(image)
    scale = min(width / 1280, height / 720)

    def point(x: float, y: float) -> tuple[int, int]:
        return round(x * width), round(y * height)

    def active(name: str) -> bool:
        return phase == "all" or phase == name

    colors = {
        "evaporation": (255, 190, 78),
        "condensation": (111, 216, 255),
        "precipitation": (89, 169, 255),
        "collection": (74, 226, 190),
    }
    muted = (68, 96, 116)
    labels = (
        ("EVAPORATION", "evaporation"), ("CONDENSATION", "condensation"),
        ("PRECIPITATION", "precipitation"), ("COLLECTION", "collection"),
    )
    heading_font = _font(max(18, round(min(width, height) * 0.052)), bold=True)
    small_font = _font(max(13, round(min(width, height) * 0.021)), bold=True)
    pad = round(min(width, height) * 0.055)
    draw.text((pad, pad), scene.get("heading", "Water Cycle"),
              font=heading_font, fill=(250, 253, 255))
    caption = project_title[:42]
    draw.text((width - pad - draw.textlength(caption, font=small_font), pad),
              caption, font=small_font, fill=(210, 225, 237))

    if width / height >= 1.2:
        chip_y, chip_w = 0.40, 0.205
        chip_xs = (0.025, 0.265, 0.505, 0.745)
        chip_h = 0.055
    else:
        chip_y, chip_w = 0.36, 0.44
        chip_xs = (0.035, 0.525, 0.035, 0.525)
        chip_h = 0.045
    for index, ((label, name), x) in enumerate(zip(labels, chip_xs)):
        row_offset = 0 if width / height >= 1.2 else (index // 2) * 0.057
        x1, y1 = point(x, chip_y + row_offset)
        x2, y2 = point(x + chip_w, chip_y + chip_h + row_offset)
        color = colors[name] if active(name) else muted
        draw.rounded_rectangle((x1, y1, x2, y2), radius=round(14 * scale),
                               fill=(13, 36, 53), outline=color, width=max(2, round(2 * scale)))
        text_w = draw.textlength(label, font=small_font)
        draw.text((x1 + (x2 - x1 - text_w) / 2, y1 + (y2 - y1 - small_font.size) / 2),
                  label, font=small_font, fill=color)

    sun_x, sun_y = point(0.15, 0.19)
    sun_radius = round(min(width, height) * 0.057)
    pulse = 1 + (0.06 * (0.5 + 0.5 * math.sin(progress * math.tau)))
    sun_radius = round(sun_radius * pulse)
    ray_color = colors["evaporation"] if active("evaporation") else muted
    for ray in range(12):
        angle = ray * math.tau / 12
        inner = sun_radius + round(7 * scale)
        outer = sun_radius + round((17 + 3 * pulse) * scale)
        draw.line((sun_x + round(math.cos(angle) * inner),
                   sun_y + round(math.sin(angle) * inner),
                   sun_x + round(math.cos(angle) * outer),
                   sun_y + round(math.sin(angle) * outer)),
                  fill=ray_color, width=max(2, round(3 * scale)))
    draw.ellipse((sun_x - sun_radius, sun_y - sun_radius,
                  sun_x + sun_radius, sun_y + sun_radius), fill=(255, 205, 91))

    cloud_center = point(0.70, 0.22)
    cloud_radius = round(min(width, height) * 0.067)
    cloud_color = colors["condensation"] if active("condensation") else (151, 177, 194)
    for dx, dy, factor in ((-1.0, 0.10, 0.76), (-0.48, -0.22, 0.98),
                           (0.18, -0.28, 1.12), (0.78, -0.03, 0.83)):
        cx = cloud_center[0] + round(dx * cloud_radius)
        cy = cloud_center[1] + round(dy * cloud_radius)
        radius = round(cloud_radius * factor)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                     fill=cloud_color)
    cloud_base_y = cloud_center[1] + round(cloud_radius * 0.46)
    draw.rounded_rectangle((cloud_center[0] - round(cloud_radius * 1.25),
                            cloud_base_y - round(cloud_radius * 0.25),
                            cloud_center[0] + round(cloud_radius * 1.18),
                            cloud_base_y + round(cloud_radius * 0.47)),
                           radius=round(cloud_radius * 0.35), fill=cloud_color)

    sea_y = round(height * 0.76)
    land = [point(0, 0.76), point(0.12, 0.70), point(0.25, 0.72),
            point(0.39, 0.61), point(0.53, 0.69), point(0.68, 0.59),
            point(0.83, 0.68), point(1, 0.64), (width, height), (0, height)]
    draw.polygon(land, fill=(67, 133, 91))
    water_top = colors["collection"] if active("collection") else (34, 139, 190)
    draw.rectangle((0, sea_y, width, height), fill=(18, 102, 153))
    draw.line((0, sea_y, width, sea_y), fill=water_top, width=max(3, round(4 * scale)))
    for wave in range(3):
        y = sea_y + round((wave + 1) * height * 0.055)
        points = [point(x / 20, y / height + 0.008 * math.sin(
            (x / 20 + progress * 2) * math.tau)) for x in range(21)]
        draw.line(points, fill=(87, 190, 216), width=max(2, round(2 * scale)))

    river_color = colors["collection"] if active("collection") else (72, 152, 177)
    river = [point(0.70, 0.64), point(0.66, 0.69), point(0.72, 0.73), point(0.63, 0.77)]
    draw.line(river, fill=river_color, width=max(8, round(min(width, height) * 0.022)), joint="curve")
    draw.line(river, fill=(128, 218, 228), width=max(2, round(min(width, height) * 0.006)), joint="curve")

    plant_x, plant_y = point(0.36, 0.69)
    plant_color = (77, 208, 126) if active("evaporation") else (78, 151, 103)
    draw.line((plant_x, plant_y, plant_x, plant_y - round(height * 0.10)),
              fill=(93, 120, 76), width=max(4, round(6 * scale)))
    for direction, level in ((-1, 0.04), (1, 0.08), (-1, 0.12), (1, 0.16)):
        lx, ly = plant_x + round(direction * height * 0.035), plant_y - round(height * level)
        draw.ellipse((lx - round(height * 0.023), ly - round(height * 0.012),
                      lx + round(height * 0.023), ly + round(height * 0.012)),
                     fill=plant_color)

    radius = max(4, round(min(width, height) * 0.012))
    if active("evaporation"):
        for i in range(6):
            t = (progress + i / 6) % 1
            x = round(width * (0.18 + 0.18 * (i % 3) / 3 + 0.012 * math.sin(t * math.tau)))
            y = round(height * (0.75 - 0.29 * t))
            _draw_drop(draw, x, y, radius, colors["evaporation"])
    if active("condensation"):
        for i in range(7):
            angle = progress * math.tau + i * math.tau / 7
            x = cloud_center[0] + round(math.cos(angle) * cloud_radius * 0.9)
            y = cloud_center[1] + round(math.sin(angle) * cloud_radius * 0.45)
            draw.ellipse((x - radius // 2, y - radius // 2,
                          x + radius // 2, y + radius // 2), fill=(31, 119, 164))
    if active("precipitation"):
        for i in range(8):
            t = (progress + i / 8) % 1
            x = round(width * (0.62 + 0.16 * (i % 4) / 4))
            y = round(height * (0.34 + 0.31 * t))
            _draw_drop(draw, x, y, radius, colors["precipitation"])
    if active("collection"):
        for i in range(7):
            t = (progress + i / 7) % 1
            x = round(width * (0.70 - 0.07 * t))
            y = round(height * (0.65 + 0.12 * t))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                         fill=colors["collection"])

    image.save(out)


def animated_water_cycle(scene: dict, project_title: str, size: tuple[int, int],
                         theme: str, out_dir: Path, fps: int = 8,
                         loop_seconds: int = 4) -> list[tuple[Path, float]]:
    """Create a short looping, phase-focused water-cycle animation from drawn frames."""
    phase = water_cycle_phase(scene.get("heading", ""))
    count = fps * loop_seconds
    frame_duration = 1 / fps
    frames = []
    render_size = (round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE))
    for index in range(count):
        path = out_dir / f"water_cycle_{index:03d}.png"
        _draw_water_cycle_frame(scene, project_title, render_size, theme, phase,
                                index / count, path)
        frames.append((path, frame_duration))
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
