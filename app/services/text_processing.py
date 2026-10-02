"""
Arabic text cleaning and chunking, applied before embedding.

Cleaning:
  - turn Arabic presentation forms from PDFs (ﻻ ﺑ …) into normal letters
  - remove diacritics (harakat) and tatweel (kashida ـــ)
  - remove invisible direction/zero-width marks left by PDF extraction
  - normalize whitespace and repeated blank lines

Note: alef forms are not normalized — the stored text is also what users see.

Chunking:
  1. split on paragraphs first; a short paragraph (e.g. one hadith) stays one chunk
  2. a paragraph longer than the maximum is split on sentence, then clause, then word boundaries
  3. consecutive pieces of a split paragraph overlap slightly so meaning isn't cut at the edges
  4. extraction leftovers are dropped (page numbers, stray symbols) — anything with fewer
     than two words or fewer than MIN_LETTERS letters. Short hadiths are kept:
     "الدين النصيحة" is two words and 12 letters. Garbled OCR (Arabic mixed with stray
     Latin letters, e.g. "BE gall") is dropped too, so it never reaches the database.
"""

import re

from app.services.extraction import looks_garbled, normalize_forms

ARABIC_DIACRITICS = re.compile(
    r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed]"
)
TATWEEL = re.compile(r"\u0640")
INVISIBLE_MARKS = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
INLINE_SPACES = re.compile(r"[ \t\u00a0]+")
BLANK_LINES = re.compile(r"\n{3,}")

PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟…])\s+")
CLAUSE_SPLIT = re.compile(r"(?<=[،؛,;:])\s+")

MAX_CHARS = 400
MIN_LETTERS = 8
OVERLAP_CHARS = 60


def clean(text: str, strip_diacritics: bool = True) -> str:
    """Clean Arabic text extracted from a raw source."""
    text = normalize_forms(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = INVISIBLE_MARKS.sub("", text)
    if strip_diacritics:
        text = ARABIC_DIACRITICS.sub("", text)
    text = TATWEEL.sub("", text)
    lines = (INLINE_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def chunk(
    text: str,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
    min_letters: int = MIN_LETTERS,
) -> list[str]:
    """Split a long text into chunks of at most max_chars characters."""
    chunks: list[str] = []
    for paragraph in PARAGRAPH_SPLIT.split(text):
        paragraph = " ".join(paragraph.split())  # join wrapped lines
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
        else:
            chunks.extend(_split_paragraph(paragraph, max_chars, overlap))
    return [c for c in chunks if _is_meaningful(c, min_letters)]


def _is_meaningful(text: str, min_letters: int) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    return len(text.split()) >= 2 and letters >= min_letters and not looks_garbled(text)


def _split_paragraph(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    units: list[str] = []
    for sentence in SENTENCE_SPLIT.split(paragraph):
        units.extend(_split_unit(sentence.strip(), max_chars))

    windows: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        candidate = f"{current} {unit}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            windows.append(current)
        tail = _tail(current, overlap)
        current = f"{tail} {unit}" if tail and len(tail) + 1 + len(unit) <= max_chars else unit
    if current:
        windows.append(current)
    return windows


def _split_unit(text: str, max_chars: int) -> list[str]:
    """Break a single over-long sentence on clauses, then on words."""
    if len(text) <= max_chars:
        return [text]

    clauses = [c.strip() for c in CLAUSE_SPLIT.split(text) if c.strip()]
    if len(clauses) > 1:
        return [piece for clause in clauses for piece in _split_unit(clause, max_chars)]

    pieces: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_chars:  # a single "word" longer than a chunk
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:max_chars])
            word = word[max_chars:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    """Last ~overlap characters of text, starting at a word boundary."""
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    if len(text) > overlap and " " in tail:
        tail = tail.split(" ", 1)[1]
    return tail.strip()
