"""Original procedural guide-character animation frames for demo scenes."""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from .visuals import SUPERSAMPLE, _font, _gradient, _wrap


_INK = (17, 39, 57)
_MINT = (89, 222, 190)
_MINT_LIGHT = (156, 245, 214)
_ORANGE = (255, 164, 83)
_CREAM = (255, 248, 224)
_BLUE = (91, 187, 232)
_DIALOGUE_LINE = re.compile(
    r"^(Pip|Maya|Ravi)\s+\[([a-z_]+),\s*([a-z_]+)\]:\s*(.+)$"
)
_DIALOGUE_GESTURES = {"wave", "point", "think", "celebrate", "idle"}
_DIALOGUE_EXPRESSIONS = {"happy", "curious", "surprised"}
_DIALOGUE_CHARACTERS = {
    "Pip": {"body": (89, 222, 190), "accent": (255, 164, 83), "hair": "tuft"},
    "Maya": {"body": (203, 150, 247), "accent": (255, 202, 92), "hair": "curls"},
    "Ravi": {"body": (102, 188, 239), "accent": (255, 137, 116), "hair": "cap"},
}


def _bezier(p0, p1, p2, p3, count: int = 18) -> list[tuple[float, float]]:
    points = []
    for index in range(count + 1):
        t = index / count
        inverse = 1 - t
        points.append((
            inverse ** 3 * p0[0] + 3 * inverse ** 2 * t * p1[0]
            + 3 * inverse * t ** 2 * p2[0] + t ** 3 * p3[0],
            inverse ** 3 * p0[1] + 3 * inverse ** 2 * t * p1[1]
            + 3 * inverse * t ** 2 * p2[1] + t ** 3 * p3[1],
        ))
    return points


