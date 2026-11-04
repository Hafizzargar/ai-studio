"""Offline text-to-speech backends: Piper, Windows SAPI, espeak-ng, and a silent test backend."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import wave
from pathlib import Path

from . import config

log = logging.getLogger("aistudio.tts")
RATE, CHANNELS, WIDTH = 22050, 1, 2
_warned_silent = False


class TTSError(RuntimeError):
    pass


def piper_voices() -> list[str]:
    if not config.VOICES_DIR.exists():
        return []
    return sorted(p.stem for p in config.VOICES_DIR.glob("*.onnx"))


def available_backends() -> dict:
    return {
        "piper": bool(config.find_exe("piper") and piper_voices()),
        "sapi": bool(config.IS_WINDOWS and shutil.which("powershell")),
        "espeak": bool(shutil.which("espeak-ng") or shutil.which("espeak")),
        "silent": True,
    }


def choose_backend(pref: str = "auto") -> str:
    av = available_backends()
    if pref and pref != "auto":
        if not av.get(pref):
            raise TTSError(f"TTS backend '{pref}' is not available on this machine. Available: "
                           f"{[k for k, v in av.items() if v]}")
        return pref
    for b in ("piper", "sapi", "espeak"):
        if av[b]:
            return b
    global _warned_silent
    if not _warned_silent:
        log.warning("No real TTS engine found - using SILENT backend (video will have no speech). "
                    "Install Piper (see README) or run on Windows for SAPI.")
        _warned_silent = True
    return "silent"


def check_language(lang: str, backend: str, voice: str) -> None:
    if lang == "ur-roman":
        raise TTSError("Roman Urdu cannot be sent to TTS directly. Convert it to Urdu script, review the "
                       "text, then set the language to 'ur'.")
    if lang == "ur" and backend == "piper" and not voice.lower().startswith("ur"):
        raise TTSError("Urdu narration needs an Urdu voice model in vendor/voices (file name starting with 'ur'). "
                       "Without one, pronunciation would be wrong. Use English narration with Urdu subtitles instead.")


def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, check=True, capture_output=True, **kw)
    except subprocess.CalledProcessError as e:
        raise TTSError(f"{Path(cmd[0]).name} failed: {(e.stderr or b'').decode('utf-8', 'replace')[-400:]}") from e


def _piper(text: str, out: Path, voice: str, speed: float) -> None:
    exe = config.find_exe("piper")
    model = config.VOICES_DIR / f"{voice}.onnx" if voice else None
    if model is None or not model.exists():
        voices = piper_voices()
        if not voices:
            raise TTSError("No Piper voice (.onnx) found in vendor/voices")
        model = config.VOICES_DIR / f"{voices[0]}.onnx"
    _run([exe, "--model", str(model), "--output_file", str(out), "--length_scale", f"{1.0 / max(speed, 0.3):.3f}"],
         input=text.encode("utf-8"))


def _sapi(text: str, out: Path, voice: str, speed: float) -> None:
    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    name = voice.split(":", 1)[1] if voice.startswith("sapi:") else ""
    select = f"$s.SelectVoice('{name.replace(chr(39), chr(39) * 2)}')" if name else ""
    rate = max(-10, min(10, round((speed - 1.0) * 10)))
    q = lambda p: str(p).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f"{select}\n$s.Rate = {rate}\n$s.SetOutputToWaveFile('{q(out)}')\n"
        f"$s.Speak([System.IO.File]::ReadAllText('{q(txt)}', [System.Text.Encoding]::UTF8))\n$s.Dispose()\n"
    )
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    try:
        _run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc])
    finally:
        txt.unlink(missing_ok=True)


def _espeak(text: str, out: Path, voice: str, speed: float) -> None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    cmd = [exe, "-w", str(out), "-s", str(int(165 * speed))]
    if voice:
        cmd += ["-v", voice]
    _run(cmd + [text])


def _silent(text: str, out: Path, voice: str, speed: float) -> None:
    secs = max(0.8, len(text.split()) / (2.6 * speed))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS), w.setsampwidth(WIDTH), w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * int(RATE * secs))


_BACKENDS = {"piper": _piper, "sapi": _sapi, "espeak": _espeak, "silent": _silent}


def _normalize(src: Path, dst: Path) -> None:
    """Make every sentence WAV 22050 Hz / mono / 16-bit so they can be joined safely."""
    try:
        with wave.open(str(src)) as w:
            ok = (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, CHANNELS, WIDTH)
    except wave.Error:
        ok = False
    if ok:
        os.replace(src, dst)
        return
    _run([config.find_exe("ffmpeg") or "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
          "-ar", str(RATE), "-ac", str(CHANNELS), "-c:a", "pcm_s16le", str(dst)])
    src.unlink(missing_ok=True)


def synth_sentence(text: str, lang: str, settings: dict, cache_dir: Path) -> tuple[Path, str]:
    backend = choose_backend(settings.get("tts_backend", "auto"))
    voice = settings.get("voice", "") or ""
    speed = float(settings.get("speed", 1.0))
    check_language(lang, backend, voice)
    key = hashlib.sha1(json.dumps([backend, voice, speed, lang, text], ensure_ascii=False).encode()).hexdigest()[:20]
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{key}.wav"
    if out.exists() and out.stat().st_size > 1000:
        return out, backend
    tmp = cache_dir / f"{key}.tmp.wav"
    _BACKENDS[backend](text, tmp, voice, speed)
    if not tmp.exists() or tmp.stat().st_size < 100:
        raise TTSError(f"{backend} produced no audio for: {text[:60]!r}")
    _normalize(tmp, out)
    return out, backend


def build_scene_audio(sentences: list[str], lang: str, settings: dict, cache_dir: Path, out_wav: Path):
    """Synthesize each sentence, join with pauses. Returns (cues, total_seconds, backends_used).
    Cue times come from real audio lengths, so sentence-level subtitle sync is exact."""
    lead, tail = 0.15, 0.5
    pause = float(settings.get("pause_sec", 0.35))
    sil = lambda s: b"\x00\x00" * int(RATE * s)
    chunks, cues, used = [sil(lead)], [], set()
    t = lead
    for i, sent in enumerate(sentences):
        wav, backend = synth_sentence(sent, lang, settings, cache_dir)
        used.add(backend)
        with wave.open(str(wav)) as w:
            raw, d = w.readframes(w.getnframes()), w.getnframes() / w.getframerate()
        cues.append({"start": round(t, 3), "end": round(t + d, 3), "text": sent})
        chunks.append(raw)
        gap = pause if i < len(sentences) - 1 else tail
        chunks.append(sil(gap))
        t += d + gap
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(CHANNELS), w.setsampwidth(WIDTH), w.setframerate(RATE)
        w.writeframes(b"".join(chunks))
    return cues, t, used
