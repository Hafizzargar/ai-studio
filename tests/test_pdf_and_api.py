import copy
import shutil

import pymupdf
import pytest
from fastapi.testclient import TestClient

from aistudio import config, pdfio, project, tts


@pytest.fixture(autouse=True)
def tmp_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")


def make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Chapter 1: Photosynthesis", fontsize=22)
    page.insert_text((72, 130), "Photosynthesis is defined as the process by which plants make food using light.", fontsize=11)
    page.insert_text((72, 150), "It takes place in the chloroplasts of green leaves. The process was studied in 1779.", fontsize=11)
    page.insert_text((72, 200), "Light reactions", fontsize=16)
    page.insert_text((72, 225), "During the light reactions, chlorophyll absorbs sunlight and splits water molecules.", fontsize=11)
    doc.save(str(path))


def test_pdf_analysis_and_draft(tmp_path):
    pdf = tmp_path / "b.pdf"
    make_pdf(pdf)
    a = pdfio.analyze_pdf(pdf)
    texts = [h["text"] for h in a["headings"]]
    assert any("Photosynthesis" in t for t in texts) and "Light reactions" in texts
    assert any("defined as" in d["text"] for d in a["definitions"])
    assert "1779" in a["years"]
    sc = pdfio.draft_scenes(pdf)
    assert sc and sc[0]["source_refs"][0]["page"] == 1


def test_highlight_rects_found(tmp_path):
    pdf = tmp_path / "b.pdf"
    make_pdf(pdf)
    page = pymupdf.open(str(pdf))[0]
    assert pdfio.find_highlights(page, ["It takes place in the chloroplasts of green leaves."])


def test_roman_urdu_language_and_windows_voice_list(monkeypatch):
    from aistudio.server import app

    monkeypatch.setattr(tts, "sapi_voices", lambda: ["Microsoft Zira Desktop"])
    client = TestClient(app)
    response = client.post("/api/projects", json={
        "title": "Roman Urdu", "language": "ur-roman", "tts_backend": "auto",
    })

    assert response.status_code == 200
    assert response.json()["settings"]["language"] == "ur-roman"
    assert client.get("/api/health").json()["sapi_voices"] == ["Microsoft Zira Desktop"]


def test_health_reports_windows_voice_discovery_failure(monkeypatch):
    from aistudio.server import app

    def fail_voice_discovery():
        raise tts.TTSError("PowerShell voice discovery failed")

    monkeypatch.setattr(tts, "sapi_voices", fail_voice_discovery)
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["sapi_voices"] == []
    assert response.json()["sapi_voices_error"] == "PowerShell voice discovery failed"


def test_water_cycle_lesson_template_creates_animated_scenes():
    from aistudio.server import app

    client = TestClient(app)
    response = client.post("/api/projects", json={
        "title": "Water Cycle Lesson", "template": "water_cycle", "tts_backend": "silent",
    })

    assert response.status_code == 200
    data = response.json()
    assert len(data["scenes"]) == 6
    assert [scene["heading"] for scene in data["scenes"]] == [
        "Introduction", "Evaporation", "Condensation", "Precipitation", "Collection", "Summary",
    ]
    assert all(scene["visual"]["type"] == "water_cycle" for scene in data["scenes"])
    assert (project.project_dir(data["id"]) / "source" / "script.txt").read_text(
        encoding="utf-8").startswith("# Introduction")

    unsupported_language = client.post("/api/projects", json={
        "title": "Urdu Water Cycle", "template": "water_cycle", "language": "ur",
    })
    assert unsupported_language.status_code == 400