def _draw_character(draw: ImageDraw.ImageDraw, center: tuple[float, float], height: float,
                    time: float, gesture: str, expression: str,
                    speaking: bool = False, body_color: tuple[int, int, int] = _MINT,
                    accessory_color: tuple[int, int, int] = _ORANGE,
                    hair_style: str = "none") -> None:
    cx, base_y = center
    bob = math.sin(time * math.tau * 0.8) * height * 0.014
    cy = base_y + bob
    h = height
    stroke = max(3, round(h * 0.018))
    limb = max(7, round(h * 0.035))
    hand_r = max(9, round(h * 0.052))

    def pt(x: float, y: float) -> tuple[int, int]:
        return round(cx + x * h), round(cy + y * h)

    left_shoulder, right_shoulder = pt(-0.25, 0.04), pt(0.25, 0.04)
    if gesture == "wave":
        wave = math.sin(time * math.tau * 2.2)
        elbow, hand = pt(-0.43, -0.02), pt(-0.44 + wave * 0.07, -0.38)
        draw.line((left_shoulder, elbow, hand), fill=_INK, width=limb, joint="curve")
        draw.ellipse((hand[0] - hand_r, hand[1] - hand_r, hand[0] + hand_r,
                      hand[1] + hand_r), fill=accessory_color, outline=_INK, width=stroke)
        draw.line((right_shoulder, pt(0.35, 0.22), pt(0.37, 0.38)),
                  fill=_INK, width=limb, joint="curve")
        hand = pt(0.37, 0.39)
        draw.ellipse((hand[0] - hand_r, hand[1] - hand_r, hand[0] + hand_r,
                      hand[1] + hand_r), fill=body_color, outline=_INK, width=stroke)
    elif gesture == "point":
        hand = pt(0.61, -0.05)
        elbow = pt(0.35, 0.08)
        draw.line((left_shoulder, pt(-0.38, 0.24), pt(-0.37, 0.38)),
                  fill=_INK, width=limb, joint="curve")
        glove = pt(-0.37, 0.39)
        draw.ellipse((glove[0] - hand_r, glove[1] - hand_r, glove[0] + hand_r,
                      glove[1] + hand_r), fill=body_color, outline=_INK, width=stroke)
        draw.line((right_shoulder, elbow, hand), fill=_INK, width=limb, joint="curve")
        draw.ellipse((hand[0] - hand_r, hand[1] - hand_r, hand[0] + hand_r,
                      hand[1] + hand_r), fill=accessory_color, outline=_INK, width=stroke)
        finger_end = pt(0.78, -0.07)
        draw.line((hand, finger_end), fill=_INK, width=max(4, stroke // 2))
    elif gesture == "think":
        elbow, hand = pt(0.37, 0.12), pt(0.25, -0.05)
        draw.line((left_shoulder, pt(-0.37, 0.24), pt(-0.36, 0.38)),
                  fill=_INK, width=limb, joint="curve")
        glove = pt(-0.36, 0.39)
        draw.ellipse((glove[0] - hand_r, glove[1] - hand_r, glove[0] + hand_r,
                      glove[1] + hand_r), fill=body_color, outline=_INK, width=stroke)
        draw.line((right_shoulder, elbow, hand), fill=_INK, width=limb, joint="curve")
        draw.ellipse((hand[0] - hand_r, hand[1] - hand_r, hand[0] + hand_r,
                      hand[1] + hand_r), fill=accessory_color, outline=_INK, width=stroke)
    else:
        arm_y = -0.28 if gesture == "celebrate" else 0.24
        for side in (-1, 1):
            shoulder = left_shoulder if side < 0 else right_shoulder
            elbow = pt(side * 0.38, arm_y * 0.65)
            hand = pt(side * 0.47, arm_y - 0.13)
            draw.line((shoulder, elbow, hand), fill=_INK, width=limb, joint="curve")
            draw.ellipse((hand[0] - hand_r, hand[1] - hand_r, hand[0] + hand_r,
                          hand[1] + hand_r),
                         fill=accessory_color if gesture == "celebrate" else body_color,
                         outline=_INK, width=stroke)

    foot_y = cy + h * 0.40
    for side in (-1, 1):
        fx = cx + side * h * 0.15
        draw.line((pt(side * 0.13, 0.36), (round(fx), round(foot_y))),
                  fill=_INK, width=max(6, round(h * 0.045)))
        shoe_y = round(foot_y + h * 0.015)
        shoe_w, shoe_h = round(h * 0.14), round(h * 0.07)
        draw.rounded_rectangle((round(fx - shoe_w / 2), shoe_y - shoe_h / 2,
                                round(fx + shoe_w / 2), shoe_y + shoe_h / 2),
                               radius=shoe_h // 2, fill=accessory_color, outline=_INK, width=stroke)

    top = pt(0, -0.54)
    right_top = pt(0.36, -0.45)
    right_mid = pt(0.43, -0.12)
    right_low = pt(0.34, 0.27)
    bottom_right = pt(0.18, 0.43)
    bottom = pt(0, 0.46)
    bottom_left = pt(-0.18, 0.43)
    left_low = pt(-0.34, 0.27)
    left_mid = pt(-0.43, -0.12)
    left_top = pt(-0.36, -0.45)
    body = (
        _bezier(top, pt(0.18, -0.56), pt(0.35, -0.53), right_top)
        + _bezier(right_top, pt(0.47, -0.31), pt(0.47, 0.08), right_mid)[1:]
        + _bezier(right_mid, pt(0.42, 0.23), pt(0.41, 0.40), right_low)[1:]
        + _bezier(right_low, pt(0.30, 0.40), pt(0.23, 0.46), bottom_right)[1:]
        + _bezier(bottom_right, pt(0.12, 0.46), pt(0.06, 0.46), bottom)[1:]
        + _bezier(bottom, pt(-0.06, 0.46), pt(-0.12, 0.46), bottom_left)[1:]
        + _bezier(bottom_left, pt(-0.23, 0.46), pt(-0.30, 0.40), left_low)[1:]
        + _bezier(left_low, pt(-0.41, 0.08), pt(-0.42, -0.31), left_mid)[1:]
        + _bezier(left_mid, pt(-0.47, -0.49), pt(-0.18, -0.56), left_top)[1:]
        + _bezier(left_top, pt(-0.35, -0.53), pt(-0.18, -0.56), top)[1:]
    )
    draw.polygon(body, fill=body_color, outline=_INK)
    draw.line(body, fill=_INK, width=stroke, joint="curve")

    scarf_y = pt(0, 0.19)[1]
    draw.rounded_rectangle((round(cx - h * 0.27), scarf_y - round(h * 0.045),
                            round(cx + h * 0.27), scarf_y + round(h * 0.045)),
                           radius=round(h * 0.035), fill=accessory_color,
                           outline=_INK, width=stroke // 2)
    scarf_tail = [pt(0.10, 0.21), pt(0.27, 0.39), pt(0.03, 0.30)]
    draw.polygon(scarf_tail, fill=accessory_color, outline=_INK)

    head_y = cy - h * 0.49
    hair_color = (80, 57, 78) if hair_style == "curls" else (42, 63, 82)
    if hair_style == "curls":
        for offset, radius in ((-0.27, 0.12), (-0.12, 0.16), (0.06, 0.16), (0.25, 0.12)):
            hx, hy, hr = round(cx + h * offset), round(head_y + h * 0.035), round(h * radius)
            draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr),
                         fill=hair_color, outline=_INK, width=stroke // 2)
    elif hair_style == "cap":
        cap_top = round(head_y - h * 0.025)
        draw.pieslice((round(cx - h * 0.34), cap_top - round(h * 0.19),
                       round(cx + h * 0.34), cap_top + round(h * 0.19)),
                      180, 360, fill=hair_color, outline=_INK, width=stroke)
        draw.rounded_rectangle((round(cx - h * 0.39), cap_top - round(h * 0.015),
                                round(cx + h * 0.39), cap_top + round(h * 0.055)),
                               radius=max(2, round(h * 0.025)), fill=accessory_color,
                               outline=_INK, width=stroke // 2)
    elif hair_style == "tuft":
        draw.polygon([pt(-0.30, -0.47), pt(-0.19, -0.67), pt(-0.06, -0.53),
                      pt(0.08, -0.68), pt(0.32, -0.44)],
                     fill=hair_color, outline=_INK)

    eye_y = cy - h * 0.13
    eye_gap = h * 0.13
    blink = (time % 3.4) < 0.13
    eye_h = h * 0.085 * (0.12 if blink else 1)
    eye_w = h * 0.055
    for side in (-1, 1):
        ex = cx + side * eye_gap
        draw.ellipse((round(ex - eye_w), round(eye_y - eye_h),
                      round(ex + eye_w), round(eye_y + eye_h)), fill=_INK)
        if not blink:
            draw.ellipse((round(ex - eye_w * 0.35), round(eye_y - eye_h * 0.55),
                          round(ex + eye_w * 0.08), round(eye_y - eye_h * 0.08)), fill=_CREAM)
    cheek_y = round(eye_y + h * 0.11)
    for side in (-1, 1):
        ex = round(cx + side * h * 0.25)
        draw.ellipse((ex - round(h * 0.035), cheek_y - round(h * 0.018),
                      ex + round(h * 0.035), cheek_y + round(h * 0.018)),
                     fill=(255, 154, 147))

    mouth_y = eye_y + h * 0.14
    if expression == "surprised":
        mouth_w = max(5, round(h * (0.026 + (0.026 if speaking else 0))))
        mouth_h = max(7, round(h * (0.055 + (0.045 if speaking else 0))))
        draw.ellipse((round(cx - mouth_w), round(mouth_y - mouth_h / 2),
                      round(cx + mouth_w), round(mouth_y + mouth_h / 2)),
                     fill=_INK)
    elif expression == "curious":
        draw.arc((round(cx - h * 0.10), round(mouth_y - h * 0.025),
                  round(cx + h * 0.10), round(mouth_y + h * 0.10)),
                 15, 155, fill=_INK, width=stroke)
    else:
        mouth_h = h * (0.12 if speaking else 0.07)
        draw.arc((round(cx - h * 0.12), round(mouth_y - mouth_h * 0.42),
                  round(cx + h * 0.12), round(mouth_y + mouth_h)),
                 15, 165, fill=_INK, width=stroke)


def _draw_demo_frame(time: float, size: tuple[int, int], cues: list[dict], out: Path,
                     project_title: str = "Pip's Learning Club",
                     duration: float | None = None) -> None:
    width, height = size
    duration = (max((float(cue["end"]) for cue in cues), default=12)
                if duration is None else duration)
    cue_index = max(
        (index for index, cue in enumerate(cues) if float(cue["start"]) <= time),
        default=0,
    )
    cue = cues[cue_index] if cues else {"start": 0.0, "end": duration}
    cue_start, cue_end = float(cue["start"]), float(cue["end"])
    gesture = ("wave", "point", "think", "celebrate")[min(cue_index, 3)]
    expression = ("happy", "happy", "curious", "surprised")[min(cue_index, 3)]
    speaking = cue_start <= time <= cue_end and (int((time - cue_start) * 7) % 2 == 0)
    top, bottom = ((17, 44, 75), (20, 98, 113))
    image = _gradient(size, top, bottom)
    draw = ImageDraw.Draw(image)
    scale = min(width / 1280, height / 720)

    for index in range(10):
        x = round(width * ((index * 0.137 + 0.05) % 1))
        y = round(height * ((index * 0.193 + 0.07) % 0.82))
        radius = max(2, round((3 + index % 3) * scale))
        alpha_color = (65, 125, 149)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=alpha_color)

    panel = (round(width * 0.53), round(height * 0.20),
             round(width * 0.95), round(height * 0.79))
    draw.rounded_rectangle(panel, radius=round(34 * scale), fill=(242, 248, 245),
                           outline=(119, 208, 197), width=max(2, round(3 * scale)))
    _draw_character(draw, (width * 0.30, height * 0.59), height * 0.50,
                    time, gesture, expression, speaking)

    title_font = _font(max(22, round(height * 0.060)), bold=True)
    label_font = _font(max(15, round(height * 0.032)), bold=True)
    body_font = _font(max(13, round(height * 0.025)))
    draw.text((round(width * 0.06), round(height * 0.07)), project_title[:38],
              font=label_font, fill=(211, 235, 239))
    titles = ("HELLO, I'M PIP!", "LET'S FOLLOW WATER", "YOUR TURN TO THINK", "YOU GOT IT!")
    descriptions = (
        "Your friendly guide to big ideas.",
        "Up to the clouds, down as rain.",
        "Where might the water go next?",
        "Back to rivers, lakes and oceans.",
    )
    title, description = titles[min(cue_index, 3)], descriptions[min(cue_index, 3)]
    text_x = round(width * 0.58)
    draw.text((text_x, round(height * 0.29)), title, font=title_font, fill=(22, 57, 78))
    draw.text((text_x, round(height * 0.39)), description, font=body_font, fill=(54, 80, 95))

    if cue_index == 1:
        nodes = [("WATER", _BLUE), ("CLOUD", (151, 194, 221)), ("RAIN", _BLUE)]
        y = round(height * 0.59)
        centers = [round(width * x) for x in (0.63, 0.75, 0.87)]
        for index, ((label, color), x) in enumerate(zip(nodes, centers)):
            r = round(height * 0.045)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
            if index < len(nodes) - 1:
                draw.line((x + r + 4, y, centers[index + 1] - r - 6, y),
                          fill=(76, 134, 147), width=max(2, round(3 * scale)))
            text_w = draw.textlength(label, font=label_font)
            draw.text((x - text_w / 2, y + r + round(height * 0.018)),
                      label, font=label_font, fill=(38, 69, 84))
    elif cue_index == 2:
        bubble_x, bubble_y = round(width * 0.83), round(height * 0.62)
        r = round(height * 0.11)
        draw.ellipse((bubble_x - r, bubble_y - r, bubble_x + r, bubble_y + r),
                     fill=(255, 222, 126), outline=(222, 159, 64), width=max(2, round(3 * scale)))
        question_font = _font(max(32, round(height * 0.14)), bold=True)
        question = "?"
        qwidth = draw.textlength(question, font=question_font)
        draw.text((bubble_x - qwidth / 2, bubble_y - question_font.size * 0.61),
                  question, font=question_font, fill=(86, 62, 33))
        for offset, radius in ((0.15, 0.018), (0.20, 0.012)):
            x, y = round(width * (0.72 + offset)), round(height * (0.75 - offset))
            r = round(height * radius)
            draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 222, 126))
    else:
        stars = [
            (width * 0.64, height * 0.61, 0.028),
            (width * 0.78, height * 0.70, 0.021),
            (width * 0.88, height * 0.58, 0.018),
        ]
        for sx, sy, radius in stars:
            r = round(height * radius * (1 + 0.18 * math.sin(time * math.tau + sx)))
            draw.polygon([(round(sx), round(sy - r)), (round(sx + r * 0.3), round(sy - r * 0.3)),
                          (round(sx + r), round(sy)), (round(sx + r * 0.3), round(sy + r * 0.3)),
                          (round(sx), round(sy + r)), (round(sx - r * 0.3), round(sy + r * 0.3)),
                          (round(sx - r), round(sy)), (round(sx - r * 0.3), round(sy - r * 0.3))],
                         fill=_ORANGE)

    progress_w = round(width * 0.88)
    progress_x, progress_y = round(width * 0.06), round(height * 0.92)
    draw.rounded_rectangle((progress_x, progress_y, progress_x + progress_w,
                            progress_y + max(5, round(height * 0.012))),
                           radius=round(height * 0.006), fill=(69, 111, 130))
    marker = progress_x + round(progress_w * min(1.0, time / max(0.01, duration)))
    draw.rounded_rectangle((progress_x, progress_y, marker,
                            progress_y + max(5, round(height * 0.012))),
                           radius=round(height * 0.006), fill=_MINT_LIGHT)
    image.save(out)


def animated_guide_demo(cues: list[dict], out_dir: Path, size: tuple[int, int] = (1280, 720),
                        fps: int = 24, duration: float | None = None) -> list[tuple[Path, float]]:
    """Create a frame sequence for an original, expressive educational guide character."""
    cue_duration = max((float(cue["end"]) for cue in cues), default=0.0)
    render_duration = cue_duration if duration is None else duration
    if (render_duration < cue_duration or render_duration <= 0 or fps <= 0
            or not math.isfinite(render_duration)):
        raise ValueError("Guide demo needs positive cue duration and frame rate")
    out_dir.mkdir(parents=True, exist_ok=True)
    render_size = (round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE))
    count = math.ceil(render_duration * fps)
    frame_duration = render_duration / count
    frames = []
    for index in range(count):
        path = out_dir / f"guide_{index:04d}.png"
        _draw_demo_frame(index / fps, render_size, cues, path, duration=render_duration)
        frames.append((path, frame_duration))
    return frames


