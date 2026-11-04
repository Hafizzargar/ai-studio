# Architecture

```
Browser UI (ui/index.html)
      |  HTTP (localhost only)
FastAPI (aistudio/server.py)  -- thin routes
      |-- aistudio/project.py   atomic save, backups, migration
      |-- aistudio/scenes.py    sentence split, scene segmentation, content hash
      |-- aistudio/pdfio.py     PyMuPDF analysis, extractive draft, highlight rects
      |-- aistudio/tts.py       Piper | SAPI | espeak | silent, per-sentence cache
      |-- aistudio/subtitles.py SRT + ASS
      |-- aistudio/visuals.py   Pillow concept diagrams / water-cycle motion frames / PDF page
      |-- aistudio/jobs.py      SQLite job state per project
      `-- aistudio/render.py    per-scene FFmpeg, concat, music ducking, validation
Render runs as a separate process: python -m engine.cli render <id>
```

Flow: script/PDF -> scenes (project.json) -> per scene: TTS per sentence -> narration.wav + cues -> generated concept diagram, animated water-cycle frames, or PDF page background PNG
-> FFmpeg (looping animation, zoompan, burned ASS + AAC) -> clip.mp4 -> timestamp-normalized concat encode -> optional music mix -> final.mp4 + final.srt -> validation.

Design rules: renderer is independent of the UI; one scene = one job; clip written to a temp name then renamed;
scene clips use matching codecs and formats, then final assembly re-encodes at the project frame rate to normalize
timestamps across scene boundaries; no B-frames keep per-scene timestamps straightforward.

Planned extension points: `visual.type` (add `svg_scene`, `chart`, `map`), a frame-pipe renderer using resvg for animated scenes,
`characters` list on each scene (already in the schema).
