"""Integration tests: vector store queries, status checks and the command-line scripts,
each against a real SQLite file, a real ChromaDB collection and real files on disk."""

import importlib
import json
import sys

import httpx
import pytest

from app.config import get_settings
from app.db.sqlite import connection
from app.services import auth, sources, status

# --- Vector store ---


def test_query_returns_closest_first_with_metadata(store, embedder):
    texts = ["إنما الأعمال بالنيات", "الدين النصيحة", "من غشنا فليس منا"]
    store.upsert(
        ids=["a", "b", "c"],
        documents=texts,
        embeddings=[embedder.encode_one(t) for t in texts],
        metadatas=[{"source": "كتاب.txt", "type": "document", "topic": ""}] * 3,
    )
    found = store.query(embedder.encode_one("الدين النصيحة"), top_k=2)
    assert found[0]["id"] == "b"
    assert found[0]["similarity"] == pytest.approx(1.0, abs=1e-5)
    assert found[0]["metadata"]["source"] == "كتاب.txt"
    assert len(found) == 2 and found[0]["similarity"] >= found[1]["similarity"]


def test_empty_store_returns_nothing_without_checks(store, embedder):
    assert store.query(embedder.encode_one("نص")) == []
    assert store.model_mismatch() is None


def test_sources_and_topics_are_counted(store, embedder):
    items = [("h1", "النية", "structured_hadith"), ("h2", "النية", "structured_hadith"),
             ("h3", "الصلاة", "structured_hadith"), ("d1", "", "document")]
    store.upsert(
        ids=[i for i, _, _ in items],
        documents=[f"نص {i}" for i, _, _ in items],
        embeddings=[embedder.encode_one(i) for i, _, _ in items],
        metadatas=[{"source": "s.json" if k != "document" else "b.txt", "topic": t, "type": k}
                   for _, t, k in items],
    )
    assert store.list_topics() == [{"name": "النية", "count": 2}, {"name": "الصلاة", "count": 1}]
    assert {(s["source"], s["chunks"]) for s in store.list_sources()} == {("s.json", 3), ("b.txt", 1)}
    assert [h["id"] for h in store.query_by_topic("الصلاة")] == ["h3"]
    assert store.delete_source("s.json") == 3
    assert store.count() == 1


# --- Status checks ---


def test_ocr_check_reports_the_engine(monkeypatch):
    monkeypatch.setattr(status, "_tesseract", lambda: (True, "Tesseract 5 مع العربية"))
    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_engine", "vision")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    ok, detail = status._ocr()
    assert ok is False and "OPENROUTER_API_KEY" in detail and "Tesseract" in detail

    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-test")
    ok, detail = status._ocr()
    assert ok is True and settings.ocr_model in detail and "الاحتياطي" in detail

    monkeypatch.setattr(settings, "ocr_engine", "tesseract")
    assert status._ocr() == (True, "Tesseract 5 مع العربية")


@pytest.mark.parametrize(("key", "ok"), [("", None), ("short-key", False), ("k" * 32, True)])
def test_site_key_check(monkeypatch, key, ok):
    monkeypatch.setattr(get_settings(), "site_api_key", key)
    assert status._site_api_key()[0] is ok


def test_disk_check_reports_free_space():
    ok, detail = status._disk()
    assert ok in (True, False) and "GB" in detail


def test_openrouter_check_reads_usage_and_credit(monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "sk-or-test")

    def reply(data):
        return lambda url, **kw: httpx.Response(200, json={"data": data}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", reply({"usage": 1.5, "limit": 10, "limit_remaining": 8.5}))
    ok, detail = status._openrouter_key()
    assert ok is True and "1.5000" in detail and "10.00" in detail

    monkeypatch.setattr(httpx, "get", reply({"usage": 10, "limit": 10, "limit_remaining": 0}))
    ok, detail = status._openrouter_key()
    assert ok is False and "الرصيد انتهى" in detail


def test_main_site_check_reports_errors_and_maintenance(admin_client, monkeypatch):
    admin_client.put("/api/site-settings", json={"main_site_url": "https://isnad.example", "maintenance_mode": True})
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(502, request=httpx.Request("GET", url)))
    ok, detail = status._main_site()
    assert ok is False and "502" in detail and "الصيانة" in detail


def test_a_crashing_check_never_breaks_the_page():
    def broken():
        raise RuntimeError("boom")

    result = status._run("فحص", broken)
    assert result.ok is False and "boom" in result.detail


