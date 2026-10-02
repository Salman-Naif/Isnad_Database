"""Integration tests: upload → extraction → chunks → embeddings → vector store → file registry."""

import json

from app.config import get_settings
from app.db.sqlite import connection
from app.services import sources, text_index
from app.services.embeddings import EmbeddingError
from app.services.ingestion import ingest_file
from app.services.sanad import parse

HADITH_A = "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى فمن كانت هجرته إلى الله ورسوله"


HADITH_B = "من حسن إسلام المرء تركه ما لا يعنيه من القول والعمل في كل حال"


BOOK = f"{HADITH_A}\n\n{HADITH_B}".encode()


def upload(client, name: str, data: bytes):
    return client.post("/api/sources", files={"file": (name, data)})


def test_upload_reports_api_failure_and_saves_nothing(admin_client, store):
    from app.api.deps import get_embedder
    from app.main import app

    class DownEmbedder:
        def encode(self, texts, progress=None):
            raise EmbeddingError("تعذّر الاتصال بخدمة التمثيلات الدلالية، حاول مرة أخرى")

    app.dependency_overrides[get_embedder] = lambda: DownEmbedder()
    res = admin_client.post("/api/sources", files={"file": ("book.txt", "نص عربي كافٍ ليكون مقطعًا واحدًا على الأقل في القاعدة".encode())})

    assert res.status_code == 202  # accepted; the failure shows in the file's status
    assert res.json()["status"] == "failed"
    assert "تعذّر الاتصال" in res.json()["error"]
    assert store.count() == 0
    assert admin_client.get("/api/sources").json()["total_files"] == 0


def test_upload_is_accepted_indexed_and_registered(admin_client, store, embedder):
    res = upload(admin_client, "book.txt", BOOK)

    assert res.status_code == 202, res.text
    body = res.json()
    assert body["filename"] == "book.txt"
    assert body["status"] == "ready"
    assert body["kind"] == "document"
    assert body["chunks"] == 2
    assert body["size_bytes"] == len(BOOK)
    assert body["uploaded_by"] == "admin"
    assert body["error"] is None

    assert store.count() == 2
    top = store.query(embedder.encode_one(HADITH_B), top_k=1)[0]
    assert top["metadata"]["source"] == "book.txt"
    # The vector store keeps vectors only; the text is stored once, in the passages table.
    assert top["text"] == ""
    assert text_index.texts([top["id"]]) == {top["id"]: HADITH_B}


def test_arabic_file_name(admin_client):
    res = upload(admin_client, "صحيح البخاري.txt", BOOK)
    assert res.status_code == 202
    assert res.json()["filename"] == "صحيح البخاري.txt"


def test_reupload_replaces_previous_version(admin_client, store):
    upload(admin_client, "book.txt", BOOK)
    upload(admin_client, "book.txt", HADITH_A.encode())

    assert store.count() == 1
    listing = admin_client.get("/api/sources").json()
    assert listing["total_files"] == 1
    assert listing["sources"][0]["chunks"] == 1


def test_failed_reupload_keeps_the_previous_version(admin_client, store):
    upload(admin_client, "book.txt", BOOK)
    res = upload(admin_client, "book.txt", b"   \n\n  ")  # nothing readable

    body = res.json()
    assert body["status"] == "ready"  # the old version is still searchable
    assert body["chunks"] == 2
    assert "بقيت النسخة السابقة" in body["error"]
    assert store.count() == 2
    assert admin_client.get(f"/api/sources/{body['id']}/download").content == BOOK


def test_structured_json_keeps_ruling_and_sanad(admin_client, store):
    records = [{
        "id": "1",
        "text": "إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ",
        "hukm": "صحيح",
        "mohaddith": "البخاري",
        "sanad": [{"name": "النبي ﷺ", "grade": "المصدر"}, {"name": "عمر بن الخطاب"}],
        "topic": "النية",
        "source": "صحيح البخاري",
    }]
    res = upload(admin_client, "hadiths.json", json.dumps(records).encode())

    assert res.json()["status"] == "ready", res.text
    assert res.json()["kind"] == "structured_hadith"
    [item] = store.query_by_topic("النية")
    assert text_index.texts([item["id"]])[item["id"]] == records[0]["text"]  # diacritics kept for display
    assert item["metadata"]["hukm"] == "صحيح"
    assert [n.name for n in parse(item["metadata"]["sanad"])] == ["النبي ﷺ", "عمر بن الخطاب"]


def test_invalid_structured_json_fails_with_reason(admin_client):
    body = upload(admin_client, "bad.json", b'[{"text": "no id"}]').json()
    assert body["status"] == "failed"
    assert "بنية الأحاديث" in body["error"]


def test_file_without_readable_text_fails(admin_client):
    body = upload(admin_client, "blank.txt", b"   \n\n  ").json()
    assert body["status"] == "failed"
    assert "نص مقروء" in body["error"]
    assert admin_client.get("/api/sources").json()["total_files"] == 0
    # A failed upload keeps no original file.
    assert admin_client.get(f"/api/sources/{body['id']}/download").status_code == 404


def test_default_limit_accepts_large_books():
    assert get_settings().max_upload_mb >= 60


def test_jobs_cut_off_by_a_restart_are_reported(admin_client):
    new_id = upload(admin_client, "new.txt", BOOK).json()["id"]
    old_id = upload(admin_client, "old.txt", BOOK).json()["id"]
    with connection() as conn:
        conn.execute("UPDATE sources SET status = 'processing', chunks = 0 WHERE id = ?", (new_id,))
        conn.execute("UPDATE sources SET status = 'processing' WHERE id = ?", (old_id,))

    sources.recover_interrupted()

    new, old = sources.get_source(new_id), sources.get_source(old_id)
    assert new.status == "failed" and "إعادة تشغيل" in new.error
    assert old.status == "ready"  # its previous version is still indexed


def test_progress_is_reported_through_every_stage(client, store, embedder):  # client: creates the app DB
    steps: list[str] = []
    ingest_file(BOOK, "book.txt", embedder, store, steps.append)
    assert steps[0] == "قراءة الملف"
    assert any(s.startswith("إنشاء التمثيلات الدلالية") for s in steps)
    assert steps[-1] == "الحفظ في قاعدة البيانات"


def test_delete_removes_chunks_file_and_record(admin_client, store):
    source_id = upload(admin_client, "book.txt", BOOK).json()["id"]

    assert admin_client.delete(f"/api/sources/{source_id}").status_code == 204
    assert store.count() == 0
    assert admin_client.get("/api/sources").json()["total_files"] == 0
    assert admin_client.get(f"/api/sources/{source_id}/download").status_code == 404
    assert admin_client.delete(f"/api/sources/{source_id}").status_code == 404
