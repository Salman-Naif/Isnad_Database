"""Integration tests: exact-quote search, the matn vector, windowed writing and safe
replacement — with a real SQLite file and a real ChromaDB collection.

The sample hadiths follow the formats the importer reads: CSV with one hadith per row, and a
JSON collection per book.
"""

import json

import pytest

from app.db.sqlite import connection
from app.services import ingestion, text_index
from app.services.embeddings import EmbeddingError

NIYYAH = ("حدثنا الحميدي عبد الله بن الزبير قال حدثنا سفيان قال حدثنا يحيى بن سعيد الأنصاري قال "
          "أخبرني محمد بن إبراهيم التيمي أنه سمع علقمة بن وقاص الليثي يقول سمعت عمر بن الخطاب رضي الله "
          "عنه على المنبر قال سمعت رسول الله صلى الله عليه وسلم يقول إنما الأعمال بالنيات وإنما لكل "
          "امرئ ما نوى فمن كانت هجرته إلى دنيا يصيبها أو إلى امرأة ينكحها فهجرته إلى ما هاجر إليه")
NASIHA = ("حدثنا محمد بن عباد عن تميم الداري أن النبي صلى الله عليه وسلم قال الدين النصيحة قلنا لمن "
          "يا رسول الله قال لله ولكتابه ولرسوله ولأئمة المسلمين وعامتهم")
SHORT = "حدثنا وكيع عن سفيان عن أنس عن النبي صلى الله عليه وسلم قال لا ضرر ولا ضرار"
MAWQUF = "حدثنا مالك عن نافع عن ابن عمر أنه كان يقول لا يصلي أحد عن أحد ولا يصوم أحد عن أحد"
CSV = "Sahih Bukhari\n" + "\n".join((NIYYAH, NASIHA, MAWQUF, SHORT)) + "\n"


def upload(admin_client, name: str, data: bytes):
    res = admin_client.post("/api/sources", files={"file": (name, data)})
    assert res.status_code == 202, res.text
    return admin_client.get(f"/api/sources/{res.json()['id']}").json()


def search(client, site_headers, query, top_k=5):
    res = client.post("/api/v1/search", json={"query": query, "top_k": top_k}, headers=site_headers)
    assert res.status_code == 200, res.text
    return res.json()["matches"]


def test_hadiths_get_a_matn_vector_when_it_can_be_told_apart(admin_client, store):
    row = upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    assert row["status"] == "ready" and row["chunks"] == 4  # four hadiths…
    # …six vectors: no matn vector for the companion's saying (no matn) nor for «لا ضرر ولا
    # ضرار» (too short: short texts land close to any short query; the literal index finds it)
    assert store.count() == 6


def test_a_short_hadith_is_found_word_for_word(admin_client, client, site_headers):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    best = search(client, site_headers, "لا ضرر ولا ضرار")[0]
    assert best["similarity"] == 1.0 and best["text"] == SHORT and best["word_overlap"] == 1.0


def test_a_word_for_word_quote_is_found_with_similarity_one(admin_client, client, site_headers):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    # Typed without diacritics, with another hamza form, in the middle of a long narration:
    [best, *_] = search(client, site_headers, "انما الاعمال بالنيات وانما لكل امرئ ما نوى")
    assert best["similarity"] == 1.0
    assert best["source"] == "صحيح البخاري" and best["text"] == NIYYAH


def test_each_hadith_is_listed_once(admin_client, client, site_headers):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    matches = search(client, site_headers, "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", top_k=5)
    texts = [m["text"] for m in matches]
    assert len(texts) == len(set(texts)) == 4  # full + matn vectors and the exact hit, merged


@pytest.mark.parametrize("query", ["قال رسول الله صلى الله عليه وسلم", "الدين النصيحة"])
def test_short_or_common_phrases_are_not_taken_as_quotes(admin_client, query):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    assert text_index.find_quote(query) == []


def test_a_formula_found_everywhere_is_not_a_quote(client):
    rows = [(f"id{i}", "book.csv", f"حديث رقم {i} قال رسول الله صلى الله عليه وسلم كذا") for i in range(30)]
    text_index.add(rows)
    assert text_index.find_quote("قال رسول الله صلى الله عليه وسلم") == []  # 30 passages
    assert text_index.find_quote("حديث رقم 7 قال رسول الله") == ["id7"]


def test_deleting_a_source_removes_its_literal_text(admin_client, store):
    row = upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    assert text_index.find_quote("انما الاعمال بالنيات وانما لكل")
    admin_client.delete(f"/api/sources/{row['id']}")
    assert text_index.find_quote("انما الاعمال بالنيات وانما لكل") == []
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0] == 0


def test_large_files_are_written_window_by_window(admin_client, store, embedder, monkeypatch):
    monkeypatch.setattr(ingestion, "WRITE_WINDOW", 2)
    calls = []
    original = embedder.encode
    monkeypatch.setattr(embedder, "encode", lambda texts, progress=None: calls.append(len(texts)) or original(texts, progress))
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    assert calls == [2, 2, 2]  # 6 vectors, at most 2 in memory at a time


def test_a_failed_reupload_keeps_the_previous_version_whole(admin_client, client, site_headers, store,
                                                            embedder, monkeypatch):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    before = sorted(store.ids_of("Sahih Bukhari.csv"))

    monkeypatch.setattr(ingestion, "WRITE_WINDOW", 2)
    calls = []
    original = embedder.encode

    def fail_on_second_window(texts, progress=None):
        calls.append(1)
        if len(calls) == 2:
            raise EmbeddingError("خدمة التمثيلات الدلالية أعادت خطأ (503)")
        return original(texts, progress)

    monkeypatch.setattr(embedder, "encode", fail_on_second_window)
    row = upload(admin_client, "Sahih Bukhari.csv", (CSV + NASIHA + " أيضا\n").encode())
    assert row["status"] == "ready" and "النسخة السابقة" in row["error"]
    assert sorted(store.ids_of("Sahih Bukhari.csv")) == before  # nothing half-written left
    assert search(client, site_headers, "انما الاعمال بالنيات وانما لكل امرئ ما نوى")[0]["similarity"] == 1.0


def test_a_successful_reupload_replaces_everything(admin_client, store):
    upload(admin_client, "Sahih Bukhari.csv", CSV.encode())
    first = set(store.ids_of("Sahih Bukhari.csv"))
    upload(admin_client, "Sahih Bukhari.csv", ("Sahih Bukhari\n" + NASIHA + "\n").encode())
    second = set(store.ids_of("Sahih Bukhari.csv"))
    assert len(second) == 2 and not first & second  # NASIHA: narration + matn
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0] == 1


def test_sunnah_json_gets_matn_vectors_too(admin_client, store):
    book = {"metadata": {"arabic": {"title": "صحيح مسلم"}}, "chapters": [{"id": 1, "arabic": "كتاب الإيمان"}],
            "hadiths": [{"idInBook": 95, "chapterId": 1, "arabic": NASIHA}]}
    row = upload(admin_client, "muslim.json", json.dumps(book, ensure_ascii=False).encode())
    assert row["chunks"] == 1 and store.count() == 2


def test_database_uses_write_ahead_logging(client):
    with connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
