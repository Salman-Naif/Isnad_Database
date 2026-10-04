"""API tests: the endpoints the main website calls (/api/v1)."""

import json

from app.db.sqlite import connection

HADITH = {
    "id": "1",
    "text": "إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ وَإِنَّمَا لِكُلِّ امْرِئٍ مَا نَوَى",
    "hukm": "صحيح",
    "mohaddith": "البخاري",
    "sanad": [{"name": "النبي ﷺ", "grade": "المصدر"}, {"name": "عمر بن الخطاب"}],
    "topic": "النية",
    "source": "صحيح البخاري",
}


def index_hadith(admin_client):
    res = admin_client.post(
        "/api/sources", files={"file": ("hadiths.json", json.dumps([HADITH]).encode())}
    )
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "ready"


def test_search_returns_ruling_and_sanad(admin_client, site_headers):
    index_hadith(admin_client)
    res = admin_client.post(
        "/api/v1/search",
        headers=site_headers,
        json={"query": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", "top_k": 3},
    )

    assert res.status_code == 200, res.text
    [match] = res.json()["matches"]
    assert match["text"] == HADITH["text"]
    assert match["similarity"] > 0.9
    assert match["kind"] == "structured_hadith"
    assert match["hukm"] == "صحيح"
    assert match["source"] == "صحيح البخاري"
    assert [n["name"] for n in match["sanad"]] == ["النبي ﷺ", "عمر بن الخطاب"]
    assert match["sanad_tree"]["name"] == "النبي ﷺ"
    assert match["sanad_tree"]["children"][0]["name"] == "عمر بن الخطاب"


def test_search_reads_the_isnad_from_the_narration(admin_client, site_headers):
    narration = {
        "id": "7", "source": "جامع الترمذي", "sanad": [],
        "text": "حدثنا قتيبة بن سعيد، حدثنا أبو عوانة، عن سماك بن حرب، ح وحدثنا هناد، حدثنا وكيع، عن "
                "إسرائيل، عن سماك، عن مصعب بن سعد، عن ابن عمر، عن النبي صلى الله عليه وسلم قال "
                "لا تقبل صلاة بغير طهور ولا صدقة من غلول",
    }
    res = admin_client.post("/api/sources", files={"file": ("t.json", json.dumps([narration]).encode())})
    assert res.json()["status"] == "ready", res.text

    [match] = admin_client.post("/api/v1/search", headers=site_headers,
                                json={"query": "لا تقبل صلاة بغير طهور", "top_k": 1}).json()["matches"]

    assert match["sanad_extracted"] is True
    tree = match["sanad_tree"]
    assert tree["name"] == "النبي ﷺ"
    [companion] = tree["children"]
    assert companion["name"] == "ابن عمر"
    simak = companion["children"][0]["children"][0]
    assert simak["name"] == "سماك"  # both chains meet here
    assert len(simak["children"]) == 2


def test_search_on_empty_database(client, site_headers):
    res = client.post("/api/v1/search", headers=site_headers, json={"query": "نص"})
    assert res.json() == {"matches": []}


def test_blank_search_rejected(client, site_headers):
    assert client.post("/api/v1/search", headers=site_headers, json={"query": "   "}).status_code == 422


def test_topics(admin_client, site_headers):
    index_hadith(admin_client)
    assert admin_client.get("/api/v1/topics", headers=site_headers).json() == [
        {"name": "النية", "count": 1}
    ]


def test_site_config_defaults(client, site_headers):
    config = client.get("/api/v1/site-config", headers=site_headers).json()
    assert config["maintenance_mode"] is False
    assert config["search_enabled"] is True and config["chat_enabled"] is True


def test_controls_saved_in_dashboard_reach_the_site(admin_client, site_headers):
    settings = {
        "maintenance_mode": True,
        "maintenance_message": "صيانة قصيرة",
        "search_enabled": True,
        "chat_enabled": False,
        "announcement": "تم تحديث المصادر",
        "main_site_url": "https://isnad.example.com/",
    }
    assert admin_client.put("/api/site-settings", json=settings).status_code == 200

    config = admin_client.get("/api/v1/site-config", headers=site_headers).json()
    assert config["maintenance_mode"] is True
    assert config["chat_enabled"] is False
    assert config["announcement"] == "تم تحديث المصادر"
    assert config["main_site_url"] == "https://isnad.example.com"  # trailing slash trimmed


def test_invalid_site_url_rejected(admin_client):
    res = admin_client.put("/api/site-settings", json={"main_site_url": "isnad.example.com"})
    assert res.status_code == 422


def test_events_are_recorded_with_hashed_visitor(client, site_headers):
    for event in [
        {"type": "visit", "visitor_id": "visitor-123"},
        {"type": "search", "visitor_id": "visitor-123", "query": "إنما الأعمال", "result": "verified", "latency_ms": 180},
        {"type": "chat", "visitor_id": "visitor-123", "query": "ما حكمه؟"},
    ]:
        assert client.post("/api/v1/events", headers=site_headers, json=event).status_code == 204

    with connection() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    assert [r["type"] for r in rows] == ["visit", "search", "chat"]
    assert rows[1]["result"] == "verified" and rows[1]["latency_ms"] == 180
    # The raw visitor id is never stored; the same visitor gets the same hash.
    assert {r["visitor_hash"] for r in rows} != {"visitor-123"}
    assert len({r["visitor_hash"] for r in rows}) == 1


def test_unknown_event_type_rejected(client, site_headers):
    res = client.post("/api/v1/events", headers=site_headers, json={"type": "purchase"})
    assert res.status_code == 422


def test_a_book_uploaded_under_an_old_name_is_shown_under_its_published_title(admin_client, site_headers):
    """Texts indexed as «موطأ مالك» before the book list existed come back as «موطأ الإمام مالك»."""
    record = {"id": "m1", "source": "موطأ مالك", "sanad": [],
              "text": "حدثني يحيى عن مالك عن نافع عن عبد الله بن عمر أن رسول الله صلى الله عليه وسلم "
                      "نهى عن بيع الثمار حتى يبدو صلاحها"}
    res = admin_client.post("/api/sources", files={"file": ("m.json", json.dumps([record]).encode())})
    assert res.json()["status"] == "ready", res.text

    [match] = admin_client.post("/api/v1/search", headers=site_headers,
                                json={"query": "نهى عن بيع الثمار حتى يبدو صلاحها", "top_k": 1}).json()["matches"]
    assert match["source"] == "موطأ الإمام مالك"
    assert match["compiler"] == "الإمام أبو عبد الله مالك بن أنس الأصبحي (ت 179هـ)"


def test_a_vector_without_its_stored_text_is_not_returned(admin_client, site_headers):
    # A write cut off by a restart can leave vectors whose texts were never stored
    index_hadith(admin_client)
    with connection() as conn:
        conn.execute("DELETE FROM passages_fts")
        conn.execute("DELETE FROM passages")
    res = admin_client.post("/api/v1/search", headers=site_headers,
                            json={"query": "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى", "top_k": 3})
    assert res.status_code == 200 and res.json()["matches"] == []
