"""Render the original three-friends water-cycle cartoon with Blender."""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aistudio import config, render, subtitles, tts
from aistudio.mascot import parse_dialogue_script


FPS = 24
SPEAKER_SPEEDS = {"Pip": 1.0, "Maya": 1.08, "Ravi": 0.82}


def _find_blender() -> str | None:
    found = shutil.which("blender")
    if found:
        return found
    roots = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "Blender Foundation",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        candidates = sorted(root.glob("Blender */blender.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    return None


def _voice_assignments(backend: str) -> dict[str, str]:
    if backend != "sapi":
        return {speaker: "" for speaker in SPEAKER_SPEEDS}

    installed = tts.sapi_voices()
    if not installed:
        return {speaker: "" for speaker in SPEAKER_SPEEDS}

    david = next((voice for voice in installed if "david" in voice.casefold()), installed[0])
    zira = next((voice for voice in installed if "zira" in voice.casefold()), installed[-1])
    return {"Pip": f"sapi:{david}", "Maya": f"sapi:{zira}", "Ravi": f"sapi:{david}"}


def _build_audio(lines: list[dict], audio_path: Path, cache_dir: Path,
                 backend: str, voices: dict[str, str]) -> tuple[list[dict], float, set[str]]:
    lead_frames = round(tts.RATE * 0.15)
    pause_frames = round(tts.RATE * 0.3)
    tail_frames = round(tts.RATE * 0.65)

    def silence(frame_count: int) -> bytes:
        return b"\x00" * (frame_count * tts.WIDTH)

    chunks = [silence(lead_frames)]
    cursor = lead_frames
    cues = []
    backends = set()
    for index, line in enumerate(lines):
        settings = {
            "tts_backend": backend,
            "voice": voices[line["speaker"]],
            "speed": SPEAKER_SPEEDS[line["speaker"]],
        }
        wav_path, used_backend = tts.synth_sentence(
            line["text"], "en", settings, cache_dir
        )
        backends.add(used_backend)
        with wave.open(str(wav_path), "rb") as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (
                tts.RATE, tts.CHANNELS, tts.WIDTH
            ):
                raise tts.TTSError(f"Unexpected audio format for {line['speaker']}'s dialogue")
            spoken_frames = wav.getnframes()
            spoken_audio = wav.readframes(spoken_frames)

        start = cursor / tts.RATE
        cursor += spoken_frames
        end = cursor / tts.RATE
        cues.append({**line, "start": start, "end": end})
        chunks.extend((spoken_audio, silence(
            pause_frames if index < len(lines) - 1 else tail_frames
        )))
        cursor += pause_frames if index < len(lines) - 1 else tail_frames

    frame_count = math.ceil(cursor * FPS / tts.RATE)
    target_audio_frames = round(frame_count * tts.RATE / FPS)
    chunks.append(silence(target_audio_frames - cursor))
    with wave.open(str(audio_path), "wb") as wav:
        wav.setnchannels(tts.CHANNELS)
        wav.setsampwidth(tts.WIDTH)
        wav.setframerate(tts.RATE)
        wav.writeframes(b"".join(chunks))
    return cues, frame_count / FPS, backends


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "demos" / "three-friends-water-cycle-3d.mp4",
        help="MP4 output path",
    )
    args = parser.parse_args()

    blender = _find_blender()
    if not blender:
        raise SystemExit(
            "Blender was not found. Install Blender 4.0 or newer, then rerun this script."
        )
    script_path = ROOT / "demos" / "three-friends-water-cycle-3d.txt"
    lines = parse_dialogue_script(script_path.read_text(encoding="utf-8"))
    backend = tts.choose_backend("auto")
    voices = _voice_assignments(backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="three-friends-3d-") as temp:
        work = Path(temp)
        audio = work / "dialogue.wav"
        cues, duration, used = _build_audio(
            lines, audio, work / "tts-cache", backend, voices
        )
        silent_video = work / "cartoon-3d.mp4"
        frame_prefix = work / "frame_"
        render_config = work / "render.json"
        render_config.write_text(json.dumps({
            "output": str(frame_prefix),
            "duration": duration,
            "fps": FPS,
            "cues": cues,
        }, ensure_ascii=False), encoding="utf-8")
        blender_script = Path(__file__).with_name("blender_render_three_friends.py")
        result = subprocess.run(
            [blender, "--background", "--python", str(blender_script),
             "--", str(render_config)],
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Blender exited with status {result.returncode}")

        ffmpeg = config.find_exe("ffmpeg") or "ffmpeg"
        render._run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-framerate", str(FPS), "-start_number", "1",
            "-i", str(frame_prefix) + "%04d.png",
            "-frames:v", str(math.ceil(duration * FPS)),
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(silent_video),
        ])
        render._run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent_video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
            str(args.output.resolve()),
        ])

    subtitle_path = args.output.with_suffix(".srt")
    subtitles.write_srt([
        {**cue, "text": f"{cue['speaker']}: {cue['text']}"}
        for cue in cues
    ], subtitle_path)
    voice_summary = ", ".join(
        f"{speaker}: {voices[speaker].removeprefix('sapi:') or backend}"
        for speaker in SPEAKER_SPEEDS
    )
    print(f"Created {args.output.resolve()} ({duration:.1f}s; TTS: {', '.join(sorted(used))})")
    print(f"Created {subtitle_path.resolve()}")
    print(f"Available voice assignments: {voice_summary}")


if __name__ == "__main__":
    main()
