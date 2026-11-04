import json
import shutil
import wave

from PIL import Image, ImageChops
import pytest

from aistudio import config, project, scenes, subtitles, tts, jobs, visuals
from aistudio.animation import InstructionError, validate_instructions
from aistudio.lessons import build_lesson


@pytest.fixture(autouse=True)
def tmp_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path


def test_sentence_split_handles_abbreviations():
    s = scenes.split_sentences("Dr. Singh arrived. He spoke e.g. about water! Did it rain? Yes.")
    assert s == ["Dr. Singh arrived.", "He spoke e.g. about water!", "Did it rain?", "Yes."]


def test_urdu_sentence_split():
    assert len(scenes.split_sentences("یہ پہلا جملہ ہے۔ یہ دوسرا جملہ ہے۔")) == 2


def test_script_to_scenes_headings_and_chunking():
    text = "# One\n" + " ".join(["Word word word word word."] * 30) + "\n\n# Two\nShort scene."
    sc = scenes.script_to_scenes(text, max_words=50)
    assert sc[0]["heading"] == "One" and sc[-1]["heading"] == "Two"
    assert len(sc) >= 3
    assert all(len(s["narration"].split()) <= 55 for s in sc)


def test_title_card_draws_diagram_from_scene_narration(tmp_path):
    scene = scenes.new_scene(
        1,
        "Condensation",
        "Water vapour cools into tiny droplets. The droplets gather to form clouds.",
    )
    labels = visuals._diagram_labels(scene)
    assert labels == ["Water vapour", "tiny droplets", "clouds"]

    output = tmp_path / "diagram.png"
    visuals.title_card(scene, 1, 1, "Water Cycle", (1280, 720), "educational", output)
    with Image.open(output) as image:
        assert image.size == (1920, 1080)
        colors = image.convert("RGB").getcolors(image.width * image.height)
        assert colors is not None
        assert any(color[0] < 30 and color[1] < 55 and color[2] < 70 and count > 1000
                   for count, color in colors)

    portrait = tmp_path / "portrait-diagram.png"
    visuals.title_card(scene, 1, 1, "Water Cycle", (720, 1280), "educational", portrait)
    with Image.open(portrait) as image:
        assert image.size == (1080, 1920)
        colors = image.convert("RGB").getcolors(image.width * image.height)
        assert colors is not None
        assert any(color[0] < 30 and color[1] < 55 and color[2] < 70 and count > 1000
                   for count, color in colors)


def test_diagram_reveals_and_highlights_concepts_at_spoken_words():
    scene = scenes.new_scene(
        1,
        "Evaporation",
        "The water cycle begins. Evaporation starts. Vapour cools. Tiny droplets form clouds.",
    )
    cues = [
        {"start": 0.0, "end": 2.0, "text": "The water cycle begins."},
        {"start": 2.0, "end": 4.0, "text": "Evaporation starts."},
        {"start": 4.0, "end": 6.0, "text": "Vapour cools."},
        {"start": 6.0, "end": 9.0, "text": "Tiny droplets form clouds."},
    ]
    title = "Water Cycle SAPI Test"
    labels = visuals._diagram_labels(scene, project_title=title)
    states = visuals.diagram_timeline(scene, cues, project_title=title)
    active_labels = [labels[state[2]] for state in states if state[2] is not None]

    assert labels[0] == "Water Cycle"
    assert "Evaporation" in labels
    assert active_labels[:2] == ["Water Cycle", "Evaporation"]
    assert sum(state[0] for state in states) == pytest.approx(9.0)
    landscape = visuals._diagram_layout((1920, 1080), labels)
    portrait = visuals._diagram_layout((1080, 1920), labels)
    assert landscape[0][0] < landscape[1][0]
    assert len({box[0] for box in landscape[1:]}) == 1
    assert len({box[1] for box in portrait}) == len(portrait)


