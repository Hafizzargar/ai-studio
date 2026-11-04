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
from .animation import validate_instructions
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
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = max(8, width * 3)
    wing = math.pi / 6
    points = [
        (end[0] - round(size * math.cos(angle - wing)),
         end[1] - round(size * math.sin(angle - wing))),
        (end[0] - round(size * math.cos(angle + wing)),
         end[1] - round(size * math.sin(angle + wing))),
    ]
    draw.polygon((end, *points), fill=color)


_INSTRUCTION_LABELS = {
    "sun": "Sun", "ocean": "Ocean", "water": "Water", "vapor": "Water vapour",
    "cloud": "Cloud", "droplets": "Cloud droplets", "rain": "Rain", "snow": "Snow",
    "river": "River", "ground": "Land", "groundwater": "Groundwater", "plant": "Plants",
    "battery": "Battery", "wire": "Wire", "bulb": "Bulb", "open_switch": "Open switch",
    "conventional_current": "Conventional current", "electrons": "Electron drift",
    "three_estates": "Three estates", "financial_crisis": "Financial crisis",
    "estates_general": "Estates-General", "national_assembly": "National Assembly",
    "bastille": "Bastille", "republic": "Republic", "king_execution": "Louis XVI executed",
    "reign_of_terror": "Reign of Terror", "directory": "Directory",
    "napoleon_coup": "Napoleon's coup", "citizenship_rights": "Citizenship and rights",
}
_HISTORY_DATES = {
    "estates_general": "5 May 1789", "national_assembly": "17 Jun 1789",
    "bastille": "14 Jul 1789", "republic": "1792",
    "king_execution": "1793", "reign_of_terror": "1793–94",
    "directory": "1795", "napoleon_coup": "1799",
}


def _instruction_positions(scene_type: str, objects: list[str]) -> dict[str, tuple[float, float]]:
    if scene_type == "science_process":
        known = {
            "sun": (0.13, 0.33), "ocean": (0.22, 0.75), "water": (0.22, 0.75),
            "vapor": (0.39, 0.54), "plant": (0.39, 0.76), "cloud": (0.65, 0.34),
            "droplets": (0.65, 0.47), "rain": (0.79, 0.56), "snow": (0.79, 0.56),
            "ground": (0.81, 0.77), "river": (0.56, 0.78), "groundwater": (0.68, 0.83),
        }
        fallback_y = 0.63
    elif scene_type == "electric_circuit":
        known = {
            "battery": (0.18, 0.52), "wire": (0.50, 0.27), "bulb": (0.82, 0.52),
            "open_switch": (0.50, 0.76), "conventional_current": (0.50, 0.40),
            "electrons": (0.50, 0.64),
        }
        fallback_y = 0.51
    else:
        known = {}
        fallback_y = 0.58

    positions = {obj: known[obj] for obj in objects if obj in known}
    unknown = [obj for obj in objects if obj not in positions]
    if scene_type == "history_timeline":
        for index, obj in enumerate(objects):
            positions[obj] = (0.12 + 0.76 * index / max(1, len(objects) - 1), fallback_y)
    else:
        for index, obj in enumerate(unknown):
            positions[obj] = (0.12 + 0.76 * index / max(1, len(unknown) - 1), fallback_y)
    return positions


def _instruction_state(instructions: dict, scene_time: float) -> dict[str, dict[str, dict]]:
    states: dict[str, dict[str, dict]] = {}
    for action in instructions["animations"]:
        start, duration = float(action.get("start", 0)), float(action["duration"])
        if not start <= scene_time <= start + duration:
            continue
        object_states = states.setdefault(action["object"], {})
        name = action["action"]
        current = object_states.get(name)
        if current is not None and current["start"] > start:
            continue
        object_states[name] = {
            "start": start,
            "progress": min(1.0, max(0.0, (scene_time - start) / duration)),
        }
    return states


