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


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_water_cycle_lesson_renders_animation_to_video():
    from aistudio import render
    from aistudio.server import app

    client = TestClient(app)
    data = client.post("/api/projects", json={
        "title": "Water Cycle Render", "template": "water_cycle", "tts_backend": "silent",
    }).json()
    data["scenes"] = data["scenes"][:1]
    data["scenes"][0]["narration"] = "Water moves around Earth."
    project.save(data["id"], data)

    result = render.render_project(data["id"])

    assert result["ok"] and result["valid"]
    assert (project.project_dir(data["id"]) / "scenes" / "s001" / "water_cycle.mp4").exists()


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
