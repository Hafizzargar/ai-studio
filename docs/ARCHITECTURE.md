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
      |-- aistudio/visuals.py   Pillow concept diagrams / PDF page + highlight overlay
      |-- aistudio/jobs.py      SQLite job state per project
      `-- aistudio/render.py    per-scene FFmpeg, concat, music ducking, validation
Render runs as a separate process: python -m engine.cli render <id>
```

Flow: script/PDF -> scenes (project.json) -> per scene: TTS per sentence -> narration.wav + cues -> generated concept diagram or PDF page background PNG
-> FFmpeg (zoompan + burned ASS + AAC) -> clip.mp4 -> concat (stream copy) -> optional music mix -> final.mp4 + final.srt -> validation.

Design rules: renderer is independent of the UI; one scene = one job; clip written to a temp name then renamed;
all clips share codec/size/fps/sample rate so concat can copy streams; no B-frames so timestamps stay clean at joins.

Planned extension points: `visual.type` (add `svg_scene`, `chart`, `map`), a frame-pipe renderer using resvg for animated scenes,
`characters` list on each scene (already in the schema).
