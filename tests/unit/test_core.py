"""Unit tests: session tokens, the rate limiter, sanad strings and request validation."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core import rate_limit
from app.core.security import hash_password, hash_token, new_session_token, verify_password
from app.models.schemas import EventIn, HadithRecord, Narrator, SiteSearchRequest, SiteSettings
from app.services import sanad

# --- Passwords and tokens ---


@pytest.mark.parametrize("stored", [
    "",
    "not-a-hash",
    "bcrypt$1$2$3$aa$bb",  # another algorithm
    "scrypt$16384$8$1$zz$zz",  # not hex
    "scrypt$x$8$1$aa$bb",  # not a number
])
def test_malformed_stored_hashes_never_verify(stored):
    assert verify_password("anything", stored) is False


def test_hash_does_not_contain_the_password():
    stored = hash_password("very-secret-password")
    assert "very-secret-password" not in stored
    assert stored.startswith("scrypt$")


def test_session_tokens_are_random_and_stored_hashed():
    tokens = {new_session_token() for _ in range(100)}
    assert len(tokens) == 100
    token = next(iter(tokens))
    assert len(token) >= 40
    assert hash_token(token) != token and len(hash_token(token)) == 64
    assert hash_token(token) == hash_token(token)


# --- Rate limiter ---


def test_rate_limiter_allows_up_to_the_limit_per_key():
    limiter = rate_limit.RateLimiter(window_seconds=60)
    assert all(limiter.hit("1.1.1.1", limit=3) for _ in range(3))
    assert limiter.hit("1.1.1.1", limit=3) is False
    assert limiter.hit("2.2.2.2", limit=3) is True  # another visitor has their own count


def test_rate_limiter_window_slides(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.RateLimiter(window_seconds=60)
    assert limiter.hit("ip", limit=1)
    assert not limiter.hit("ip", limit=1)
    now[0] += 61
    assert limiter.hit("ip", limit=1)


def test_rate_limiter_forgets_idle_visitors(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.RateLimiter(window_seconds=1)
    for i in range(10_001):
        limiter.hit(f"ip-{i}", limit=5)
    now[0] += 5
    for i in range(10_001):  # all old hits expire; empty entries are dropped
        limiter.hit(f"ip-{i}", limit=5)
    limiter.hit("one-more", limit=5)
    assert len(limiter._hits) <= 10_002


def test_rate_limiter_forgets_addresses_seen_only_once(monkeypatch):
    """Made-up addresses, each used once, must not pile up in memory."""
    now = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    limiter = rate_limit.RateLimiter(window_seconds=1)
    for i in range(rate_limit.MAX_KEYS + 1):
        limiter.hit(f"fake-{i}", limit=5)
    now[0] += 5
    limiter.hit("next-visitor", limit=5)
    assert len(limiter._hits) == 1


# --- Sanad ---


def test_sanad_round_trip():
    chain = [Narrator(name="النبي ﷺ", grade="المصدر"), Narrator(name="أبو هريرة", grade="صحابي"),
             Narrator(name="راوٍ بلا درجة")]
    text = sanad.serialize(chain)
    assert text == "النبي ﷺ (المصدر) > أبو هريرة (صحابي) > راوٍ بلا درجة"
    assert sanad.parse(text) == chain


def test_sanad_parse_tolerates_empty_parts_and_parentheses_in_names():
    parsed = sanad.parse(" > عبد الله (بن عمر) (صحابي) >  ")
    assert parsed == [Narrator(name="عبد الله (بن عمر)", grade="صحابي")]
    assert sanad.parse("") == []


# --- Request validation ---


@pytest.mark.parametrize("payload", [
    {"query": ""},
    {"query": "x" * 2001},
    {"query": "نص", "top_k": 0},
    {"query": "نص", "top_k": 21},
])
def test_search_request_limits(payload):
    with pytest.raises(ValidationError):
        SiteSearchRequest(**payload)


def test_search_request_defaults():
    assert SiteSearchRequest(query="نص").top_k == 5


@pytest.mark.parametrize("payload", [
    {"type": "login"},
    {"type": "visit", "visitor_id": "x" * 201},
    {"type": "search", "latency_ms": -1},
    {"type": "search", "result": "x" * 51},
])
def test_event_validation(payload):
    with pytest.raises(ValidationError):
        EventIn(**payload)


@pytest.mark.parametrize(("url", "stored"), [
    ("https://isnad.example/", "https://isnad.example"),
    ("  http://localhost:8001  ", "http://localhost:8001"),
    ("", ""),
])
def test_site_url_is_normalized(url, stored):
    assert SiteSettings(main_site_url=url).main_site_url == stored


@pytest.mark.parametrize("url", ["ftp://isnad.example", "javascript:alert(1)", "isnad.example"])
def test_site_url_must_be_http(url):
    with pytest.raises(ValidationError):
        SiteSettings(main_site_url=url)


def test_site_messages_are_bounded():
    with pytest.raises(ValidationError):
        SiteSettings(announcement="x" * 501)


def test_hadith_record_needs_id_and_text():
    with pytest.raises(ValidationError):
        HadithRecord(id="", text="نص")
    with pytest.raises(ValidationError):
        HadithRecord(id="1", text="")
    assert HadithRecord(id="1", text="نص").sanad == []


# --- Settings defaults ---


def test_defaults_match_the_documented_choices(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DIMENSIONS", raising=False)  # set for the tests' fake embedder
    defaults = Settings(_env_file=None)
    assert defaults.embedding_model == "qwen/qwen3-embedding-4b"
    assert defaults.embedding_dimensions == 1024
    assert defaults.ocr_engine == "vision"
    assert defaults.ocr_languages == "ara"
    assert defaults.max_upload_mb == 100
    assert defaults.enable_api_docs is False


# --- Literal text normalisation (exact-quote search) ---

from app.services.text_index import normalize  # noqa: E402


def test_quotes_are_compared_without_diacritics_punctuation_or_letter_forms():
    assert normalize("«إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ»، وإنما لكل امرئٍ ما نوى.") == \
        normalize("انما الاعمال بالنيات وانما لكل امرئ ما نوي")
    assert normalize("الصلاةُ") == normalize("الصلاه")


from app.services.embeddings import QWEN3_QUERY_INSTRUCTION, query_instruction  # noqa: E402
from app.services.text_index import word_overlap  # noqa: E402


@pytest.mark.parametrize(("query", "text", "share"), [
    ("إنما الأعمال بالنيات", "حدثنا الحميدي قال سمعت رسول الله يقول إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ", 1.0),
    ("إنما الأعمال بالنية", "إنما الأعمال بالنيات", 0.6667),  # one word altered
    ("صوموا تصحوا", "السحر الأعلى في بيتي أو عندي إلا نائما", 0.0),  # sounds alike, shares nothing
    ("من في على", "أي نص", 0.0),  # only common words: nothing to compare
])
def test_word_overlap(query, text, share):
    assert word_overlap(query, text) == pytest.approx(share, abs=1e-3)


def test_query_instruction_is_only_for_qwen3_unless_configured(monkeypatch):
    settings = Settings(_env_file=None)
    assert query_instruction(settings.model_copy(update={"embedding_model": "qwen/qwen3-embedding-4b"})) == QWEN3_QUERY_INSTRUCTION
    assert query_instruction(settings.model_copy(update={"embedding_model": "openai/text-embedding-3-small"})) == ""
    assert query_instruction(settings.model_copy(update={"embedding_query_instruction": "-"})) == ""
    assert query_instruction(settings.model_copy(update={"embedding_query_instruction": "Query: "})) == "Query: "