def parse_dialogue_script(script: str) -> list[dict]:
    """Parse named lines with explicit gesture and expression directions."""
    lines = []
    for line_number, raw in enumerate(script.splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        match = _DIALOGUE_LINE.fullmatch(raw)
        if not match:
            raise ValueError(f"Dialogue line {line_number} must name a character and stage direction")
        speaker, gesture, expression, text = match.groups()
        if gesture not in _DIALOGUE_GESTURES:
            raise ValueError(f"Dialogue line {line_number} has unsupported gesture {gesture!r}")
        if expression not in _DIALOGUE_EXPRESSIONS:
            raise ValueError(f"Dialogue line {line_number} has unsupported expression {expression!r}")
        lines.append({
            "speaker": speaker,
            "gesture": gesture,
            "expression": expression,
            "text": text.strip(),
        })
    if not lines or {line["speaker"] for line in lines} != set(_DIALOGUE_CHARACTERS):
        raise ValueError("Dialogue script must include Pip, Maya, and Ravi")
    return lines


def _draw_dialogue_frame(time: float, background: Image.Image, cues: list[dict],
                         out: Path, duration: float) -> None:
    size = background.size
    width, height = size
    active_index = max(
        (index for index, cue in enumerate(cues) if float(cue["start"]) <= time),
        default=0,
    )
    active = cues[active_index]
    speaker = active["speaker"]
    speaking = float(active["start"]) <= time <= float(active["end"])
    image = background.copy()
    draw = ImageDraw.Draw(image)
    scale = min(width / 1280, height / 720)

    for index in range(14):
        x = round(width * ((index * 0.137 + 0.05) % 1))
        y = round(height * ((index * 0.193 + 0.08) % 0.52))
        radius = max(2, round((2 + index % 3) * scale))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=(48, 91, 118))

    title_font = _font(max(19, round(height * 0.037)), bold=True)
    bubble_font = _font(max(23, round(height * 0.048)), bold=True)
    badge_font = _font(max(16, round(height * 0.030)), bold=True)
    small_font = _font(max(13, round(height * 0.022)))
    title = "THE WATER-CYCLE MYSTERY"
    draw.text(((width - draw.textlength(title, font=title_font)) / 2,
               round(height * 0.025)), title, font=title_font, fill=(211, 235, 239))

    bubble = (round(width * 0.07), round(height * 0.105),
              round(width * 0.93), round(height * 0.48))
    draw.rounded_rectangle(bubble, radius=round(30 * scale), fill=(247, 250, 245),
                           outline=(119, 208, 197), width=max(2, round(3 * scale)))
    character_order = ("Pip", "Maya", "Ravi")
    centers = {
        "Pip": width * 0.20,
        "Maya": width * 0.50,
        "Ravi": width * 0.80,
    }
    tail_x = round(centers[speaker])
    draw.polygon([
        (tail_x - round(27 * scale), bubble[3] - round(2 * scale)),
        (tail_x + round(29 * scale), bubble[3] - round(2 * scale)),
        (tail_x, bubble[3] + round(34 * scale)),
    ], fill=(247, 250, 245), outline=(119, 208, 197))
    speaker_name = speaker.upper()
    name_width = draw.textlength(speaker_name, font=badge_font)
    badge_x, badge_y = round(width * 0.11), round(height * 0.145)
    draw.rounded_rectangle((badge_x, badge_y, badge_x + round(name_width + 38 * scale),
                            badge_y + round(height * 0.052)),
                           radius=round(12 * scale), fill=_DIALOGUE_CHARACTERS[speaker]["accent"])
    draw.text((badge_x + round(19 * scale), badge_y + round(5 * scale)), speaker_name,
              font=badge_font, fill=_INK)

    dialogue = active["text"]
    max_text_width = round(width * 0.78)
    wrapped = _wrap(draw, dialogue, bubble_font, max_text_width)
    line_height = round(bubble_font.size * 1.28)
    text_y = round(height * 0.245)
    for line in wrapped[:3]:
        draw.text((round(width * 0.11), text_y), line,
                  font=bubble_font, fill=(25, 55, 74))
        text_y += line_height

    stage_y = round(height * 0.53)
    floor_y = round(height * 0.885)
    draw.rounded_rectangle((round(width * 0.07), stage_y, round(width * 0.93), floor_y),
                           radius=round(38 * scale), fill=(20, 62, 81),
                           outline=(43, 107, 124), width=max(2, round(2 * scale)))
    draw.line((round(width * 0.12), floor_y - round(8 * scale),
               round(width * 0.88), floor_y - round(8 * scale)),
              fill=(93, 162, 166), width=max(2, round(2 * scale)))

    for name in character_order:
        palette = _DIALOGUE_CHARACTERS[name]
        center_x = centers[name]
        is_speaking = name == speaker and speaking
        gesture = active["gesture"] if name == speaker else "idle"
        expression = active["expression"] if name == speaker else "happy"
        center_y = height * (0.735 if is_speaking else 0.755)
        character_height = height * (0.34 if is_speaking else 0.31)
        _draw_character(
            draw, (center_x, center_y), character_height, time, gesture, expression,
            is_speaking, palette["body"], palette["accent"], palette["hair"],
        )
        name_label = name
        label_width = draw.textlength(name_label, font=badge_font)
        label_x = round(center_x - label_width / 2)
        label_y = round(height * 0.91)
        tag_color = palette["accent"] if name == speaker else (190, 211, 218)
        draw.text((label_x, label_y), name_label, font=badge_font, fill=tag_color)
        if name == speaker:
            underline_y = label_y + badge_font.size + round(5 * scale)
            draw.rounded_rectangle((label_x - round(9 * scale), underline_y,
                                    label_x + round(label_width + 9 * scale),
                                    underline_y + max(3, round(4 * scale))),
                                   radius=round(3 * scale), fill=palette["accent"])

    progress_w = round(width * 0.84)
    progress_x, progress_y = round(width * 0.08), round(height * 0.955)
    bar_h = max(5, round(height * 0.012))
    draw.rounded_rectangle((progress_x, progress_y, progress_x + progress_w,
                            progress_y + bar_h), radius=round(height * 0.006),
                           fill=(69, 111, 130))
    marker = progress_x + round(progress_w * min(1.0, time / max(0.01, duration)))
    draw.rounded_rectangle((progress_x, progress_y, marker, progress_y + bar_h),
                           radius=round(height * 0.006), fill=_MINT_LIGHT)
    image.save(out)


