"""
Uploaded sources: registry, stored originals, and background indexing.

Flow for an upload from the dashboard:
  1. the route streams the file to UPLOADS_DIR/.incoming/ (never held whole in memory)
  2. enqueue_source() records it as 'processing' and hands it to the background worker
  3. the worker indexes it (extract → chunk → embed → ChromaDB) and updates `progress`
  4. on success the file becomes the stored original and the row 'ready'; on failure
     the previous version of the same file (if any) stays searchable and the row shows why

A single worker processes uploads one at a time: OCR and embedding are heavy, and
running several at once would only compete for the same CPU and API quota. A large
scanned book can take many minutes — the dashboard shows its progress meanwhile.

The registry (SQLite `sources` table) is what the dashboard lists: file name, type,
size, number of chunks, who uploaded it and when, and its processing status.
"""

import errno
import hashlib
import logging
import os
import shutil
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.db.sqlite import connection, vacuum
from app.models.schemas import SourceInfo
from app.services import text_index
from app.services.embeddings import EmbeddingError, EmbeddingService
from app.services.extraction import SUPPORTED_EXTENSIONS, ExtractionError
from app.services.ingestion import STRUCTURED_EXTENSIONS, ingest_upload
from app.services.vector_store import VectorStore, VectorStoreError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = SUPPORTED_EXTENSIONS | STRUCTURED_EXTENSIONS

# Fixed statements; values are always bound as ? parameters.
_SELECT = (
    "SELECT id, filename, kind, size_bytes, chunks, characters, ocr_pages, uploaded_by, "
    "uploaded_at, status, progress, error FROM sources"
)
_SELECT_ALL = _SELECT + " ORDER BY uploaded_at DESC"
_SELECT_READY = _SELECT + " WHERE status = 'ready' ORDER BY uploaded_at DESC"
_SELECT_BY_ID = _SELECT + " WHERE id = ?"
_SELECT_BY_NAME = _SELECT + " WHERE filename = ?"
# Expected failures carry a message meant for the admin; anything else is a bug.
_KNOWN_ERRORS = (ExtractionError, EmbeddingError, VectorStoreError)

DISK_FULL_MESSAGE = (
    "مساحة التخزين ممتلئة — احذف ملفات لا تحتاجها، أو كبّر مساحة الـ Volume على Railway "
    "(الخطة المجانية 0.5 GB، Hobby 5 GB)"
)


def _is_disk_full(exc: BaseException) -> bool:
    """SQLite's "database or disk is full", or the system's "No space left on device"."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return True
    text = str(exc).lower()
    return "disk is full" in text or "no space left" in text
PROGRESS_WRITE_INTERVAL = 1.0  # seconds — don't hit SQLite for every page

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")


class SourceBusyError(Exception):
    """The file is already being processed."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def stored_path(filename: str) -> Path:
    """Where the original of an uploaded file is kept.

    Named by a hash of the file name, so any name (Arabic, spaces, symbols) is
    safe on every filesystem and a re-upload overwrites the previous original.
    """
    digest = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:24]
    return Path(get_settings().uploads_dir) / f"{digest}{Path(filename).suffix.lower()}"


def _incoming_dir() -> Path:
    return Path(get_settings().uploads_dir) / ".incoming"


def new_incoming_path(filename: str) -> Path:
    """A fresh temporary path for an upload that hasn't been processed yet."""
    folder = _incoming_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


# --- Starting and running a job ---


