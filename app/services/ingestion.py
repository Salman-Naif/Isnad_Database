"""
Ingestion pipeline: file → text → clean → items → embeddings → ChromaDB (+ literal index).

Two kinds of input, and the difference between them is fundamental:

1) ingest_file()        — general books and files (PDF, Word, text, scans)
   They are chunked and indexed, but **without ruling or sanad** because they are unstructured.

2) ingest_structured()  — hadith collections: JSON or CSV, one record per hadith
   (Isnad's own JSON format — the Shamela editions are converted to it — a JSON collection per
   book, or CSV; see app/services/hadith_import.py).
   Each record carries: text, ruling, who ruled on it, sanad, topic, source.
   Only this path feeds the "ruling attribution" and "narrator list" features.
   A hadith gets two vectors when its text can be told apart from its chain of narrators:
   one for the whole narration, one for the hadith's own words (matn) — a visitor quotes the
   words, and the chain would otherwise dilute the match.

Every item's literal text also goes into the exact-quote index (app/services/text_index.py).

Large files are written in windows of WRITE_WINDOW items — embed, store, next — so memory
stays small whatever the file's size. Items are written under a new id generation; the
previous version of the file is removed only once the new one is complete, so a failed
re-upload leaves the previous version searchable. Re-uploading a file replaces it.
"""

import hashlib
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.schemas import HadithRecord
from app.services import sanad, text_index
from app.services.embeddings import EmbeddingService
from app.services.extraction import ExtractionError, Progress, extract_text
from app.services.hadith_import import COLLECTION_EXTENSIONS, read_collection, record_matn
from app.services.text_processing import chunk, clean
from app.services.vector_store import VectorStore

STRUCTURED_EXTENSIONS = COLLECTION_EXTENSIONS
WRITE_WINDOW = 1000  # items embedded and stored together


@dataclass
class IngestResult:
    source: str
    kind: str
    chunks: int
    characters: int
    ocr_pages: int = 0
    note: str | None = None  # e.g. OCR pages worth a human look


@dataclass
class Item:
    """One vector in the store: `embed` is what is embedded, `text` what is shown."""

    key: str
    embed: str
    text: str
    metadata: dict[str, Any]


def _no_progress(_: str) -> None:
    pass


def ingest_upload(
    data: bytes,
    filename: str,
    embedder: EmbeddingService,
    store: VectorStore,
    progress: Progress = _no_progress,
) -> IngestResult:
    """Route an uploaded file to the right pipeline by its extension."""
    if Path(filename).suffix.lower() in STRUCTURED_EXTENSIONS:
        return ingest_structured(data, filename, embedder, store, progress)
    return ingest_file(data, filename, embedder, store, progress)


def ingest_file(
    data: bytes,
    filename: str,
    embedder: EmbeddingService,
    store: VectorStore,
    progress: Progress = _no_progress,
) -> IngestResult:
    """Index a general document (PDF, Word, text or scanned image)."""
    settings = get_settings()
    source = Path(filename).name

    progress("قراءة الملف")
    extracted = extract_text(data, source, progress)
    progress("تقطيع النص")
    text = clean(extracted.text)
    chunks = chunk(
        text,
        max_chars=settings.chunk_max_chars,
        overlap=settings.chunk_overlap_chars,
        min_letters=settings.chunk_min_letters,
    )
    if not chunks:
        raise ExtractionError("لم يُعثر على نص مقروء في الملف")

    items = [
        Item(f"doc{i}", c, c, {"type": "document", "source": source, "chunk_index": i})
        for i, c in enumerate(chunks)
    ]
    _write(items, source, "doc", embedder, store, progress)
    return IngestResult(
        source, "document", len(chunks), len(text), extracted.ocr_pages, extracted.note
    )


