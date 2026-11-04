"""Local web server (FastAPI). Thin routes only; all logic lives in aistudio.* services.
Rendering runs in a separate process so a crash never takes the UI down."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import config, jobs, pdfio, project, tts
from .scenes import script_to_scenes

app = FastAPI(title="AI Studio", version="0.1.0")
UI = config.ROOT / "ui" / "index.html"


def _load(pid: str) -> dict:
    try:
        return project.load(pid)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(404, str(e))


class NewProject(BaseModel):
    title: str
    mode: str = "educational"
    language: str = "en"
    voice: str = ""
    tts_backend: str = "auto"
    resolution: str = "720p"
    aspect: str = "16:9"
    fps: int = 24
    template: str | None = None


class ScriptIn(BaseModel):
    script: str
    max_words: int = 60


class RenderIn(BaseModel):
    force: bool = False
    scenes: list[str] | None = None


class PreviewIn(BaseModel):
    text: str


@app.get("/", response_class=HTMLResponse)
def index():
    return UI.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    report = config.tool_report()
    try:
        report["sapi_voices"] = tts.sapi_voices()
    except (OSError, tts.TTSError) as e:
        report["sapi_voices"] = []
        report["sapi_voices_error"] = str(e)
    return report


@app.get("/api/projects")
def projects():
    return project.list_projects()


@app.post("/api/projects")
def create_project(body: NewProject):
    if body.language not in {"en", "ur", "ur-roman"}:
        raise HTTPException(400, "language must be 'en', 'ur', or 'ur-roman'")
    if body.template not in (None, "water_cycle"):
        raise HTTPException(400, "template must be 'water_cycle'")
    if body.template == "water_cycle" and body.language != "en":
        raise HTTPException(400, "The water-cycle lesson template is currently available in English only")

    template_script = None
    if body.template == "water_cycle":
        try:
            template_script = (config.ROOT / "samples" / "sample_script.txt").read_text(encoding="utf-8")
        except OSError as e:
            raise HTTPException(500, f"Could not load the water-cycle lesson template: {e}")

    try:
        p = project.create(body.title, body.mode, language=body.language, voice=body.voice,
                           tts_backend=body.tts_backend, resolution=body.resolution,
                           aspect=body.aspect, fps=body.fps)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if template_script is not None:
        p["scenes"] = script_to_scenes(template_script, body.language)
        for scene in p["scenes"]:
            scene["visual"] = {"type": "water_cycle"}
        (project.project_dir(p["id"]) / "source" / "script.txt").write_text(
            template_script, encoding="utf-8")
        project.save(p["id"], p)
    return p


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _load(pid)


@app.put("/api/projects/{pid}")
def put_project(pid: str, body: dict):
    _load(pid)
    if body.get("id") != pid or not isinstance(body.get("scenes"), list):
        raise HTTPException(400, "Body must be a full project with matching id and a scenes list")
    project.save(pid, project.migrate(body))
    return {"saved": True}


@app.post("/api/projects/{pid}/segment")
def segment(pid: str, body: ScriptIn):
    p = _load(pid)
    p["scenes"] = script_to_scenes(body.script, p["settings"]["language"], body.max_words)
    (project.project_dir(pid) / "source" / "script.txt").write_text(body.script, encoding="utf-8")
    project.save(pid, p)
    return p


@app.get("/api/projects/{pid}/source-script")
def source_script(pid: str):
    _load(pid)
    f = project.project_dir(pid) / "source" / "script.txt"
    if not f.exists():
        raise HTTPException(404, "No saved script")
    return FileResponse(f, media_type="text/plain; charset=utf-8")


@app.post("/api/projects/{pid}/pdf")
async def upload_pdf(pid: str, file: UploadFile = File(...)):
    p = _load(pid)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a .pdf file")
    dest = project.project_dir(pid) / "source" / "book.pdf"
    dest.write_bytes(await file.read())
    analysis = pdfio.analyze_pdf(dest)
    (project.project_dir(pid) / "source" / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    p["source"]["pdf"] = "source/book.pdf"
    project.save(pid, p)
    return analysis


@app.post("/api/projects/{pid}/pdf/draft")
def draft_from_pdf(pid: str):
    p = _load(pid)
    pdf = project.project_dir(pid) / "source" / "book.pdf"
    if not pdf.exists():
        raise HTTPException(400, "Upload a PDF first")
    p["scenes"] = pdfio.draft_scenes(pdf, p["settings"]["language"])
    project.save(pid, p)
    return p


@app.post("/api/projects/{pid}/preview-audio")
def preview_audio(pid: str, body: PreviewIn):
    p = _load(pid)
    try:
        wav, _ = tts.synth_sentence(body.text[:400], p["settings"]["language"], p["settings"],
                                    project.project_dir(pid) / "cache" / "tts")
    except tts.TTSError as e:
        raise HTTPException(400, str(e))
    return FileResponse(wav, media_type="audio/wav")


@app.post("/api/projects/{pid}/render")
def start_render(pid: str, body: RenderIn):
    _load(pid)
    if jobs.read_progress(pid).get("status") == "running":
        raise HTTPException(409, "A render is already running for this project")
    cmd = [sys.executable, "-m", "engine.cli", "render", pid]
    if body.force:
        cmd.append("--force")
    for s in body.scenes or []:
        cmd += ["--scene", s]
    logf = open(project.project_dir(pid) / "logs" / "render-stdout.log", "ab")
    kw = {"creationflags": 0x08000000} if config.IS_WINDOWS else {}   # no console window on Windows
    subprocess.Popen(cmd, cwd=config.ROOT, stdout=logf, stderr=logf, **kw)
    return {"started": True}


@app.get("/api/projects/{pid}/status")
def status(pid: str):
    _load(pid)
    return {"progress": jobs.read_progress(pid), "jobs": jobs.all_jobs(pid)}


@app.get("/api/projects/{pid}/log")
def get_log(pid: str):
    f = project.project_dir(pid) / "logs" / "render.log"
    return {"log": f.read_text(encoding="utf-8")[-6000:] if f.exists() else ""}


def _file(pid: str, rel: str, mime: str, name: str):
    f = project.project_dir(pid) / rel
    if not f.exists():
        raise HTTPException(404, "Not rendered yet")
    return FileResponse(f, media_type=mime, filename=name)


@app.get("/api/projects/{pid}/video")
def video(pid: str):
    return _file(pid, "renders/final.mp4", "video/mp4", f"{pid}.mp4")


@app.get("/api/projects/{pid}/srt")
def srt(pid: str):
    return _file(pid, "renders/final.srt", "application/x-subrip", f"{pid}.srt")


def run(host: str = "127.0.0.1", port: int = 8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")
