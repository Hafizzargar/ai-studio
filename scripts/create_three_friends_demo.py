"""Create a narrated water-cycle video with three original characters."""
from __future__ import annotations

import argparse
import math
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aistudio import config, render, subtitles, tts
from aistudio.mascot import animated_dialogue_demo, parse_dialogue_script


FPS = 24
SPEAKER_SPEEDS = {"Pip": 1.0, "Maya": 1.08, "Ravi": 0.82}


def _voice_assignments(backend: str) -> dict[str, str]:
    if backend != "sapi":
        return {speaker: "" for speaker in SPEAKER_SPEEDS}

    installed = tts.sapi_voices()
    if not installed:
        return {speaker: "" for speaker in SPEAKER_SPEEDS}

    david = next((voice for voice in installed if "david" in voice.casefold()), installed[0])
    zira = next((voice for voice in installed if "zira" in voice.casefold()), installed[-1])
    return {"Pip": f"sapi:{david}", "Maya": f"sapi:{zira}", "Ravi": f"sapi:{david}"}


def _synthesize_dialogue(lines: list[dict], audio_path: Path, cache_dir: Path,
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
        cues.append({
            **line,
            "start": start,
            "end": end,
            "text": line["text"],
        })
        chunks.append(spoken_audio)
        gap = pause_frames if index < len(lines) - 1 else tail_frames
        chunks.append(silence(gap))
        cursor += gap

    video_frames = math.ceil(cursor * FPS / tts.RATE)
    target_audio_frames = round(video_frames * tts.RATE / FPS)
    chunks.append(silence(target_audio_frames - cursor))
    with wave.open(str(audio_path), "wb") as wav:
        wav.setnchannels(tts.CHANNELS)
        wav.setsampwidth(tts.WIDTH)
        wav.setframerate(tts.RATE)
        wav.writeframes(b"".join(chunks))
    return cues, video_frames / FPS, backends


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "demos" / "three-friends-water-cycle.mp4",
        help="MP4 output path",
    )
    args = parser.parse_args()

    script_path = ROOT / "demos" / "three-friends-water-cycle.txt"
    lines = parse_dialogue_script(script_path.read_text(encoding="utf-8"))
    backend = tts.choose_backend("auto")
    voices = _voice_assignments(backend)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="three-friends-demo-") as temp:
        work = Path(temp)
        audio = work / "dialogue.wav"
        cues, duration, used = _synthesize_dialogue(
            lines, audio, work / "tts-cache", backend, voices
        )
        frames = animated_dialogue_demo(cues, work, (1280, 720), FPS, duration=duration)
        silent_video = work / "dialogue-video.mp4"
        render._encode_diagram_frames(frames, silent_video, FPS, duration, work)
        ffmpeg = config.find_exe("ffmpeg") or "ffmpeg"
        render._run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(silent_video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
            str(args.output.resolve()),
        ])

    subtitle_path = args.output.with_suffix(".srt")
    subtitle_cues = [
        {**cue, "text": f"{cue['speaker']}: {cue['text']}"}
        for cue in cues
    ]
    subtitles.write_srt(subtitle_cues, subtitle_path)
    voice_summary = ", ".join(
        f"{speaker}: {voices[speaker].removeprefix('sapi:') or backend}"
        for speaker in SPEAKER_SPEEDS
    )
    print(f"Created {args.output.resolve()} ({duration:.1f}s; TTS: {', '.join(sorted(used))})")
    print(f"Created {subtitle_path.resolve()}")
    print(f"Available voice assignments: {voice_summary}")


if __name__ == "__main__":
    main()
