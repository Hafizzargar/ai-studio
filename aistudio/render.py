"""Scene-by-scene rendering with checkpoints, resume, final assembly and validation."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import traceback
from pathlib import Path

from . import config, jobs, project, subtitles, tts, visuals
from .scenes import scene_hash, split_sentences

log = logging.getLogger("aistudio.render")


class RenderError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-12:])
        raise RenderError(f"{Path(cmd[0]).name} exited {p.returncode}:\n{tail}")
    return p.stdout


def ffmpeg() -> str:
    exe = config.find_exe("ffmpeg")
    if not exe:
        raise RenderError("ffmpeg not found. Put ffmpeg.exe in the vendor/ folder or add it to PATH.")
    return exe


def probe_duration(path: Path) -> float:
    exe = config.find_exe("ffprobe") or "ffprobe"
    out = _run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def _write_progress(pid: str, **kw):
    p = project.project_dir(pid) / "progress.json"
    d = {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    d.update(kw, heartbeat=time.time())
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, p)


def _camera_filter(move: str, dur: float, fps: int, size) -> str:
    frames = max(1, int(dur * fps))
    step = 0.10 / frames
    z = {"slow_zoom_in": f"min(1+{step:.8f}*on,1.10)", "slow_zoom_out": f"max(1.10-{step:.8f}*on,1.0)"}.get(move, "1")
    return (f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={size[0]}x{size[1]}:fps={fps}")


def _encode_diagram_frames(frames: list[tuple[Path, float]], out: Path, fps: int,
                           duration: float, cwd: Path) -> None:
    listing = cwd / "diagram_frames.txt"
    lines = []
    for path, frame_duration in frames:
        lines.extend((f"file '{path.name}'", f"duration {max(0.001, frame_duration):.6f}"))
    lines.append(f"file '{frames[-1][0].name}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", listing.name, "-t", f"{duration:.3f}", "-vf", f"fps={fps},format=yuv420p",
          "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-r", str(fps),
          "-video_track_timescale", str(fps * 1000), out.name], cwd=cwd)


def scene_dir(pid: str, sid: str) -> Path:
    return project.project_dir(pid) / "scenes" / sid


def render_scene(proj: dict, scene: dict, idx: int, total: int) -> tuple[Path, float]:
    pid, st = proj["id"], proj["settings"]
    size = config.frame_size(st["resolution"], st["aspect"])
    fps = int(st["fps"])
    sdir = scene_dir(pid, scene["scene_id"])
    sdir.mkdir(parents=True, exist_ok=True)

    lang = scene.get("language") or st["language"]
    sentences = split_sentences(scene["narration"])
    if not sentences:
        raise RenderError(f"{scene['scene_id']}: narration is empty")
    cues, dur, used = tts.build_scene_audio(sentences, lang, st, project.project_dir(pid) / "cache" / "tts",
                                            sdir / "narration.wav")
    if used == {"silent"}:
        log.warning("%s: SILENT audio (no TTS engine)", scene["scene_id"])
    (sdir / "cues.json").write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")

    vis = scene.get("visual", {})
    if vis.get("type") == "pdf_page":
        pdf = project.project_dir(pid) / vis.get("pdf", "source/book.pdf")
        if not pdf.exists():
            raise RenderError(f"{scene['scene_id']}: PDF not found: {pdf}")
        visuals.pdf_page_card(scene, pdf, size, st["theme"], sdir / "bg.png")
        video_input = ["-framerate", str(fps), "-loop", "1", "-i", "bg.png"]
    else:
        frames = visuals.animated_title_card(scene, idx, total, proj["title"], size, st["theme"], cues, sdir)
        diagram_video = sdir / "diagram.mp4"
        _encode_diagram_frames(frames, diagram_video, fps, dur, sdir)
        video_input = ["-i", diagram_video.name]

    sub = st["subtitles"]
    use_subs = sub.get("enabled", True) and scene.get("subtitle", {}).get("enabled", True)
    move = "none" if vis.get("type") != "pdf_page" else scene.get("camera", {}).get("move", "slow_zoom_in")
    vf = [_camera_filter(move, dur, fps, size)]
    if use_subs:
        subtitles.write_ass(cues, sdir / "subs.ass", size[0], size[1], sub)
        fontsdir = ""
        try:
            if any(config.FONTS_DIR.glob("*.[to]tf")):
                fontsdir = ":fontsdir=" + os.path.relpath(config.FONTS_DIR, sdir).replace("\\", "/")
        except ValueError:
            pass  # different drive on Windows: fall back to system fonts
        vf.append(f"ass=subs.ass{fontsdir}")
    vf.append("format=yuv420p")

    tmp = sdir / "clip.tmp.mp4"
    cmd = [ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *video_input,
           "-i", "narration.wav", "-vf", ",".join(vf), "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-bf", "0", "-pix_fmt", "yuv420p", "-r", str(fps),
           "-video_track_timescale", str(fps * 1000),
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "clip.tmp.mp4"]
    _run(cmd, cwd=sdir)
    out = sdir / "clip.mp4"
    os.replace(tmp, out)
    return out, probe_duration(out)


def _heartbeat(pid: str, stop: threading.Event):
    while not stop.wait(10):
        try:
            _write_progress(pid)
        except OSError:
            pass


def render_project(pid: str, force: bool = False, only: list[str] | None = None) -> dict:
    proj = project.load(pid)
    scenes = proj["scenes"]
    if not scenes:
        raise RenderError("Project has no scenes. Add a script and segment it first.")
    logdir = project.project_dir(pid) / "logs"
    logdir.mkdir(exist_ok=True)
    fh = logging.FileHandler(logdir / "render.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger("aistudio").addHandler(fh)
    stop = threading.Event()
    jobs.reset_running(pid)
    _write_progress(pid, status="running", done=0, total=len(scenes), current="", failed=[], message="")
    threading.Thread(target=_heartbeat, args=(pid, stop), daemon=True).start()
    t0 = time.time()
    failed, clips, durations, done = [], [], [], 0
    try:
        ffmpeg()
        for i, sc in enumerate(scenes, 1):
            sid = sc["scene_id"]
            h = scene_hash(sc, proj["settings"], proj["title"])
            clip = scene_dir(pid, sid) / "clip.mp4"
            job = jobs.get(pid, sid)
            skip = (not force and (only is None or sid not in only) and job and job["status"] == "done"
                    and job["hash"] == h and clip.exists())
            if only and sid not in only and not skip and clip.exists() and job and job["status"] == "done":
                skip = True
            if skip:
                log.info("%s cached - skipped", sid)
                clips.append(clip)
                durations.append(job["duration"])
            else:
                _write_progress(pid, current=sid, message=f"Rendering {sid} ({i}/{len(scenes)})")
                jobs.set_status(pid, sid, h, "running")
                s0 = time.time()
                try:
                    clip, d = render_scene(proj, sc, i, len(scenes))
                    jobs.set_status(pid, sid, h, "done", "", d)
                    clips.append(clip)
                    durations.append(d)
                    log.info("%s rendered in %.1fs (clip %.1fs)", sid, time.time() - s0, d)
                except Exception as e:  # keep going so one bad scene does not block the rest
                    jobs.set_status(pid, sid, h, "failed", str(e))
                    failed.append({"scene_id": sid, "error": str(e)})
                    log.error("%s FAILED: %s\n%s", sid, e, traceback.format_exc())
            done += 1
            _write_progress(pid, done=done, failed=failed)
        if failed:
            _write_progress(pid, status="failed", message=f"{len(failed)} scene(s) failed. Fix and render again; finished scenes are kept.")
            return {"ok": False, "failed": failed}
        report = assemble(proj, clips, durations)
        _write_progress(pid, status="done", message="Finished", seconds=round(time.time() - t0, 1))
        return {"ok": True, **report}
    except Exception as e:
        log.error("Render aborted: %s\n%s", e, traceback.format_exc())
        _write_progress(pid, status="failed", message=str(e))
        raise
    finally:
        stop.set()
        logging.getLogger("aistudio").removeHandler(fh)
        fh.close()


def assemble(proj: dict, clips: list[Path], durations: list[float]) -> dict:
    pid, st = proj["id"], proj["settings"]
    rdir = project.project_dir(pid) / "renders"
    rdir.mkdir(exist_ok=True)
    listing = rdir / "clips.txt"
    listing.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    joined = rdir / "joined.tmp.mp4"
    _run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
          "-i", str(listing), "-c", "copy", str(joined)])

    final = rdir / "final.mp4"
    music = st.get("music", {}).get("path")
    if music and Path(music).exists():
        vol = float(st["music"].get("volume", 0.15))
        fc = ("[0:a]asplit=2[n1][n2];[1:a]volume=%s[m];[m][n1]sidechaincompress=threshold=0.05:ratio=8:"
              "attack=20:release=400[d];[n2][d]amix=inputs=2:duration=first:dropout_transition=0,"
              "loudnorm=I=-16:TP=-1.5:LRA=11[a]" % vol)
        _run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-stream_loop", "-1",
              "-i", str(music), "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
              "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)])
        joined.unlink(missing_ok=True)
    else:
        _run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-c", "copy",
              "-movflags", "+faststart", str(final)])
        joined.unlink(missing_ok=True)

    # Cumulative SRT from per-scene cues
    cues, offset = [], 0.0
    for c, d in zip(clips, durations):
        for cue in json.loads((c.parent / "cues.json").read_text(encoding="utf-8")):
            cues.append({"start": cue["start"] + offset, "end": cue["end"] + offset, "text": cue["text"]})
        offset += d
    subtitles.write_srt(cues, rdir / "final.srt")

    # Validation: duration match + full decode test
    final_d = probe_duration(final)
    expected = sum(durations)
    drift = abs(final_d - expected)
    dec = subprocess.run([ffmpeg(), "-v", "error", "-i", str(final), "-fps_mode", "passthrough", "-f", "null", "-"], capture_output=True, text=True)
    report = {"final": str(final), "duration_sec": round(final_d, 2), "expected_sec": round(expected, 2),
              "drift_sec": round(drift, 3), "decode_errors": dec.stderr.strip()[-500:],
              "size_mb": round(final.stat().st_size / 1e6, 2), "srt": str(rdir / "final.srt")}
    report["valid"] = drift < 0.5 and not report["decode_errors"]
    (rdir / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["valid"]:
        log.warning("Validation problem: %s", report)
    return report
