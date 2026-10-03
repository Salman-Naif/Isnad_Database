"""Integration tests: hadith collections (JSON or CSV) through the upload pipeline and the
import script, into a real vector store.

Samples in the two formats the importer reads: a JSON collection per book, and CSV with one
hadith per row.
"""

import json
import sys

import httpx
import pytest

from app.config import get_settings
from app.services import sources

BUKHARI = {"metadata": {"arabic": {"title": "صحيح البخاري"}}, "chapters": [{"id": 1, "arabic": "كتاب الإيمان"}],
           "hadiths": [{"idInBook": 1, "chapterId": 1, "arabic": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى"},
                       {"idInBook": 2, "chapterId": 1, "arabic": "بني الإسلام على خمس شهادة أن لا إله إلا الله"}]}
MUSLIM_CSV = "1,الدين النصيحة قلنا لمن قال لله ولكتابه ولرسوله\n2,من غشنا فليس منا\n"


def upload(admin_client, name, data: bytes):
    res = admin_client.post("/api/sources", files={"file": (name, data)})
    assert res.status_code == 202, res.text
    return admin_client.get(f"/api/sources/{res.json()['id']}").json()


def test_csv_collection_uploads_from_the_dashboard(admin_client, client, site_headers):
    row = upload(admin_client, "muslim.csv", MUSLIM_CSV.encode())
    assert row["status"] == "ready" and row["kind"] == "structured_hadith" and row["chunks"] == 2
    best = client.post("/api/v1/search", json={"query": "من غشنا فليس منا"}, headers=site_headers).json()["matches"][0]
    assert best["kind"] == "structured_hadith" and best["source"] == "صحيح مسلم"  # known title, in Arabic


def test_books_with_the_same_hadith_numbers_do_not_overwrite_each_other(admin_client, store):
    upload(admin_client, "bukhari.json", json.dumps(BUKHARI, ensure_ascii=False).encode())
    upload(admin_client, "muslim.csv", MUSLIM_CSV.encode())  # also numbered 1, 2
    assert store.count() == 4
    admin_client.delete(f"/api/sources/{sources.get_source_by_name('muslim.csv').id}")
    assert store.count() == 2  # the other book is untouched


def test_sunnah_json_keeps_topic_and_book_title(admin_client, client, site_headers):
    upload(admin_client, "bukhari.json", json.dumps(BUKHARI, ensure_ascii=False).encode())
    best = client.post("/api/v1/search", json={"query": "إنما الأعمال بالنيات"}, headers=site_headers).json()["matches"][0]
    assert best["topic"] == "كتاب الإيمان" and best["source"] == "صحيح البخاري"


def test_bad_collection_fails_with_the_reason(admin_client):
    row = upload(admin_client, "broken.csv", b"1,English only\n")
    assert row["status"] == "failed" and "لا يحتوي" in row["error"]


# --- scripts/import_hadiths.py ---


def run(monkeypatch, *args):
    import scripts.import_hadiths as script

    monkeypatch.setattr(sys, "argv", ["import_hadiths.py", *map(str, args)])
    script.main()
    return script


def test_script_converts_files_and_folders(monkeypatch, tmp_path, capsys):
    books = tmp_path / "books"
    books.mkdir()
    (books / "bukhari.json").write_text(json.dumps(BUKHARI, ensure_ascii=False), encoding="utf-8")
    (books / "muslim.csv").write_text(MUSLIM_CSV, encoding="utf-8")
    out = tmp_path / "out"
    run(monkeypatch, books, "--out", out, "--hukm", "صحيح", "--mohaddith", "الإمامان")

    printed = capsys.readouterr().out
    assert "2 hadiths of «صحيح البخاري»" in printed and "2 hadiths of «صحيح مسلم»" in printed
    converted = json.loads((out / "bukhari.json").read_text(encoding="utf-8"))
    assert converted[0]["hukm"] == "صحيح" and converted[0]["mohaddith"] == "الإمامان"
    assert converted[0]["topic"] == "كتاب الإيمان"


def test_script_measures_the_cost_from_a_sample(monkeypatch, tmp_path, capsys):
    script = __import__("scripts.import_hadiths", fromlist=["estimate"])
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "sk-or-test")
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        chars = sum(len(t) for t in body["input"])
        return httpx.Response(200, json={"data": [], "usage": {"prompt_tokens": chars // 2, "cost": chars * 1e-8}})

    texts = ["حديث " * 20] * 1000
    result = script.estimate(texts, sample_size=50, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(sent[0]["input"]) == 50 and sent[0]["model"] == get_settings().embedding_model
    assert result.hadiths == 1000
    assert result.tokens == pytest.approx(result.characters / 2, rel=0.01)
    assert result.cost == pytest.approx(result.characters * 1e-8, rel=0.01)
    assert result.sample_cost < result.cost / 10


def test_script_indexes_into_the_database(monkeypatch, tmp_path, store, embedder, client, capsys):
    import app.api.deps as deps

    monkeypatch.setattr(deps, "get_embedder", lambda: embedder)
    monkeypatch.setattr(deps, "get_vector_store", lambda: store)
    book = tmp_path / "muslim.csv"
    book.write_text(MUSLIM_CSV, encoding="utf-8")
    run(monkeypatch, book, "--out", tmp_path / "out", "--index", "--source", "صحيح مسلم")
    assert "indexed: ready — 2 hadiths" in capsys.readouterr().out
    assert store.count() == 2


def test_script_reports_unreadable_files(monkeypatch, tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(monkeypatch, bad, "--out", tmp_path / "out")
    assert "✗ bad.json" in capsys.readouterr().out
