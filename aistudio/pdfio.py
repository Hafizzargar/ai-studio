"""PDF intelligence: structure detection, extractive script drafting, page rendering, highlight rectangles.
The original PDF is never modified."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pymupdf

from .scenes import new_scene, split_sentences

_DEF_RE = re.compile(r"\b(is defined as|refers to|is called|are called|means|is known as)\b", re.I)
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


def _body_size(doc) -> float:
    sizes: Counter = Counter()
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") == 0:
                for ln in b["lines"]:
                    for sp in ln["spans"]:
                        sizes[round(sp["size"], 1)] += len(sp["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 11.0


def _blocks(doc, body: float):
    """Yield (page_no, kind, text, size) in reading order. kind = 'heading' | 'body'."""
    for pno, page in enumerate(doc, 1):
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0 or not b["lines"]:
                continue
            spans = [sp for ln in b["lines"] for sp in ln["spans"] if sp["text"].strip()]
            if not spans:
                continue
            text = " ".join(" ".join(sp["text"].strip() for sp in ln["spans"]).strip() for ln in b["lines"]).strip()
            size = max(sp["size"] for sp in spans)
            bold = all(bool(sp["flags"] & 16) for sp in spans)
            is_head = len(text) <= 120 and re.search(r"[A-Za-z\u0600-\u06FF]", text) and (
                size >= body * 1.15 or (bold and size >= body * 0.98 and len(text.split()) <= 12))
            yield pno, "heading" if is_head else "body", text, round(size, 1)


def analyze_pdf(path: str | Path) -> dict:
    doc = pymupdf.open(str(path))
    body = _body_size(doc)
    heads, dates, defs, scanned = [], {}, [], []
    sizes = sorted({s for _, k, _, s in _blocks(doc, body) if k == "heading"}, reverse=True)
    level = {s: i + 1 for i, s in enumerate(sizes)}
    for pno, kind, text, size in _blocks(doc, body):
        if kind == "heading":
            heads.append({"page": pno, "text": text, "level": level.get(size, 1)})
        else:
            for sent in split_sentences(text):
                if _DEF_RE.search(sent) and len(sent) < 300:
                    defs.append({"page": pno, "text": sent})
            for y in _YEAR_RE.findall(text):
                dates.setdefault(y, set()).add(pno)
    for pno, page in enumerate(doc, 1):
        if len(page.get_text("text").strip()) < 30 and page.get_images():
            scanned.append(pno)
    title = (doc.metadata or {}).get("title") or (heads[0]["text"] if heads else Path(path).stem)
    return {
        "title": title, "page_count": len(doc), "body_font_size": body,
        "toc": doc.get_toc(), "headings": heads, "definitions": defs[:200],
        "years": {y: sorted(p) for y, p in sorted(dates.items())},
        "scanned_pages": scanned,
        "warnings": ([f"{len(scanned)} page(s) look scanned. OCR (Tesseract) is needed for text: {scanned[:10]}"]
                     if scanned else []),
    }


def draft_scenes(path: str | Path, language: str = "en", max_sentences: int = 4) -> list[dict]:
    """Extractive draft: per heading, keep definition sentences + the first few sentences.
    Every scene keeps its PDF page reference. The user must review before rendering."""
    doc = pymupdf.open(str(path))
    body = _body_size(doc)
    sections: list[dict] = []
    for pno, kind, text, _ in _blocks(doc, body):
        if kind == "heading":
            sections.append({"heading": text, "page": pno, "text": []})
        elif sections:
            sections[-1]["text"].append(text)
    scenes: list[dict] = []
    for sec in sections:
        sents = [s for s in split_sentences(" ".join(sec["text"])) if 30 <= len(s) <= 300]
        if not sents:
            continue
        pick = [s for s in sents if _DEF_RE.search(s)][:2]
        for s in sents:
            if len(pick) >= max_sentences:
                break
            if s not in pick:
                pick.append(s)
        pick.sort(key=sents.index)
        scenes.append(new_scene(
            len(scenes) + 1, sec["heading"], " ".join(pick), language,
            visual={"type": "pdf_page", "pdf": "source/book.pdf", "page": sec["page"]},
            source_refs=[{"type": "pdf", "page": sec["page"]}], status="draft"))
    return scenes


def find_highlights(page, sentences: list[str]) -> list:
    """Best-effort rectangles for each sentence (exact search, then a shorter phrase)."""
    rects = []
    for s in sentences:
        hits = page.search_for(s[:90])
        if not hits:
            words = s.split()
            for n in (8, 5):
                if len(words) >= n:
                    hits = page.search_for(" ".join(words[:n]))
                    if hits:
                        break
        rects.extend(hits)
    return rects
