"""Small, fact-checked starter lessons expressed using the animation schema."""
from __future__ import annotations

from . import config
from .animation import validate_instructions
from .scenes import script_to_scenes

_ELECTRIC_CIRCUIT = [
    ("A Complete Circuit",
     "A circuit needs a source of electrical energy, conducting paths, and a load. "
     "When the path is closed, current can flow and the bulb lights.",
     ["battery", "wire", "bulb", "conventional_current"],
     [("conventional_current", "flow", 0, 12), ("bulb", "pulse", 5, 5)]),
    ("Conventional Current",
     "By convention, current in the external circuit is shown from the battery's positive terminal "
     "toward its negative terminal. The arrows show this conventional-current direction.",
     ["battery", "wire", "bulb", "conventional_current"],
     [("conventional_current", "flow", 0, 12), ("conventional_current", "highlight", 2, 8)]),
    ("Electrons in a Metal Wire",
     "In a metal wire, electrons drift in the opposite direction to conventional current: "
     "from the negative terminal toward the positive terminal. These are two descriptions of charge flow.",
     ["battery", "wire", "bulb", "conventional_current", "electrons"],
     [("conventional_current", "flow", 0, 12), ("electrons", "flow", 0, 12),
      ("electrons", "highlight", 2, 8)]),
    ("An Open Switch",
     "An open switch breaks the conducting path, so a steady current does not flow and the bulb is off. "
     "Closing the switch completes the path.",
     ["battery", "open_switch", "bulb", "wire"],
     [("open_switch", "highlight", 0, 8), ("bulb", "pulse", 8, 4)]),
]

_FRENCH_REVOLUTION = [
    ("The Old Regime",
     "Before 1789, French society was legally divided into three estates. "
     "The clergy and nobility held privileges, while the Third Estate included most people and carried "
     "many tax burdens. France also faced a severe financial crisis.",
     ["three_estates", "financial_crisis", "estates_general"],
     [("three_estates", "reveal", 0, 6), ("financial_crisis", "highlight", 5, 5)]),
    ("A Revolution Begins in 1789",
     "The Estates-General met in 1789. Representatives of the Third Estate formed a National Assembly. "
     "On 14 July, a crowd in Paris took the Bastille, a royal fortress and prison.",
     ["estates_general", "national_assembly", "bastille"],
     [("estates_general", "highlight", 0, 4), ("national_assembly", "reveal", 3, 5),
      ("bastille", "reveal", 7, 5)]),
    ("Republic and the Terror",
     "The monarchy was abolished in 1792 and France became a republic. Louis the Sixteenth was executed "
     "in 1793. During 1793 and 1794, the Reign of Terror brought mass executions amid war and political conflict.",
     ["republic", "king_execution", "reign_of_terror"],
     [("republic", "reveal", 0, 4), ("king_execution", "highlight", 4, 4),
      ("reign_of_terror", "highlight", 7, 5)]),
    ("The Revolution's End and Legacy",
     "The Directory governed from 1795 until Napoleon's coup in 1799. The Revolution ended the old monarchy "
     "and spread influential ideas about citizenship and rights, though these ideals were applied unevenly.",
     ["directory", "napoleon_coup", "citizenship_rights"],
     [("directory", "reveal", 0, 5), ("napoleon_coup", "reveal", 4, 4),
      ("citizenship_rights", "highlight", 7, 5)]),
]

_TIMING = {
    "water_cycle": {
        "Introduction": (["sun", "ocean", "vapor", "cloud", "rain", "river"],
                         [("sun", "pulse", 0, 12), ("vapor", "move_up", 2, 7),
                          ("rain", "move_down", 5, 6), ("river", "flow", 7, 5)]),
        "Evaporation": (["sun", "ocean", "vapor", "plant"],
                        [("sun", "pulse", 0, 8), ("vapor", "move_up", 2, 9)]),
        "Condensation": (["vapor", "cloud", "droplets"],
                         [("vapor", "move_up", 0, 5), ("droplets", "reveal", 3, 7),
                          ("cloud", "pulse", 6, 6)]),
        "Precipitation": (["cloud", "rain", "snow", "ground"],
                          [("cloud", "pulse", 0, 5), ("rain", "move_down", 2, 8),
                           ("snow", "move_down", 5, 7)]),
        "Collection": (["rain", "river", "groundwater", "ocean"],
                       [("rain", "move_down", 0, 5), ("river", "flow", 3, 8),
                        ("groundwater", "reveal", 5, 7)]),
        "Summary": (["sun", "ocean", "vapor", "cloud", "rain", "river"],
                    [("sun", "pulse", 0, 12), ("vapor", "move_up", 1, 5),
                     ("rain", "move_down", 4, 5), ("river", "flow", 7, 5)]),
    },
}


def _instruction(scene_type: str, narration: str, objects: list[str],
                 actions: list[tuple[str, str, int, int]]) -> dict:
    return validate_instructions({
        "schema_version": 1,
        "scene_type": scene_type,
        "duration": 12,
        "objects": objects,
        "animations": [
            {"object": obj, "action": action, "start": start, "duration": duration}
            for obj, action, start, duration in actions
        ],
        "narration": narration,
    })


def build_lesson(template: str) -> tuple[list[dict], str]:
    """Build scenes and source script for a supported, English starter lesson."""
    if template == "water_cycle":
        script = (config.ROOT / "samples" / "sample_script.txt").read_text(encoding="utf-8")
        scenes = script_to_scenes(script)
        timing = _TIMING[template]
        for scene in scenes:
            objects, actions = timing.get(scene["heading"], timing["Summary"])
            scene["visual"] = {
                "type": "water_cycle",
                "instructions": _instruction("science_process", scene["narration"], objects, actions),
            }
        return scenes, script

    lesson = {"electric_circuit": _ELECTRIC_CIRCUIT, "french_revolution": _FRENCH_REVOLUTION}.get(template)
    if lesson is None:
        raise ValueError(f"Unknown lesson template: {template}")
    script_parts = []
    scenes = []
    scene_type = "electric_circuit" if template == "electric_circuit" else "history_timeline"
    for index, (heading, narration, objects, actions) in enumerate(lesson, 1):
        scenes.append({
            "scene_id": f"s{index:03d}",
            "heading": heading,
            "narration": narration,
            "language": "en",
            "visual": {"type": "instruction_scene",
                       "instructions": _instruction(scene_type, narration, objects, actions)},
            "background": None,
            "characters": [],
            "animation": None,
            "duration_sec": None,
            "subtitle": {"enabled": True},
            "source_refs": [],
            "camera": {"move": "none"},
            "dramatized": False,
            "status": "draft",
        })
        script_parts.append(f"# {heading}\n{narration}")
    return scenes, "\n\n".join(script_parts)