def test_water_cycle_animation_has_motion_and_focuses_scene_phase(tmp_path):
    scene = scenes.new_scene(1, "Precipitation", "Cloud droplets fall as rain.")
    assert visuals.water_cycle_phase(scene["heading"]) == "precipitation"
    frames = visuals.animated_water_cycle(
        scene, "Water Cycle", (320, 180), "educational", tmp_path, fps=4, loop_seconds=2
    )
    assert len(frames) == 8
    assert all(path.exists() and duration == pytest.approx(0.25) for path, duration in frames)
    with Image.open(frames[0][0]) as first:
        assert first.size == (480, 270)
        initial = first.convert("RGB")
    moved = False
    for path, _ in frames[1:]:
        with Image.open(path) as later:
            moved = moved or ImageChops.difference(
                initial, later.convert("RGB")
            ).getbbox() is not None
    assert moved


def test_instruction_schema_rejects_invalid_actions_and_timing():
    instructions = {
        "schema_version": 1,
        "scene_type": "science_process",
        "duration": 12,
        "objects": ["water", "vapor"],
        "animations": [{"object": "vapor", "action": "move_up", "start": 2, "duration": 5}],
        "narration": "Water evaporates.",
    }
    assert validate_instructions(instructions) is instructions

    invalid = {**instructions, "animations": [
        {"object": "missing", "action": "move_up", "start": 2, "duration": 5},
    ]}
    with pytest.raises(InstructionError, match="unknown object"):
        validate_instructions(invalid)

    invalid = {**instructions, "animations": [
        {"object": "vapor", "action": "move_up", "start": 9, "duration": 5},
    ]}
    with pytest.raises(InstructionError, match="fit inside"):
        validate_instructions(invalid)


def test_structured_lessons_render_moving_frames_for_three_subjects(tmp_path):
    examples = {
        "water_cycle": ("science_process", "water_cycle"),
        "electric_circuit": ("electric_circuit", "instruction_scene"),
        "french_revolution": ("history_timeline", "instruction_scene"),
    }
    for template, (scene_type, visual_type) in examples.items():
        lesson_scenes, script = build_lesson(template)
        assert lesson_scenes and script.startswith("# ")
        scene = lesson_scenes[0]
        instructions = validate_instructions(scene["visual"]["instructions"])
        assert scene["visual"]["type"] == visual_type
        assert instructions["scene_type"] == scene_type
        frames = visuals.animated_instruction_scene(
            scene, template.replace("_", " ").title(), (320, 180), "educational", tmp_path / template,
            fps=4, loop_seconds=2,
        )
        assert len(frames) == 8
        assert all(path.exists() and duration == pytest.approx(0.25) for path, duration in frames)
        with Image.open(frames[0][0]) as first:
            assert first.size == (480, 270)
            initial = first.convert("RGB")
        moved = False
        for path, _ in frames[1:]:
            with Image.open(path) as later:
                moved = moved or ImageChops.difference(
                    initial, later.convert("RGB")
                ).getbbox() is not None
        assert moved


def test_instruction_animation_spans_narration_duration(tmp_path):
    scene = build_lesson("electric_circuit")[0][0]
    frames = visuals.animated_instruction_scene(
        scene, "Electric Circuit", (320, 180), "educational", tmp_path,
        fps=4, scene_duration=6,
    )

    assert len(frames) == 24
    assert sum(duration for _, duration in frames) == pytest.approx(6)


def test_overlapping_instruction_actions_are_preserved():
    instructions = {
        "animations": [
            {"object": "current", "action": "flow", "start": 0, "duration": 12},
            {"object": "current", "action": "highlight", "start": 2, "duration": 8},
        ],
    }

    state = visuals._instruction_state(instructions, 4)

    assert set(state["current"]) == {"flow", "highlight"}
    assert state["current"]["flow"]["progress"] == pytest.approx(1 / 3)
    assert state["current"]["highlight"]["progress"] == pytest.approx(0.25)


