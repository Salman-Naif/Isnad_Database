"""Integration tests: scripts/reset_sources.py clears every source and keeps everything else."""

import sys

import pytest

from app.config import get_settings
from app.db.sqlite import connection
from app.models.schemas import EventIn
from app.services import auth, events, text_index


@pytest.fixture
def storage(tmp_path, monkeypatch, client):
    """A storage folder laid out as on the Railway Volume (the vector files closed, as after a stop)."""
    chroma = tmp_path / "chroma_db"
    chroma.mkdir()
    (chroma / "chroma.sqlite3").write_bytes(b"x" * 5000)
    index = chroma / "8a8c8c5b-3a0b-454a-b701-b9fe90c3d85c"
    index.mkdir()
    (index / "data_level0.bin").write_bytes(b"x" * 9000)
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "صحيح البخاري.json").write_bytes(b"{}")
    (chroma / "notes.txt").write_text("not Chroma's", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "chroma_dir", str(chroma))
    monkeypatch.setattr(get_settings(), "uploads_dir", str(uploads))
    return chroma, uploads


def run(monkeypatch, *args):
    import scripts.reset_sources as script

    monkeypatch.setattr(sys, "argv", ["reset_sources.py", *args])
    script.main()


def test_everything_about_sources_goes_and_the_rest_stays(storage, monkeypatch, capsys):
    chroma, uploads = storage
    auth.create_admin("editor", "a-long-password")
    events.record_event(EventIn(type="visit", visitor_id="v1"))
    text_index.add([("doc-1", "book.txt", "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى")])
    with connection() as conn:
        conn.execute("""INSERT INTO sources (filename, kind, size_bytes, chunks, characters, uploaded_at)
                        VALUES ('book.txt', 'document', 10, 1, 10, '2026-10-02 00:00:00')""")

    run(monkeypatch, "--yes")

    assert sorted(p.name for p in chroma.iterdir()) == ["notes.txt"]  # only Chroma's files deleted
    assert list(uploads.iterdir()) == []
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert auth.authenticate("editor", "a-long-password") is not None
    assert "MB of vectors and originals deleted" in capsys.readouterr().out


def test_nothing_happens_without_confirmation(storage, monkeypatch):
    chroma, _ = storage
    with pytest.raises(SystemExit):
        run(monkeypatch)
    assert (chroma / "chroma.sqlite3").exists()
