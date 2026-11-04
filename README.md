# AI Studio (Phase 1 prototype)

Local-first video production engine for Windows 11 (CPU only, no paid services).
Script or PDF in, narrated MP4 with burned-in subtitles and an SRT file out.

## What works in this version (Phase 1)

- Projects: create, autosave, reopen, crash recovery (atomic save plus 5 rolling backups).
- Script editor in a local web UI. `# Heading` lines start a scene; long paragraphs are split automatically.
- PDF upload: headings, definitions, years, scanned-page detection, extractive script draft with page references.
- Scenes can use a fixed-position concept map or a moving water-cycle illustration. The water-cycle template moves vapour, cloud droplets, rain and collection water, while waves move and the sun pulses; it is motion graphics, not a general-purpose animation engine or morphing cloud simulation. It emphasizes the process named by the scene heading. PDF scenes can show the original PDF page with narrated sentences highlighted (the PDF is rendered as an image, never changed).
- Offline voice: Piper (best), Windows built-in voices (SAPI, zero install, selectable with a voice preview), espeak-ng, or a silent test mode. English and Roman Urdu are selectable; Roman Urdu is read as typed by a Windows voice and may be pronounced approximately.
- Exact sentence-level subtitles (SRT export and styled ASS burn-in).
- Scene-by-scene rendering with checkpoints. Re-rendering only redoes scenes you changed. A failed scene never loses the others. Closing the app mid-render and rendering again resumes.
- Optional background music with automatic ducking under narration and loudness normalisation.
- Output checks: audio/video drift, full decode test. Exports 720p/1080p, 16:9, 9:16, 1:1, 24/25/30 fps, H.264 + AAC.

Not in Phase 1: characters, animated maps, word-level subtitle timing, Urdu voice (see Limits). Generated diagrams are simple text-based concept flows, not hand-drawn illustrations.

## Install on Windows 11

1. Install Python 3.11 or 3.12 from python.org (tick "Add python.exe to PATH").
2. Double-click `install_windows.bat`. It creates `.venv` and installs the libraries.
3. Get the tools (either run `powershell -ExecutionPolicy Bypass -File scripts\download_tools.ps1`, or do it by hand):
   - FFmpeg: put `ffmpeg.exe` and `ffprobe.exe` in `vendor\`.
   - Piper (optional, best English voice): unzip into `vendor\piper\` and put voice files (`xxx.onnx` and `xxx.onnx.json`) into `vendor\voices\`.
   - If you skip Piper, the app uses the Windows built-in voices automatically.
4. Run `python -m engine.cli doctor` (inside the venv) to see what was found.
5. Double-click `run_ui.bat`. The browser opens at http://127.0.0.1:8765.

Fonts: for Urdu or consistent styling, copy OFL-licensed `.ttf` files (for example Noto Naskh Arabic) into `assets\fonts\`. See `assets\fonts\README.md`.

## Command line

```
python -m engine.cli doctor
python -m engine.cli quick samples\sample_script.txt --title "Water Cycle"
python -m engine.cli render <project_id>            # resumes, skips finished scenes
python -m engine.cli render <project_id> --scene s003
python -m engine.cli render <project_id> --force
python -m engine.cli pdf-analyze book.pdf
python -m pytest                                      # run the tests
```

Projects live in `projects\<id>\`: `project.json`, `source\` (script, original PDF), `scenes\<id>\` (audio, clip, cues), `renders\final.mp4`, `renders\final.srt`, `logs\render.log`.
Set `AISTUDIO_PROJECTS` to store projects somewhere else (for example another drive).
In the scene list, choose **Moving water cycle** in the Visual column to use the animated illustration. It is a hand-drawn 2D motion-graphics template, not AI-generated footage; choose Concept map for the existing diagram style.
For a complete starter lesson, choose **Create water-cycle lesson** when creating a project. It loads the six-scene English sample and selects the moving illustration for every scene; narration, visuals, and subtitles can then be edited before rendering.

## Project file (project.json)

Each scene: `scene_id, heading, narration, language, visual {type: title_card | water_cycle | pdf_page, pdf, page}, camera {move: slow_zoom_in | slow_zoom_out | none}, subtitle {enabled}, source_refs, dramatized, status`. The renderer hashes everything that affects the picture or sound, so unchanged scenes are never re-rendered. The UI is only an editor for this file.

## Limits you should know about

- Tested here: Windows, Python 3.11, FFmpeg 8.1, and Windows SAPI; the six-scene water-cycle lesson passed its decode and audio/video drift checks. Automated tests: 23 passed. Piper and a 16 GB CPU-only PC have not been tested.
- Urdu-script narration needs a compatible Urdu voice. Without one the app refuses to narrate Urdu (to avoid wrong pronunciation). Roman Urdu uses a Windows voice and may be mispronounced. Urdu subtitles use libass and need an Arabic-script font. Title cards use Pillow; Urdu shaping there needs Pillow built with raqm, otherwise use English headings.
- Scanned PDFs are detected but OCR is not included yet.
- Highlights are per scene (all narrated sentences matched on the page), not timed per sentence yet. Matching is exact-text search, so heavily re-worded scripts will not highlight.
- Rendering speed on the test machine used for development was roughly 0.5 s of CPU per second of video for title-card scenes. Animated character scenes will be slower.
- Diagram keyword highlights use estimated word positions within sentence-level speech cues; they are not phoneme-aligned, so timing can be approximate.
- Licences to check before distributing: PyMuPDF (AGPL or commercial), your FFmpeg build (LGPL/GPL), each Piper voice, any music or fonts. Newer Piper releases may use a different licence from older ones.

## Next phases

Phase 2: timed sentence highlights, OCR, charts/diagrams. Phase 3: SVG character rigs. Phase 4: history studio (maps, timelines, costumes). See `docs\ARCHITECTURE.md` and `docs\RISKS.md`.
