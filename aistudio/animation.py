"""Validation for the structured instructions consumed by the 2D renderer."""
from __future__ import annotations

import math
import re

SCENE_TYPES = {"science_process", "electric_circuit", "history_timeline"}
ACTIONS = {"flow", "highlight", "move_down", "move_left", "move_right", "move_up", "pulse", "reveal"}
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_DURATION = 120
MAX_OBJECTS = 16
MAX_ANIMATIONS = 24
MAX_NARRATION_LENGTH = 5000


class InstructionError(ValueError):
    """Raised when scene instructions are outside the supported render schema."""


def validate_instructions(instructions: dict) -> dict:
    """Validate and return supported structured scene instructions."""
    if not isinstance(instructions, dict):
        raise InstructionError("Animation instructions must be an object")

    required = {"schema_version", "scene_type", "duration", "objects", "animations", "narration"}
    if set(instructions) != required:
        missing = sorted(required - set(instructions))
        extra = sorted(set(instructions) - required)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unsupported {', '.join(extra)}")
        raise InstructionError("Animation instructions have " + " and ".join(details))
    version = instructions["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise InstructionError("Animation schema_version must be 1")
    if not isinstance(instructions["scene_type"], str) or instructions["scene_type"] not in SCENE_TYPES:
        raise InstructionError(f"Unsupported scene_type: {instructions['scene_type']!r}")

    duration = instructions["duration"]
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise InstructionError("Animation duration must be a number")
    if not math.isfinite(duration) or not 1 <= duration <= MAX_DURATION:
        raise InstructionError(f"Animation duration must be between 1 and {MAX_DURATION} seconds")

    objects = instructions["objects"]
    if not isinstance(objects, list) or not objects or len(objects) > MAX_OBJECTS:
        raise InstructionError(f"Animation objects must contain 1 to {MAX_OBJECTS} ids")
    if any(not isinstance(obj, str) or not _ID_RE.fullmatch(obj) for obj in objects):
        raise InstructionError("Animation object ids must be lowercase snake_case identifiers")
    if len(set(objects)) != len(objects):
        raise InstructionError("Animation object ids must be unique")

    animations = instructions["animations"]
    if not isinstance(animations, list) or len(animations) > MAX_ANIMATIONS:
        raise InstructionError(f"Animation animations must contain at most {MAX_ANIMATIONS} actions")
    for index, animation in enumerate(animations):
        if not isinstance(animation, dict) or set(animation) - {"object", "action", "start", "duration"}:
            raise InstructionError(f"Animation action {index + 1} has unsupported fields")
        if not {"object", "action", "duration"} <= set(animation):
            raise InstructionError(f"Animation action {index + 1} needs object, action, and duration")
        if not isinstance(animation["object"], str) or animation["object"] not in objects:
            raise InstructionError(f"Animation action {index + 1} refers to an unknown object")
        if not isinstance(animation["action"], str) or animation["action"] not in ACTIONS:
            raise InstructionError(f"Animation action {index + 1} has an unsupported action")
        start = animation.get("start", 0)
        action_duration = animation["duration"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               for value in (start, action_duration)):
            raise InstructionError(f"Animation action {index + 1} timing must use finite numbers")
        if (start < 0 or action_duration <= 0 or start + action_duration > duration
                or not math.isfinite(start) or not math.isfinite(action_duration)):
            raise InstructionError(f"Animation action {index + 1} must fit inside the scene duration")

    narration = instructions["narration"]
    if (not isinstance(narration, str) or not narration.strip()
            or len(narration) > MAX_NARRATION_LENGTH):
        raise InstructionError(
            f"Animation narration must contain 1 to {MAX_NARRATION_LENGTH} characters"
        )
    return instructions