def animated_dialogue_demo(cues: list[dict], out_dir: Path,
                           size: tuple[int, int] = (1280, 720), fps: int = 24,
                           duration: float | None = None) -> list[tuple[Path, float]]:
    """Render a three-character conversation with timed speaking turns."""
    if {cue.get("speaker") for cue in cues} != set(_DIALOGUE_CHARACTERS):
        raise ValueError("Dialogue cues must include Pip, Maya, and Ravi")
    cue_duration = max((float(cue["end"]) for cue in cues), default=0.0)
    render_duration = cue_duration if duration is None else duration
    if (render_duration < cue_duration or render_duration <= 0 or fps <= 0
            or not math.isfinite(render_duration)):
        raise ValueError("Dialogue demo needs positive cue duration and frame rate")
    out_dir.mkdir(parents=True, exist_ok=True)
    render_size = (round(size[0] * SUPERSAMPLE), round(size[1] * SUPERSAMPLE))
    background = _gradient(render_size, (17, 44, 75), (20, 98, 113))
    count = math.ceil(render_duration * fps)
    frame_duration = render_duration / count
    frames = []
    for index in range(count):
        path = out_dir / f"dialogue_{index:04d}.png"
        _draw_dialogue_frame(index / fps, background, cues, path, render_duration)
        frames.append((path, frame_duration))
    return frames
