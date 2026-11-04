import shutil

import pymupdf
import pytest
from fastapi.testclient import TestClient

from aistudio import config, pdfio, project


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
