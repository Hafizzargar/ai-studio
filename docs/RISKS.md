# Technical risks and limitations

| Risk | Impact | Mitigation |
|---|---|---|
| Urdu TTS quality and licence | High | Test candidate voices first. Fallback: English narration with Urdu subtitles |
| Roman Urdu pronunciation | High | Blocked until converted to Urdu script and reviewed by a person |
| Windows-specific behaviour (fonts, paths, SAPI) | Medium | Test on target PC; run `doctor`; paths handled with pathlib; fonts folder supported |
| PyMuPDF AGPL licence | Medium | Fine for personal use; replace with pypdfium2 or buy a licence before distributing |
| Highlight matching on re-worded scripts | Medium | Exact search first, shorter phrase second; manual correction UI planned |
| Long render time (40 min) | Medium | Scene cache, resume, background process; measure on target PC |
| Scanned PDFs | Medium | Detected and flagged; Tesseract OCR planned |
| Disk use of intermediate files | Low | Delete `projects/<id>/scenes` and `cache` after final export |