# --- Command-line scripts ---


def run_script(monkeypatch, name, *args):
    """Run scripts/<name>.py main() in-process with the given arguments."""
    module = importlib.import_module(f"scripts.{name}")
    monkeypatch.setattr(sys, "argv", [f"{name}.py", *args])
    module.main()
    return module


@pytest.fixture
def build(monkeypatch, store, embedder):
    """scripts/build_database.py, using the test embedder and vector store."""
    import scripts.build_database as build

    monkeypatch.setattr(build, "get_embedder", lambda: embedder)
    monkeypatch.setattr(build, "get_vector_store", lambda: store)
    return build


def test_build_database_indexes_folders(monkeypatch, tmp_path, build, capsys):
    raw, structured = tmp_path / "raw", tmp_path / "structured"
    (raw / "sub").mkdir(parents=True)
    structured.mkdir()
    (raw / "sub" / "كتاب.txt").write_text("إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", encoding="utf-8")
    (raw / "ignored.exe").write_bytes(b"MZ")
    (structured / "hadiths.json").write_text(json.dumps(
        [{"id": "1", "text": "الدين النصيحة", "hukm": "صحيح"}], ensure_ascii=False), encoding="utf-8")

    run_script(monkeypatch, "build_database", "--raw-dir", str(raw), "--structured-dir", str(structured))
    out = capsys.readouterr().out
    assert "✓ كتاب.txt" in out and "✓ hadiths.json" in out and "Done: 2/2" in out
    assert {s.filename for s in sources.list_sources()} == {"كتاب.txt", "hadiths.json"}


def test_build_database_exits_nonzero_on_failures(monkeypatch, tmp_path, build):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "empty.txt").write_text("١٢", encoding="utf-8")  # nothing readable
    with pytest.raises(SystemExit) as exc:
        run_script(monkeypatch, "build_database", "--raw-dir", str(raw), "--structured-dir", str(tmp_path / "none"))
    assert exc.value.code == 1


def test_build_database_with_empty_folders(monkeypatch, tmp_path, build, capsys):
    run_script(monkeypatch, "build_database", "--raw-dir", str(tmp_path), "--structured-dir", str(tmp_path))
    assert "No files found" in capsys.readouterr().out


def test_manage_admins_create_list_reset_delete(monkeypatch, capsys, client):
    import scripts.manage_admins as manage

    monkeypatch.setattr(manage, "ask_password", lambda: "a-long-password")
    run_script(monkeypatch, "manage_admins", "create", "editor")
    assert auth.authenticate("editor", "a-long-password") is not None

    run_script(monkeypatch, "manage_admins", "list")
    assert "editor" in capsys.readouterr().out

    monkeypatch.setattr(manage, "ask_password", lambda: "another-long-password")
    run_script(monkeypatch, "manage_admins", "password", "editor")
    assert auth.authenticate("editor", "another-long-password") is not None

    run_script(monkeypatch, "manage_admins", "delete", "editor")
    assert auth.authenticate("editor", "another-long-password") is None

    with pytest.raises(SystemExit):
        run_script(monkeypatch, "manage_admins", "delete", "editor")


def test_manage_admins_rejects_weak_passwords(monkeypatch, client):
    import scripts.manage_admins as manage

    monkeypatch.setattr(manage, "ask_password", lambda: "short")
    with pytest.raises(SystemExit) as exc:
        run_script(monkeypatch, "manage_admins", "create", "editor")
    assert "8" in str(exc.value.code)


def test_extract_text_writes_cleaned_text(monkeypatch, tmp_path, capsys):
    import scripts.extract_text as extract

    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    (raw / "نص.txt").write_text("إِنَّمَا الأَعْمَالُ بالنيات", encoding="utf-8")
    (raw / "bad.pdf").write_bytes(b"not a pdf")
    monkeypatch.setattr(extract, "RAW_DIR", raw)
    monkeypatch.setattr(extract, "PROCESSED_DIR", processed)
    extract.main()
    assert (processed / "نص.txt").read_text(encoding="utf-8") == "إنما الأعمال بالنيات"
    assert "✗ bad.pdf" in capsys.readouterr().out


def test_cli_upload_path_registers_the_file(store, embedder, client):
    source = sources.add_source("الدين النصيحة لله ولرسوله".encode(), "cli.txt", "command line", embedder, store)
    assert source.status == "ready" and source.uploaded_by == "command line"
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
