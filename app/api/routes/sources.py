"""
Uploaded sources — upload, list, download and delete. Admins only.

Uploads accept PDF, Word, text, scanned images, and hadith collections (JSON or CSV).
An upload is streamed to disk and answered at once (202); indexing then runs in
the background and the file list shows its progress — a large scanned book can
take many minutes, far longer than an HTTP request should wait.
"""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import get_embedder, get_vector_store, require_admin
from app.config import get_settings
from app.models.schemas import SourceInfo, SourcesResponse
from app.services import sources
from app.services.auth import Admin
from app.services.embeddings import EmbeddingService
from app.services.vector_store import VectorStore

router = APIRouter(prefix="/sources", tags=["sources"], dependencies=[Depends(require_admin)])

COPY_CHUNK_BYTES = 1024 * 1024


@router.post("", response_model=SourceInfo, status_code=status.HTTP_202_ACCEPTED)
def upload_source(
    file: UploadFile = File(...),
    admin: Admin = Depends(require_admin),
    embedder: EmbeddingService = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> SourceInfo:
    """Accept one file and index it in the background. Re-uploading a file name replaces it."""
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in sources.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="نوع الملف غير مدعوم. المسموح: " + " ".join(sorted(sources.ALLOWED_EXTENSIONS)),
        )

    # Copy to disk in 1 MB pieces, so even a 100 MB book never sits in memory here.
    max_mb = get_settings().max_upload_mb
    incoming = sources.new_incoming_path(filename)
    size = 0
    with incoming.open("wb") as out:
        while piece := file.file.read(COPY_CHUNK_BYTES):
            size += len(piece)
            if size > max_mb * 1024 * 1024:
                break
            out.write(piece)
    if size > max_mb * 1024 * 1024:
        incoming.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"حجم الملف أكبر من الحد المسموح ({max_mb} MB)",
        )
    if size == 0:
        incoming.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="الملف فارغ")

    try:
        return sources.enqueue_source(incoming, filename, size, admin.username, embedder, store)
    except sources.SourceBusyError as exc:
        incoming.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=SourcesResponse)
def list_sources() -> SourcesResponse:
    items = sources.list_sources()
    ready = [s for s in items if s.status == "ready"]
    return SourcesResponse(
        sources=items, total_files=len(ready), total_chunks=sum(s.chunks for s in ready)
    )


@router.get("/{source_id}", response_model=SourceInfo)
def get_source(source_id: int) -> SourceInfo:
    """One file's current state — the dashboard polls this while it is processing."""
    source = sources.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الملف غير موجود")
    return source


@router.get("/{source_id}/download")
def download_source(source_id: int) -> FileResponse:
    """The original file exactly as it was uploaded."""
    source = sources.get_source(source_id)
    path = sources.stored_path(source.filename) if source else None
    if source is None or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الملف غير موجود")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(source.filename)}"},
    )


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, store: VectorStore = Depends(get_vector_store)) -> Response:
    """Remove a source: its chunks in the database, its original file and its record."""
    source = sources.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="الملف غير موجود")
    try:
        sources.delete_source(source, store)
    except sources.SourceBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