def _register(filename: str, size: int, uploaded_by: str | None) -> bool:
    """Mark the file as processing. Returns whether a ready previous version exists."""
    kind = "structured_hadith" if Path(filename).suffix.lower() in STRUCTURED_EXTENSIONS else "document"
    with connection() as conn:
        existing = conn.execute(
            "SELECT status, chunks FROM sources WHERE filename = ?", (filename,)
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO sources
                     (filename, kind, size_bytes, chunks, characters, ocr_pages,
                      uploaded_by, uploaded_at, status, progress)
                   VALUES (?, ?, ?, 0, 0, 0, ?, ?, 'processing', 'في الانتظار')""",
                (filename, kind, size, uploaded_by, _now()),
            )
            return False
        updated = conn.execute(
            """UPDATE sources SET status = 'processing', progress = 'في الانتظار', error = NULL
               WHERE filename = ? AND status != 'processing'""",
            (filename,),
        ).rowcount
    if not updated:
        raise SourceBusyError("هذا الملف قيد المعالجة بالفعل — انتظر حتى ينتهي")
    return existing["chunks"] > 0


def _progress_writer(filename: str):
    last_write = 0.0

    def report(text: str) -> None:
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < PROGRESS_WRITE_INTERVAL:
            return
        last_write = now
        with connection() as conn:
            conn.execute("UPDATE sources SET progress = ? WHERE filename = ?", (text, filename))

    return report


def _process(
    incoming: Path,
    filename: str,
    size: int,
    uploaded_by: str | None,
    has_previous: bool,
    embedder: EmbeddingService,
    store: VectorStore,
) -> None:
    try:
        result = ingest_upload(
            incoming.read_bytes(), filename, embedder, store, _progress_writer(filename)
        )
        destination = stored_path(filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(incoming, destination)
        with connection() as conn:
            conn.execute(
                """UPDATE sources SET kind = ?, size_bytes = ?, chunks = ?, characters = ?,
                     ocr_pages = ?, uploaded_by = ?, uploaded_at = ?,
                     status = 'ready', progress = NULL, error = ?
                   WHERE filename = ?""",
                (result.kind, size, result.chunks, result.characters, result.ocr_pages,
                 uploaded_by, _now(), result.note, filename),
            )
    except Exception as exc:
        if isinstance(exc, _KNOWN_ERRORS):
            message = str(exc)
        elif _is_disk_full(exc):
            logger.error("Storage is full while processing %s: %s", filename, exc)
            message = DISK_FULL_MESSAGE
        else:
            logger.exception("Unexpected error while processing %s", filename)
            message = "خطأ غير متوقع أثناء المعالجة"
        incoming.unlink(missing_ok=True)
        with connection() as conn:
            if has_previous:
                # The indexing step replaces chunks only after embedding succeeds,
                # so the previous version is still intact and searchable.
                conn.execute(
                    """UPDATE sources SET status = 'ready', progress = NULL, error = ?
                       WHERE filename = ?""",
                    (f"فشل تحديث الملف وبقيت النسخة السابقة: {message}", filename),
                )
            else:
                conn.execute(
                    """UPDATE sources SET status = 'failed', progress = NULL, error = ?
                       WHERE filename = ?""",
                    (message, filename),
                )


def enqueue_source(
    incoming: Path,
    filename: str,
    size: int,
    uploaded_by: str | None,
    embedder: EmbeddingService,
    store: VectorStore,
) -> SourceInfo:
    """Record an upload and index it in the background. Returns its row ('processing')."""
    filename = Path(filename).name
    has_previous = _register(filename, size, uploaded_by)
    _executor.submit(_process, incoming, filename, size, uploaded_by, has_previous, embedder, store)
    return _registered(filename)


def add_source(
    data: bytes,
    filename: str,
    uploaded_by: str | None,
    embedder: EmbeddingService,
    store: VectorStore,
) -> SourceInfo:
    """Index a file right away (command line). Returns its final row — check `status`."""
    filename = Path(filename).name
    incoming = new_incoming_path(filename)
    incoming.write_bytes(data)
    try:
        has_previous = _register(filename, len(data), uploaded_by)
    except SourceBusyError:
        incoming.unlink(missing_ok=True)
        raise
    _process(incoming, filename, len(data), uploaded_by, has_previous, embedder, store)
    return _registered(filename)


def recover_interrupted() -> None:
    """On startup: jobs cut off by a restart or redeploy can't resume — say so plainly."""
    message = "توقفت المعالجة بسبب إعادة تشغيل الخادم — ارفع الملف مرة أخرى"
    with connection() as conn:
        conn.execute(
            """UPDATE sources SET
                 status = CASE WHEN chunks > 0 THEN 'ready' ELSE 'failed' END,
                 progress = NULL, error = ?
               WHERE status = 'processing'""",
            (message,),
        )
    shutil.rmtree(_incoming_dir(), ignore_errors=True)


# --- Reading and deleting ---


def list_sources(ready_only: bool = False) -> list[SourceInfo]:
    with connection() as conn:
        rows = conn.execute(_SELECT_READY if ready_only else _SELECT_ALL).fetchall()
    return [SourceInfo(**dict(r)) for r in rows]


def get_source(source_id: int) -> SourceInfo | None:
    with connection() as conn:
        row = conn.execute(_SELECT_BY_ID, (source_id,)).fetchone()
    return SourceInfo(**dict(row)) if row else None


def get_source_by_name(filename: str) -> SourceInfo | None:
    with connection() as conn:
        row = conn.execute(_SELECT_BY_NAME, (filename,)).fetchone()
    return SourceInfo(**dict(row)) if row else None


def _registered(filename: str) -> SourceInfo:
    """The row of a file that was just registered (it exists unless the database broke)."""
    source = get_source_by_name(filename)
    if source is None:
        raise RuntimeError(f"source {filename!r} vanished from the registry")
    return source


def delete_source(source: SourceInfo, store: VectorStore) -> None:
    """Remove a source everywhere: its chunks, its original file and its registry row."""
    if source.status == "processing":
        raise SourceBusyError("لا يمكن حذف ملف قيد المعالجة — انتظر حتى ينتهي")
    store.delete_source(source.filename)
    text_index.delete_source(source.filename)
    stored_path(source.filename).unlink(missing_ok=True)
    with connection() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source.id,))
    # In the background, after any upload being indexed: rewriting the files takes a while.
    _executor.submit(reclaim_space, store)


def reclaim_space(store: VectorStore) -> None:
    """Give the space of deleted items back to the disk (SQLite files never shrink alone)."""
    try:
        store.compact()
        vacuum()
        logger.info("Storage compacted")
    except Exception:
        # Rewriting needs some free space itself; the data is untouched if it fails.
        logger.exception("Could not compact the storage")


def totals() -> tuple[int, int]:
    """(number of ready files, number of chunks) in the registry."""
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(chunks), 0) FROM sources WHERE status = 'ready'"
            ).fetchone()
    except sqlite3.Error:
        return 0, 0
    return row[0], row[1]