def test_structured_lesson_templates_are_available_through_api():
    from aistudio.server import app

    client = TestClient(app)
    expected_types = {
        "water_cycle": ("science_process", "water_cycle"),
        "electric_circuit": ("electric_circuit", "instruction_scene"),
        "french_revolution": ("history_timeline", "instruction_scene"),
    }
    for template, (scene_type, visual_type) in expected_types.items():
        response = client.post("/api/projects", json={
            "title": template.replace("_", " ").title(),
            "template": template,
            "tts_backend": "silent",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["scenes"]
        assert all(scene["visual"]["type"] == visual_type for scene in data["scenes"])
        assert all(scene["visual"]["instructions"]["scene_type"] == scene_type
                   for scene in data["scenes"])
        assert (project.project_dir(data["id"]) / "source" / "script.txt").exists()

    unsupported_language = client.post("/api/projects", json={
        "title": "Roman Urdu Circuit", "template": "electric_circuit", "language": "ur-roman",
    })
    assert unsupported_language.status_code == 400


def test_changed_narration_blocks_render_until_manual_instruction_review():
    from aistudio import render
    from aistudio.animation import instruction_status
    from aistudio.server import app

    client = TestClient(app)
    data = client.post("/api/projects", json={
        "title": "Narration review", "template": "electric_circuit", "tts_backend": "silent",
    }).json()
    scene = data["scenes"][0]
    original = copy.deepcopy(scene["visual"]["instructions"])
    scene["narration"] = "The circuit remains open. Current does not flow."
    put = client.put(f"/api/projects/{data['id']}", json=data)

    assert put.status_code == 200
    loaded = project.load(data["id"])
    edited_scene = loaded["scenes"][0]
    assert edited_scene["visual"]["instructions"] == original
    assert instruction_status(edited_scene) == ("generated", "stale")
    with pytest.raises(render.RenderError, match="review and save"):
        render.render_scene(loaded, edited_scene, 1, len(loaded["scenes"]))

    unmapped = copy.deepcopy(original)
    unmapped["animations"][0].pop("sentence_index")
    unmapped["animations"][0].update({"start": 0, "duration": 5})
    rejected = client.post(
        f"/api/projects/{data['id']}/scenes/{scene['scene_id']}/instructions/review",
        json={"instructions": unmapped},
    )
    assert rejected.status_code == 400

    reviewed = client.post(
        f"/api/projects/{data['id']}/scenes/{scene['scene_id']}/instructions/review",
        json={"instructions": original},
    )
    assert reviewed.status_code == 200
    reviewed_scene = reviewed.json()["scene"]
    assert instruction_status(reviewed_scene) == ("manual", "current")
    assert reviewed_scene["visual"]["instructions"]["animations"] == original["animations"]
    assert reviewed_scene["visual"]["instructions"]["narration"] == edited_scene["narration"]


def test_instruction_status_api_uses_backend_fingerprint_and_does_not_persist_display_state():
    from aistudio.server import app

    client = TestClient(app)
    data = client.post("/api/projects", json={
        "title": "Instruction status", "template": "electric_circuit", "tts_backend": "silent",
    }).json()
    pid = data["id"]
    response = client.get(f"/api/projects/{pid}")
    assert response.json()["_instruction_status"]["s001"] == {
        "origin": "generated",
        "state": "current",
    }

    stale_project = response.json()
    stale_project["scenes"][0]["visual"]["instruction_meta"]["narration_hash"] = "mismatch"
    saved = client.put(f"/api/projects/{pid}", json=stale_project)

    assert saved.status_code == 200
    expected = {"origin": "generated", "state": "stale"}
    assert saved.json()["_instruction_status"]["s001"] == expected
    assert client.get(f"/api/projects/{pid}").json()["_instruction_status"]["s001"] == expected
    persisted = project.load(pid)
    assert "_instruction_status" not in persisted
    assert all("_instruction_status" not in scene for scene in persisted["scenes"])


def test_sentence_count_change_after_manual_review_requires_remapping():
    from aistudio import render
    from aistudio.animation import instruction_status
    from aistudio.server import app

    client = TestClient(app)
    data = client.post("/api/projects", json={
        "title": "Sentence count change", "template": "electric_circuit", "tts_backend": "silent",
    }).json()
    pid = data["id"]
    scene = data["scenes"][0]
    original_instructions = copy.deepcopy(scene["visual"]["instructions"])
    reviewed = client.post(
        f"/api/projects/{pid}/scenes/s001/instructions/review",
        json={"instructions": original_instructions},
    )
    assert reviewed.status_code == 200

    data = project.load(pid)
    data["scenes"][0]["narration"] = "The circuit explanation has been rewritten."
    assert len(data["scenes"][0]["narration"].split(". ")) == 1
    assert client.put(f"/api/projects/{pid}", json=data).status_code == 200

    stale_scene = project.load(pid)["scenes"][0]
    assert instruction_status(stale_scene) == ("manual", "stale")
    assert stale_scene["visual"]["instructions"]["animations"] == original_instructions["animations"]
    with pytest.raises(render.RenderError, match="review and save"):
        render.render_scene(project.load(pid), stale_scene, 1, len(data["scenes"]))

    remap = client.post(
        f"/api/projects/{pid}/scenes/s001/instructions/review",
        json={"instructions": original_instructions},
    )
    assert remap.status_code == 400
    assert "sentence_index is outside the narration" in remap.json()["detail"]
    unchanged = project.load(pid)["scenes"][0]
    assert unchanged["visual"]["instructions"]["animations"] == original_instructions["animations"]
    assert instruction_status(unchanged) == ("manual", "stale")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_instruction_scene_rendering_for_each_subject():
    from aistudio import lessons, render

    for template in ("water_cycle", "electric_circuit", "french_revolution"):
        data = project.create(template.replace("_", " ").title(), tts_backend="silent", fps=24)
        lesson_scenes, _ = lessons.build_lesson(template)
        data["scenes"] = lesson_scenes[:1]
        project.save(data["id"], data)
        clip, duration = render.render_scene(data, data["scenes"][0], 1, 1)

        assert clip.exists() and duration > 0
        expected_animation = "water_cycle.mp4" if template == "water_cycle" else "instruction.mp4"
        assert (project.project_dir(data["id"]) / "scenes" / "s001" / expected_animation).exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_complete_water_cycle_lesson_renders_animation_to_video():
    from aistudio import render
    from aistudio.server import app

    client = TestClient(app)
    data = client.post("/api/projects", json={
        "title": "Water Cycle Render", "template": "water_cycle", "tts_backend": "silent",
    }).json()
    project.save(data["id"], data)

    result = render.render_project(data["id"])

    assert result["ok"] and result["valid"]
    assert len(data["scenes"]) == 6
    assert all((project.project_dir(data["id"]) / "scenes" / scene["scene_id"]
                / "water_cycle.mp4").exists() for scene in data["scenes"])
    assert (project.project_dir(data["id"]) / "renders" / "final.mp4").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_api_flow_with_pdf(tmp_path):
    from aistudio.server import app
    from aistudio import render
    c = TestClient(app)
    p = c.post("/api/projects", json={"title": "API test", "tts_backend": "silent"}).json()
    pid = p["id"]
    pdf = tmp_path / "b.pdf"
    make_pdf(pdf)
    r = c.post(f"/api/projects/{pid}/pdf", files={"file": ("b.pdf", pdf.read_bytes(), "application/pdf")})
    assert r.status_code == 200 and r.json()["page_count"] == 1
    d = c.post(f"/api/projects/{pid}/pdf/draft").json()
    assert d["scenes"][0]["visual"]["type"] == "pdf_page"
    res = render.render_project(pid)               # PDF page + highlight scene
    assert res["ok"] and res["valid"]
    assert c.get(f"/api/projects/{pid}/video").status_code == 200
    assert c.get(f"/api/projects/{pid}/status").json()["progress"]["status"] == "done"
    assert c.get("/api/projects/../x").status_code in (404, 422)