def test_starter_diagrams_preserve_teaching_relationships(tmp_path, monkeypatch):
    water_scenes, _ = build_lesson("water_cycle")
    water_positions = visuals._instruction_positions(
        "science_process", water_scenes[0]["visual"]["instructions"]["objects"]
    )
    assert water_positions["ocean"][1] > water_positions["vapor"][1]
    assert water_positions["vapor"][1] > water_positions["cloud"][1]
    assert water_positions["cloud"][1] < water_positions["rain"][1]
    assert water_positions["rain"][1] < water_positions["river"][1]

    circuit_scenes, _ = build_lesson("electric_circuit")
    circuit = circuit_scenes[2]
    original_arrow = visuals._arrow
    arrows = []

    def record_arrow(draw, start, end, color, width):
        arrows.append((start, end, color))
        original_arrow(draw, start, end, color, width)

    monkeypatch.setattr(visuals, "_arrow", record_arrow)
    visuals._draw_instruction_frame(
        circuit, circuit["visual"]["instructions"], "Electric Circuit",
        (480, 270), "educational", 0.5, tmp_path / "circuit.png",
    )
    assert ((134, 73), (206, 73), (255, 190, 78)) in arrows
    assert ((206, 73), (134, 73), (102, 210, 255)) in arrows

    open_switch = {
        "heading": "Open switch",
        "visual": {"instructions": {
            "scene_type": "electric_circuit",
            "duration": 1,
            "objects": ["battery", "open_switch", "bulb", "wire"],
            "animations": [],
        }},
    }
    switch_path = tmp_path / "open_switch.png"
    visuals._draw_instruction_frame(
        open_switch, open_switch["visual"]["instructions"], "Circuit",
        (480, 270), "educational", 0, switch_path,
    )
    with Image.open(switch_path) as image:
        pixels = image.convert("RGB")
        assert pixels.getpixel((220, 73)) == (116, 190, 207)
        assert pixels.getpixel((260, 73)) == (116, 190, 207)
        assert pixels.getpixel((240, 73)) != (116, 190, 207)

    history_scenes, _ = build_lesson("french_revolution")
    timeline = history_scenes[1]["visual"]["instructions"]
    timeline_positions = visuals._instruction_positions("history_timeline", timeline["objects"])
    assert timeline["objects"] == ["estates_general", "national_assembly", "bastille"]
    assert [visuals._HISTORY_DATES[obj] for obj in timeline["objects"]] == [
        "5 May 1789", "17 Jun 1789", "14 Jul 1789",
    ]
    assert [timeline_positions[obj][0] for obj in timeline["objects"]] == sorted(
        timeline_positions[obj][0] for obj in timeline["objects"]
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_concat_reencodes_continuous_timestamps_for_long_lessons():
    from aistudio import render

    data = project.create("Concat timing", tts_backend="silent", fps=24)
    scene_clips = []
    durations = []
    for index in range(20):
        scene_id = f"s{index + 1:03d}"
        scene_dir = render.scene_dir(data["id"], scene_id)
        scene_dir.mkdir(parents=True)
        clip = scene_dir / "clip.mp4"
        requested_duration = 0.8 + (index % 4) * 0.1
        render._run([
            render.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x90:r=24:d={requested_duration}",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(requested_duration), "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "30", "-bf", "0", "-pix_fmt", "yuv420p", "-r", "24",
            "-video_track_timescale", "24000", "-c:a", "aac", "-b:a", "64k",
            "-ar", "44100", "-ac", "2", "-shortest", str(clip),
        ])
        (scene_dir / "cues.json").write_text("[]", encoding="utf-8")
        scene_clips.append(clip)
        durations.append(render.probe_duration(clip))

    for count in (2, 6, 10, 20):
        result = render.assemble(data, scene_clips[:count], durations[:count])
        assert result["valid"], f"{count}-scene lesson failed validation: {result}"
        assert result["drift_sec"] < 0.5


def test_hash_changes_only_when_relevant():
    p = project.default_settings()
    s = scenes.new_scene(1, "A", "Hello there.")
    h1 = scenes.scene_hash(s, p)
    s["status"] = "approved"
    assert scenes.scene_hash(s, p) == h1
    s["narration"] = "Hello again."
    assert scenes.scene_hash(s, p) != h1
    assert scenes.scene_hash(s, p, "Water Cycle") != scenes.scene_hash(s, p, "Photosynthesis")


def test_project_save_backup_and_recover():
    d = project.create("Crash test")
    pid = d["id"]
    for i in range(8):
        d["title"] = f"v{i}"
        project.save(pid, d)
    assert len(list((project.project_dir(pid) / "backups").glob("*.json"))) <= project.KEEP_BACKUPS
    (project.project_dir(pid) / "project.json").write_text("{corrupt", encoding="utf-8")
    assert project.load(pid)["id"] == pid          # recovered from backup


def test_invalid_project_id_rejected():
    with pytest.raises(ValueError):
        project.project_dir("../etc")


def test_srt_and_ass(tmp_path):
    cues = [{"start": 0.5, "end": 2.25, "text": "Hello {world}"}]
    subtitles.write_srt(cues, tmp_path / "a.srt")
    assert "00:00:00,500 --> 00:00:02,250" in (tmp_path / "a.srt").read_text()
    subtitles.write_ass(cues, tmp_path / "a.ass", 1280, 720, project.default_settings()["subtitles"])
    ass = (tmp_path / "a.ass").read_text()
    assert "Dialogue: 0,0:00:00.50,0:00:02.25" in ass and "{world}" not in ass


def test_roman_urdu_is_blocked():
    with pytest.raises(tts.TTSError):
        tts.check_language("ur-roman", "piper", "x")


def test_roman_urdu_uses_windows_voice_when_backend_is_auto(tmp_path, monkeypatch):
    def fake_sapi(text, output, voice, speed):
        with wave.open(str(output), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(tts.RATE)
            audio.writeframes(b"\x01\x00" * tts.RATE)

    monkeypatch.setattr(tts, "available_backends", lambda: {
        "piper": False, "sapi": True, "espeak": False, "silent": True,
    })
    monkeypatch.setitem(tts._BACKENDS, "sapi", fake_sapi)

    path, backend = tts.synth_sentence(
        "Yeh Roman Urdu hai.", "ur-roman", {"tts_backend": "auto", "voice": ""}, tmp_path / "cache"
    )

    assert backend == "sapi"
    assert path.exists()


def test_urdu_needs_urdu_voice():
    with pytest.raises(tts.TTSError):
        tts.check_language("ur", "piper", "en_US-lessac-medium")


def test_silent_audio_cues_match_audio_length(tmp_path):
    st = project.default_settings()
    st["tts_backend"] = "silent"
    cues, total, used = tts.build_scene_audio(["One two three.", "Four five six seven."], "en", st,
                                              tmp_path / "c", tmp_path / "n.wav")
    with wave.open(str(tmp_path / "n.wav")) as w:
        assert abs(w.getnframes() / w.getframerate() - total) < 0.01
    assert cues[0]["end"] <= cues[1]["start"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_end_to_end_render_resume_and_failure(monkeypatch):
    from aistudio import render
    d = project.create("E2E", tts_backend="silent", resolution="720p")
    d["scenes"] = scenes.script_to_scenes("# A\nFirst scene here.\n\n# B\nSecond scene here.")
    project.save(d["id"], d)
    res = render.render_project(d["id"])
    assert res["ok"] and res["valid"] and res["drift_sec"] < 0.5

    # second run: everything cached
    calls = []
    orig = render.render_scene
    monkeypatch.setattr(render, "render_scene", lambda *a, **k: calls.append(1) or orig(*a, **k))
    render.render_project(d["id"])
    assert calls == []

    # edit one scene: only that one re-renders
    d = project.load(d["id"])
    d["scenes"][1]["narration"] = "Second scene changed text."
    project.save(d["id"], d)
    render.render_project(d["id"])
    assert len(calls) == 1

    # a failing scene does not lose the others
    d = project.load(d["id"])
    d["scenes"][0]["narration"] = "   "
    project.save(d["id"], d)
    out = render.render_project(d["id"])
    assert not out["ok"] and out["failed"][0]["scene_id"] == "s001"
    assert jobs.get(d["id"], "s002")["status"] == "done"
