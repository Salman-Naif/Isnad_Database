"""API tests: the sources endpoints (list, status, download, delete) and upload validation."""

from app.config import get_settings
from app.db.sqlite import connection

HADITH_A = "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى فمن كانت هجرته إلى الله ورسوله"


HADITH_B = "من حسن إسلام المرء تركه ما لا يعنيه من القول والعمل في كل حال"


BOOK = f"{HADITH_A}\n\n{HADITH_B}".encode()


def upload(client, name: str, data: bytes):
    return client.post("/api/sources", files={"file": (name, data)})


def test_unsupported_type_rejected(admin_client):
    assert upload(admin_client, "virus.exe", b"MZ").status_code == 415


def test_empty_file_rejected(admin_client):
    assert upload(admin_client, "empty.txt", b"").status_code == 400


def test_size_limit(admin_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    big = ("نص عربي " * 200_000).encode()  # ~2.8 MB
    assert upload(admin_client, "big.txt", big).status_code == 413
    assert admin_client.get("/api/sources").json()["sources"] == []


def test_single_file_status_endpoint(admin_client):
    source_id = upload(admin_client, "book.txt", BOOK).json()["id"]
    assert admin_client.get(f"/api/sources/{source_id}").json()["status"] == "ready"
    assert admin_client.get("/api/sources/9999").status_code == 404


def test_list_shows_uploaded_files(admin_client):
    upload(admin_client, "book.txt", BOOK)
    upload(admin_client, "second.txt", HADITH_B.encode())

    listing = admin_client.get("/api/sources").json()
    assert listing["total_files"] == 2
    assert listing["total_chunks"] == 3
    assert {s["filename"] for s in listing["sources"]} == {"book.txt", "second.txt"}


def test_download_returns_the_original_file(admin_client):
    source_id = upload(admin_client, "صحيح.txt", BOOK).json()["id"]

    res = admin_client.get(f"/api/sources/{source_id}/download")
    assert res.status_code == 200
    assert res.content == BOOK
    assert "attachment" in res.headers["content-disposition"]


def test_file_being_processed_cannot_be_replaced_or_deleted(admin_client):
    source_id = upload(admin_client, "book.txt", BOOK).json()["id"]
    with connection() as conn:
        conn.execute("UPDATE sources SET status = 'processing' WHERE id = ?", (source_id,))

    assert upload(admin_client, "book.txt", BOOK).status_code == 409
    assert admin_client.delete(f"/api/sources/{source_id}").status_code == 409