def ingest_structured(
    data: bytes,
    filename: str,
    embedder: EmbeddingService,
    store: VectorStore,
    progress: Progress = _no_progress,
) -> IngestResult:
    """Index a hadith collection (JSON or CSV): one or two vectors per hadith."""
    source = Path(filename).name
    progress("قراءة الأحاديث")
    records = read_collection(data, source).records

    items: list[Item] = []
    for record in records:
        metadata = _hadith_metadata(record, source)
        # The original text (with diacritics) is stored for display; the cleaned text is
        # what gets embedded, matching how queries are cleaned.
        items.append(Item(record.id, clean(record.text), record.text, {**metadata, "part": "full"}))
        matn = record_matn(record)
        if matn:
            items.append(Item(f"{record.id}{text_index.MATN_SUFFIX}", clean(matn), record.text,
                              {**metadata, "part": "matn"}))
    _write(items, source, "hadith", embedder, store, progress)
    return IngestResult(
        source, "structured_hadith", len(records), sum(len(r.text) for r in records)
    )


def _write(
    items: list[Item],
    source: str,
    prefix: str,
    embedder: EmbeddingService,
    store: VectorStore,
    progress: Progress,
) -> None:
    """Embed and store the items window by window, then retire the file's previous version."""
    _check_free_space(items)
    previous = store.ids_of(source)
    # A new generation of ids per upload: the previous version stays untouched until the
    # new one is complete. Numbered per file, so two books' hadith 1 never collide.
    base = f"{prefix}-{_digest(source)}-{uuid.uuid4().hex[:8]}"
    written: list[str] = []
    try:
        for start in range(0, len(items), WRITE_WINDOW):
            window = items[start:start + WRITE_WINDOW]
            ids = [f"{base}-{item.key}" for item in window]
            vectors = embedder.encode([item.embed for item in window], _progress(progress, start, len(items)))
            written += ids
            # The text is stored once, with the narration (or chunk); a matn item shows it too.
            # Texts first: a search never finds a vector whose text isn't there yet.
            text_index.add([(i, source, item.text) for i, item in zip(ids, window, strict=True)
                            if item.metadata.get("part") != "matn"])
            store.upsert(ids=ids, embeddings=vectors, metadatas=[item.metadata for item in window])
    except BaseException:
        store.delete_ids(written)
        text_index.delete_ids(written)
        raise

    progress("الحفظ في قاعدة البيانات")
    store.delete_ids(previous)
    text_index.delete_ids(previous)


# Disk space one item takes: its vector in the index and in Chroma's database, its metadata,
# and its text with the literal index. Measured on Bukhari, Tirmidhi and Musnad Ahmad.
BYTES_PER_VECTOR_VALUE = 4 * 2.2  # float32, stored by the index and by Chroma's database
BYTES_PER_ITEM = 1_500
TEXT_OVERHEAD = 3  # the text, its normalized copy and the full-text index


def _check_free_space(items: list[Item]) -> None:
    """Refuse a file that won't fit, before anything is written — not halfway through."""
    dims = get_settings().embedding_dimensions
    needed = sum(
        dims * BYTES_PER_VECTOR_VALUE + BYTES_PER_ITEM
        + (TEXT_OVERHEAD * len(item.text.encode("utf-8")) if item.metadata.get("part") != "matn" else 0)
        for item in items
    )
    folder = Path(get_settings().chroma_dir)
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if needed > free:
        raise ExtractionError(
            f"مساحة التخزين لا تكفي: الملف يحتاج نحو {needed / 2**20:.0f} MB والمتاح "
            f"{free / 2**20:.0f} MB — احذف ملفات لا تحتاجها أو كبّر مساحة الـ Volume على Railway"
        )


def _progress(progress: Progress, offset: int, total: int) -> Callable[[int, int], None]:
    return lambda done, _: progress(f"إنشاء التمثيلات الدلالية {offset + done}/{total}")


def _hadith_metadata(record: HadithRecord, file_source: str) -> dict:
    # Chroma metadata values must be str/int/float/bool — never None or lists.
    return {
        "type": "structured_hadith",
        "source": file_source,
        "reference": record.source,
        "record_id": record.id,
        "hukm": record.hukm,
        "mohaddith": record.mohaddith,
        "sanad": sanad.serialize(record.sanad),
        "topic": record.topic,
    }


def _digest(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
