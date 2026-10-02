"""Integration tests: disk space — texts stored once, space given back after a delete, files
that won't fit refused up front, and a full disk reported plainly."""

import errno
import sqlite3
from collections import namedtuple

import pytest

from app.config import get_settings
from app.db.sqlite import connection, init_db
from app.services import ingestion, sources, text_index

BOOK = "Sahih Bukhari\n" + "\n".join(
    f"حدثنا فلان عن فلان أن رسول الله صلى الله عليه وسلم قال الحديث رقم {i} في باب الطهارة والصلاة والصيام"
    for i in range(1, 41)
) + "\n"


def upload(admin_client, name, data: bytes):
    res = admin_client.post("/api/sources", files={"file": (name, data)})
    assert res.status_code == 202, res.text
    return admin_client.get(f"/api/sources/{res.json()['id']}").json()


def test_the_vector_store_keeps_no_texts(admin_client, store):
    upload(admin_client, "book.csv", BOOK.encode())
    raw = store._connect().get(include=["documents"])
    assert raw["ids"] and all(doc is None for doc in raw["documents"])
    with connection() as conn:  # one text per hadith, none for its matn vector
        assert conn.execute("SELECT COUNT(*) FROM passages WHERE text != ''").fetchone()[0] == 40


def test_deleting_a_source_compacts_the_storage(admin_client, store, monkeypatch):
    compacted = []
    monkeypatch.setattr(store, "compact", lambda: compacted.append(store.count()))
    row = upload(admin_client, "book.csv", BOOK.encode())
    assert admin_client.delete(f"/api/sources/{row['id']}").status_code == 204
    assert compacted == [0]  # run after the delete, by the background worker


def test_compaction_runs_on_a_real_database(admin_client, store):
    row = upload(admin_client, "book.csv", BOOK.encode())
    admin_client.delete(f"/api/sources/{row['id']}")
    sources.reclaim_space(store)  # the real Chroma vacuum and SQLite VACUUM
    assert store.count() == 0
    assert store.model_mismatch() is None
    upload(admin_client, "book.csv", BOOK.encode())  # the store still works afterwards
    assert store.count() > 0


def test_a_file_that_wont_fit_is_refused_before_anything_is_written(admin_client, store, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(ingestion.shutil, "disk_usage", lambda _: usage(10**9, 10**9 - 10_000, 10_000))
    row = upload(admin_client, "book.csv", BOOK.encode())
    assert row["status"] == "failed"
    assert "مساحة التخزين لا تكفي" in row["error"] and "MB" in row["error"]
    assert store.count() == 0


@pytest.mark.parametrize("error", [
    sqlite3.OperationalError("database or disk is full"),
    OSError(errno.ENOSPC, "No space left on device"),
])
def test_a_full_disk_is_reported_plainly(admin_client, monkeypatch, error):
    def full(*args, **kwargs):
        raise error

    monkeypatch.setattr(text_index, "add", full)
    row = upload(admin_client, "book.csv", BOOK.encode())
    assert row["status"] == "failed"
    assert row["error"] == sources.DISK_FULL_MESSAGE


def test_databases_from_the_previous_version_get_the_text_column(client):
    with connection() as conn:
        conn.execute("DROP TABLE passages")
        conn.execute("CREATE TABLE passages (rowid INTEGER PRIMARY KEY, item_id TEXT NOT NULL UNIQUE, source TEXT NOT NULL)")
    init_db()
    with connection() as conn:
        assert "text" in {r["name"] for r in conn.execute("PRAGMA table_info(passages)")}
    assert get_settings().sqlite_path
