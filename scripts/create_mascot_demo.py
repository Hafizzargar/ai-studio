"""Render a short narrated demo of the original Pip guide character."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aistudio import config, render, subtitles, tts
from aistudio.mascot import animated_guide_demo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "demos" / "pip-guide-demo.mp4",
        help="MP4 output path",
    )
    args = parser.parse_args()
    sentences = [
        "Hello, I'm Pip, your friendly guide to big ideas.",
        "Let's follow water as it rises, gathers into clouds, and returns as rain.",
        "Where do you think the rain goes next?",
        "Great thinking, water returns to rivers and oceans.",
    ]
    backend = tts.choose_backend("auto")
    voice = "sapi:Microsoft Zira Desktop" if backend == "sapi" else ""
    settings = {"tts_backend": backend, "voice": voice, "speed": 1.0, "pause_sec": 0.3}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pip-guide-demo-") as temp:
        work = Path(temp)
        audio = work / "narration.wav"
        cues, duration, used = tts.build_scene_audio(
            sentences, "en", settings, work / "tts-cache", audio
        )
        fps = 24
        frames = animated_guide_demo(cues, work, (1280, 720), fps, duration=duration)
        silent_video = work / "guide-video.mp4"
        render._encode_diagram_frames(frames, silent_video, fps, duration, work)
        ffmpeg = config.find_exe("ffmpeg") or "ffmpeg"
        render._run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent_video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
            str(args.output.resolve()),
        ])
    subtitle_path = args.output.with_suffix(".srt")
    subtitles.write_srt(cues, subtitle_path)
    print(
        f"Created {args.output.resolve()} ({duration:.1f}s, TTS: {', '.join(sorted(used))})"
    )
    print(f"Created {subtitle_path.resolve()}")


if __name__ == "__main__":
    main()
