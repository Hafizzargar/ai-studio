"""Command-line engine. The UI is just an editor for project.json; this renders it.

  python -m engine.cli doctor
  python -m engine.cli quick samples/sample_script.txt --title "Water Cycle"
  python -m engine.cli render <project_id> [--force] [--scene s003]
  python -m engine.cli pdf-analyze file.pdf
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from aistudio import config, pdfio, project, render
from aistudio.jobs import all_jobs
from aistudio.scenes import script_to_scenes


def _segment(pid: str, text: str):
    p = project.load(pid)
    p["scenes"] = script_to_scenes(text, p["settings"]["language"])
    (project.project_dir(pid) / "source" / "script.txt").write_text(text, encoding="utf-8")
    project.save(pid, p)
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ai-studio")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    q = sub.add_parser("quick")
    q.add_argument("script")
    q.add_argument("--title", default="Quick project")
    q.add_argument("--mode", default="educational", choices=project.MODES)
    q.add_argument("--backend", default="auto")
    q.add_argument("--voice", default="")
    q.add_argument("--resolution", default="720p")
    q.add_argument("--aspect", default="16:9")
    r = sub.add_parser("render")
    r.add_argument("project_id")
    r.add_argument("--force", action="store_true")
    r.add_argument("--scene", action="append")
    s = sub.add_parser("status")
    s.add_argument("project_id")
    pa = sub.add_parser("pdf-analyze")
    pa.add_argument("pdf")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    if a.cmd == "doctor":
        print(json.dumps(config.tool_report(), indent=2))
        return 0
    if a.cmd == "pdf-analyze":
        print(json.dumps(pdfio.analyze_pdf(a.pdf), indent=2, ensure_ascii=False))
        return 0
    if a.cmd == "quick":
        p = project.create(a.title, a.mode, tts_backend=a.backend, voice=a.voice,
                           resolution=a.resolution, aspect=a.aspect)
        _segment(p["id"], Path(a.script).read_text(encoding="utf-8"))
        print("Project:", p["id"])
        a.project_id, a.force, a.scene = p["id"], False, None
        a.cmd = "render"
    if a.cmd == "status":
        print(json.dumps({"progress": render.jobs.read_progress(a.project_id), "jobs": all_jobs(a.project_id)}, indent=2))
        return 0
    if a.cmd == "render":
        res = render.render_project(a.project_id, force=a.force, only=a.scene)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