def _draw_instruction_frame(scene: dict, instructions: dict, project_title: str,
                            size: tuple[int, int], theme: str, progress: float,
                            out: Path) -> None:
    width, height = size
    scene_type = instructions["scene_type"]
    objects = instructions["objects"]
    positions = _instruction_positions(scene_type, objects)
    scene_time = progress * float(instructions["duration"])
    active = _instruction_state(instructions, scene_time)
    reveal_starts = {}
    for action in instructions["animations"]:
        if action["action"] == "reveal":
            obj = action["object"]
            reveal_starts[obj] = min(reveal_starts.get(obj, float("inf")),
                                     float(action.get("start", 0)))
    top, bottom, accent = THEMES.get(theme, THEMES["educational"])
    image = _gradient(size, top, bottom)
    draw = ImageDraw.Draw(image)
    scale = min(width / 1280, height / 720)

    def point(pos: tuple[float, float]) -> tuple[int, int]:
        return round(pos[0] * width), round(pos[1] * height)

    heading_font = _font(max(18, round(min(width, height) * 0.05)), bold=True)
    label_font = _font(max(12, round(min(width, height) * 0.019)), bold=True)
    small_font = _font(max(10, round(min(width, height) * 0.014)))
    pad = round(min(width, height) * 0.055)
    draw.text((pad, pad), scene.get("heading", ""), font=heading_font, fill=(250, 253, 255))
    caption = project_title[:42]
    draw.text((width - pad - draw.textlength(caption, font=small_font), pad),
              caption, font=small_font, fill=(210, 225, 237))

    if scene_type == "science_process":
        caption = "Solar energy drives evaporation; water returns through precipitation."
        draw.text((pad, round(height * 0.20)), caption, font=small_font, fill=(199, 222, 235))
        route = [obj for obj in ("ocean", "water", "vapor", "cloud", "rain", "river")
                 if obj in positions]
        for left, right in zip(route, route[1:]):
            _arrow(draw, point(positions[left]), point(positions[right]),
                   _DIAGRAM_MUTED, max(2, round(3 * scale)))
    elif scene_type == "electric_circuit":
        caption = ("An open switch breaks the path; closing it completes the circuit."
                   if "open_switch" in objects
                   else "Closed path required for current; directions are explicitly distinguished.")
        draw.text((pad, round(height * 0.20)), caption, font=small_font, fill=(199, 222, 235))
        bx, by = point(positions.get("battery", (0.18, 0.52)))
        lx, ly = point(positions.get("bulb", (0.82, 0.52)))
        wire_x = round(width * 0.50)
        wire_top, wire_bottom = round(height * 0.27), round(height * 0.76)
        wire_color = (116, 190, 207)
        thickness = max(3, round(4 * scale))
        battery_radius = round(min(width, height) * 0.043)
        battery_top, battery_bottom = by - battery_radius, by + battery_radius
        if "open_switch" in objects:
            draw.line((bx, battery_top, bx, wire_top, wire_x - 20, wire_top), fill=wire_color, width=thickness)
            draw.line((wire_x + 20, wire_top, lx, wire_top, lx, ly), fill=wire_color, width=thickness)
            draw.line((lx, ly, lx, wire_bottom, bx, wire_bottom, bx, battery_bottom),
                      fill=wire_color, width=thickness)
            draw.line((wire_x - 18, wire_top, wire_x + 14, wire_top - 19),
                      fill=(255, 190, 78), width=thickness)
        else:
            draw.line((bx, battery_top, bx, wire_top, lx, wire_top, lx, ly),
                      fill=wire_color, width=thickness, joint="curve")
            draw.line((lx, ly, lx, wire_bottom, bx, wire_bottom, bx, battery_bottom),
                      fill=wire_color, width=thickness, joint="curve")
            current_color = (255, 190, 78)
            electron_color = (102, 210, 255)
            if "conventional_current" in objects:
                _arrow(draw, (round(width * 0.28), wire_top), (round(width * 0.43), wire_top),
                       current_color, thickness)
                _arrow(draw, (round(width * 0.72), wire_bottom), (round(width * 0.56), wire_bottom),
                       current_color, thickness)
            if "electrons" in objects:
                _arrow(draw, (round(width * 0.43), wire_top), (round(width * 0.28), wire_top),
                       electron_color, thickness)
                _arrow(draw, (round(width * 0.56), wire_bottom), (round(width * 0.72), wire_bottom),
                       electron_color, thickness)
    else:
        left, right = round(width * 0.11), round(width * 0.89)
        y = round(height * 0.58)
        draw.line((left, y, right, y), fill=_DIAGRAM_MUTED, width=max(3, round(4 * scale)))
        for index in range(len(objects) - 1):
            x1 = round(width * (0.12 + 0.76 * index / max(1, len(objects) - 1)))
            x2 = round(width * (0.12 + 0.76 * (index + 1) / max(1, len(objects) - 1)))
            _arrow(draw, (x1 + 8, y), (x2 - 8, y), _DIAGRAM_MUTED, max(2, round(3 * scale)))
        draw.text((pad, round(height * 0.20)),
                  "French Revolution • selected events (sequence, not to scale) • 1789–1799",
                  font=small_font, fill=(199, 222, 235))

    for index, obj in enumerate(objects):
        if obj in reveal_starts and scene_time < reveal_starts[obj]:
            continue
        x, y = positions[obj]
        states = active.get(obj, {})
        motion = max(
            ((name, state) for name, state in states.items()
             if name in {"flow", "move_down", "move_left", "move_right", "move_up"}),
            key=lambda item: item[1]["start"],
            default=None,
        )
        action, motion_state = motion if motion else ("", {})
        amount = motion_state.get("progress", 0.0)
        if action in {"move_up", "move_down"}:
            y += (-1 if action == "move_up" else 1) * 0.055 * math.sin(amount * math.pi)
        elif action in {"move_left", "move_right", "flow"}:
            direction = -1 if action == "move_left" else 1
            x += direction * 0.035 * math.sin(amount * math.pi)
        x_px, y_px = point((x, y))
        radius = max(12, round(min(width, height) * (0.043 if scene_type != "history_timeline" else 0.033)))
        pulse = 1 + 0.14 * math.sin(states["pulse"]["progress"] * math.tau) if "pulse" in states else 1
        reveal = states.get("reveal")
        radius = (max(4, round(radius * (0.2 + 0.8 * reveal["progress"]))) if reveal
                  else round(radius * pulse))
        color = _DIAGRAM_COLORS[index % len(_DIAGRAM_COLORS)]
        if "highlight" in states:
            color = (255, 210, 99)

        if scene_type == "electric_circuit" and obj == "battery":
            draw.rounded_rectangle((x_px - radius, y_px - radius, x_px + radius, y_px + radius),
                                   radius=max(4, radius // 4), fill=(20, 54, 72),
                                   outline=color, width=max(3, round(4 * scale)))
            plus = _font(max(12, round(min(width, height) * 0.035)), bold=True)
            draw.text((x_px - plus.size / 2, y_px - radius + 2), "+", font=plus,
                      fill=(255, 190, 78))
            draw.text((x_px - plus.size / 2, y_px + radius - plus.size - 2), "−", font=plus,
                      fill=(102, 210, 255))
        elif scene_type == "electric_circuit" and obj == "bulb":
            draw.ellipse((x_px - radius, y_px - radius, x_px + radius, y_px + radius),
                         fill=(41, 58, 67), outline=color, width=max(3, round(4 * scale)))
            draw.line((x_px - radius // 3, y_px + radius // 3,
                       x_px + radius // 3, y_px - radius // 3), fill=color, width=max(2, radius // 9))
        elif scene_type == "history_timeline":
            draw.ellipse((x_px - radius, y_px - radius, x_px + radius, y_px + radius),
                         fill=_mix_color(_DIAGRAM_CARD, color, 0.38 if states else 0.12),
                         outline=color, width=max(3, round(4 * scale)))
        else:
            draw.ellipse((x_px - radius, y_px - radius, x_px + radius, y_px + radius),
                         fill=_mix_color(_DIAGRAM_CARD, color, 0.42 if states else 0.2),
                         outline=color, width=max(3, round(4 * scale)))

        if "flow" in states or reveal:
            draw.ellipse((x_px - radius - 7, y_px - radius - 7, x_px + radius + 7, y_px + radius + 7),
                         outline=color, width=max(2, round(3 * scale)))
        label = _INSTRUCTION_LABELS.get(obj, obj.replace("_", " ").title())
        text_width = draw.textlength(label, font=label_font)
        draw.text((x_px - text_width / 2, y_px + radius + round(height * 0.012)),
                  label, font=label_font, fill=(248, 251, 255))
        date = _HISTORY_DATES.get(obj)
        if scene_type == "history_timeline" and date:
            date_width = draw.textlength(date, font=small_font)
            draw.text((x_px - date_width / 2, y_px - radius - small_font.size - 6),
                      date, font=small_font, fill=accent)

    if scene_type == "electric_circuit":
        draw.text((pad, round(height * 0.90)), "Amber: conventional current (+ to −)",
                  font=small_font, fill=(255, 190, 78))
        if "electrons" in objects:
            electron_text = "Blue: electron drift (− to +)"
            draw.text((width - pad - draw.textlength(electron_text, font=small_font),
                       round(height * 0.90)), electron_text, font=small_font, fill=(102, 210, 255))
    image.save(out)


def animated_instruction_scene(scene: dict, project_title: str, size: tuple[int, int],
                               theme: str, out_dir: Path, fps: int = 8,
                               loop_seconds: int = 4,
                               scene_duration: float | None = None) -> list[tuple[Path, float]]:
    """Render the instruction timeline across the narration duration."""
    instructions = validate_instructions(scene.get("visual", {}).get("instructions"))
    out_dir.mkdir(parents=True, exist_ok=True)
    render_duration = loop_seconds if scene_duration is None else scene_duration
    if not math.isfinite(render_duration) or render_duration <= 0:
        raise ValueError("Scene duration must be a positive finite number")
    count = max(1, math.ceil(fps * render_duration))
    frame_duration = render_duration / count
    render_size = (round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE))
    frames = []
    for index in range(count):
        path = out_dir / f"instruction_{index:03d}.png"
        _draw_instruction_frame(scene, instructions, project_title, render_size, theme,
                                index / count, path)
        frames.append((path, frame_duration))
    return frames


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
