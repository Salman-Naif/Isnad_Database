"""System tests: the database service as deployed — a real process, real HTTP, real files.

The tests follow one story, in order, on one running service: first start → the owner signs
in and replaces the default password → uploads a text book, a scanned page and structured
hadiths → the main website searches them and reports visits → reports are exported → the
service restarts and everything is still there.
"""

import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.system.conftest import OWNER, OWNER_PASSWORD
from tests.system.stub_openrouter import OCR_TEXT

NEW_PASSWORD = "a-strong-new-password"
HADITHS = [
    {"id": "b1", "text": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", "hukm": "صحيح",
     "mohaddith": "البخاري ومسلم", "sanad": [{"name": "عمر بن الخطاب", "grade": "صحابي"}],
     "topic": "النية", "source": "صحيح البخاري"},
    {"id": "b2", "text": "من حسن إسلام المرء تركه ما لا يعنيه", "hukm": "حسن",
     "mohaddith": "الترمذي", "topic": "الأخلاق", "source": "جامع الترمذي"},
]
BOOK = "باب الصلاة\n\nمن صلى البردين دخل الجنة\n\nالطهور شطر الإيمان والحمد لله تملأ الميزان"


def scanned_page() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("L", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    for y in range(200, 1400, 60):
        for x in range(150, 1050, 140):
            draw.rectangle((x, y, x + 110, y + 28), fill="black")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def sign_in(browser, password):
    return browser.post("/api/auth/login", json={"username": OWNER, "password": password})


def wait_until_processed(browser, source_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = browser.get(f"/api/sources/{source_id}").json()
        if row["status"] != "processing":
            return row
        time.sleep(0.3)
    raise AssertionError(f"source {source_id} still processing after {timeout}s")


def test_first_start_serves_only_the_login_and_health(browser):
    assert browser.get("/health").json() == {"status": "ok"}
    assert browser.get("/", follow_redirects=False).headers["location"] == "/login"
    login = browser.get("/login")
    assert login.status_code == 200 and "text/html" in login.headers["content-type"]
    assert "content-security-policy" in login.headers
    assert browser.get("/static/js/login.js").status_code == 200
    assert browser.get("/api/sources").status_code == 401


def test_default_owner_must_replace_the_default_password(browser):
    res = sign_in(browser, OWNER_PASSWORD)
    assert res.status_code == 200 and res.json()["must_change_password"] is True
    change = browser.post("/api/auth/change-password",
                          json={"current_password": OWNER_PASSWORD, "new_password": NEW_PASSWORD})
    assert change.status_code == 204
    assert browser.get("/api/auth/me").json()["must_change_password"] is False
    # The old password no longer works anywhere.
    browser.post("/api/auth/logout")
    assert sign_in(browser, OWNER_PASSWORD).status_code == 401


@pytest.fixture
def owner(browser):
    assert sign_in(browser, NEW_PASSWORD).status_code == 200
    return browser


def test_owner_uploads_every_kind_of_source(owner, openrouter):
    files = {
        "كتاب الصلاة.txt": BOOK.encode("utf-8"),
        "صفحة ممسوحة.png": scanned_page(),
        "أحاديث.json": json.dumps(HADITHS, ensure_ascii=False).encode("utf-8"),
    }
    rows = {}
    for name, data in files.items():
        res = owner.post("/api/sources", files={"file": (name, data)})
        assert res.status_code == 202, res.text
        rows[name] = wait_until_processed(owner, res.json()["id"])

    for name, row in rows.items():
        assert row["status"] == "ready" and row["error"] is None, (name, row)
    assert rows["صفحة ممسوحة.png"]["ocr_pages"] == 1
    assert rows["أحاديث.json"]["kind"] == "structured_hadith" and rows["أحاديث.json"]["chunks"] == 2
    # The scanned page went to the vision model, read twice (main model + check model).
    assert openrouter.paths().count("/chat/completions") >= 2
    listing = owner.get("/api/sources").json()
    assert listing["total_files"] == 3


def test_the_original_files_can_be_downloaded(owner):
    [book] = [s for s in owner.get("/api/sources").json()["sources"] if s["filename"] == "كتاب الصلاة.txt"]
    res = owner.get(f"/api/sources/{book['id']}/download")
    assert res.status_code == 200 and res.content == BOOK.encode("utf-8")


def test_the_website_finds_hadiths_with_their_ruling(website):
    res = website.post("/search", json={"query": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", "top_k": 3})
    assert res.status_code == 200
    best = res.json()["matches"][0]
    assert best["hukm"] == "صحيح" and best["similarity"] > 0.99
    assert best["sanad"] == [{"name": "عمر بن الخطاب", "grade": "صحابي"}]


def test_the_website_finds_text_from_books_and_scans(website):
    book = website.post("/search", json={"query": "من صلى البردين دخل الجنة"}).json()["matches"][0]
    assert book["source"] == "كتاب الصلاة.txt"
    scan = website.post("/search", json={"query": OCR_TEXT}).json()["matches"][0]
    assert scan["source"] == "صفحة ممسوحة.png"


def test_many_searches_at_once(website):
    queries = [h["text"] for h in HADITHS] * 10
    with ThreadPoolExecutor(10) as pool:
        codes = list(pool.map(lambda q: website.post("/search", json={"query": q}).status_code, queries))
    assert codes == [200] * len(queries)


def test_dashboard_controls_reach_the_website(owner, website):
    settings = owner.get("/api/site-settings").json()
    owner.put("/api/site-settings", json={**settings, "maintenance_mode": True, "announcement": "تحديث"})
    config = website.get("/site-config").json()
    assert config["maintenance_mode"] is True and config["announcement"] == "تحديث"
    owner.put("/api/site-settings", json={**settings, "maintenance_mode": False})


def test_visits_and_searches_feed_the_reports(owner, website):
    for i in range(3):
        website.post("/events", json={"type": "visit", "visitor_id": f"visitor-{i % 2}"})
    website.post("/events", json={"type": "search", "visitor_id": "visitor-0", "query": "النية",
                                  "result": "verified", "latency_ms": 120})
    summary = owner.get("/api/reports/summary").json()
    assert summary["visits"] == 3 and summary["unique_visitors"] == 2 and summary["searches"] == 1
    assert summary["top_searches"] == [{"label": "النية", "count": 1}]
    for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF")):
        res = owner.get(f"/api/reports/export?format={fmt}")
        assert res.status_code == 200 and res.content.startswith(magic)


def test_status_page_checks_the_live_services(owner):
    checks = {c["name"]: c for c in owner.get("/api/status").json()["checks"]}
    assert checks["قاعدة بيانات التطبيق"]["ok"] is True
    assert checks["قاعدة البيانات المتجهية"]["ok"] is True
    assert checks["نموذج التمثيلات الدلالية"]["ok"] is True  # a real call to the stub API
    assert checks["مفتاح OpenRouter"]["ok"] is True


def test_everything_survives_a_restart(service, browser, website):
    service.restart()
    assert sign_in(browser, NEW_PASSWORD).status_code == 200
    assert browser.get("/api/sources").json()["total_files"] == 3
    best = website.post("/search", json={"query": "من حسن إسلام المرء تركه ما لا يعنيه"}).json()["matches"][0]
    assert best["hukm"] == "حسن"
    assert browser.get("/api/reports/summary").json()["visits"] == 3


def test_deleting_a_source_removes_it_from_search(owner, website):
    [book] = [s for s in owner.get("/api/sources").json()["sources"] if s["filename"] == "كتاب الصلاة.txt"]
    assert owner.delete(f"/api/sources/{book['id']}").status_code == 204
    matches = website.post("/search", json={"query": "من صلى البردين دخل الجنة", "top_k": 20}).json()["matches"]
    assert all(m["source"] != "كتاب الصلاة.txt" for m in matches)
