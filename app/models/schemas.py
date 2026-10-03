"""
Request and response models (Pydantic) shared by the API routes and services.

Field names mirror the metadata stored in ChromaDB
(see docs/hadith_format.example.json and app/services/ingestion.py).
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- Hadith data ---


class Narrator(BaseModel):
    """A single narrator in the sanad chain."""

    name: str
    grade: str | None = None


class HadithRecord(BaseModel):
    """One structured hadith, as uploaded in a JSON file."""

    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    hukm: str = ""
    mohaddith: str = ""
    sanad: list[Narrator] = Field(default_factory=list)
    topic: str = ""
    source: str = ""
    # The hadith's own words without its chain, when the edition marks them (Shamela does);
    # otherwise they are found by app/services/hadith_import.matn_of.
    matn: str = ""


# --- Admin accounts ---


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class AdminCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class AdminInfo(BaseModel):
    id: int
    username: str
    created_at: str = ""
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


# --- Uploaded sources ---


class SourceInfo(BaseModel):
    id: int
    filename: str
    kind: str  # "document" or "structured_hadith"
    size_bytes: int
    chunks: int
    characters: int
    ocr_pages: int = 0
    uploaded_by: str | None = None
    uploaded_at: str
    status: str = "ready"  # "processing", "ready" or "failed"
    progress: str | None = None
    error: str | None = None


class SourcesResponse(BaseModel):
    sources: list[SourceInfo] = Field(default_factory=list)
    total_files: int = 0
    total_chunks: int = 0


# --- Main website controls ---


class SiteSettings(BaseModel):
    """Read by the main website on every page load (via /api/v1/site-config)."""

    maintenance_mode: bool = False
    maintenance_message: str = Field(default="الموقع تحت الصيانة، نعود قريبًا بإذن الله", max_length=500)
    search_enabled: bool = True
    chat_enabled: bool = True
    announcement: str = Field(default="", max_length=500)
    # Used by the dashboard to check the main website is up (GET <url>/health).
    main_site_url: str = Field(default="", max_length=300)

    @field_validator("main_site_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("رابط الموقع يجب أن يبدأ بـ http:// أو https://")
        return value


# --- System status ---


class CheckResult(BaseModel):
    name: str
    # True = healthy, False = failing, None = not configured yet
    ok: bool | None
    detail: str
    latency_ms: int | None = None


class SystemStatus(BaseModel):
    checked_at: str
    checks: list[CheckResult]


# --- API for the main website (/api/v1) ---


class SiteSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SanadNode(BaseModel):
    """A narrator in an isnad tree; each path from the root to a leaf is one chain."""

    name: str
    grade: str | None = None
    children: list["SanadNode"] = Field(default_factory=list)


class SiteMatch(BaseModel):
    """One stored text close to the query, with everything the site needs to show it."""

    id: str
    text: str
    similarity: float = Field(..., ge=0.0, le=1.0)
    # Share of the query's meaningful words found in this text: high for a quote with a word
    # or two changed, near 0 for a different saying that merely sounds alike.
    word_overlap: float = Field(..., ge=0.0, le=1.0)
    kind: str  # "structured_hadith" or "document"
    hukm: str | None = None
    mohaddith: str | None = None
    sanad: list[Narrator] = Field(default_factory=list)
    # The chain(s) as a tree from the Prophet ﷺ to the compiler. Taken from the uploaded sanad,
    # or read from the narration's own wording (sanad_extracted), which the site must say.
    sanad_tree: SanadNode | None = None
    sanad_extracted: bool = False
    topic: str | None = None
    source: str | None = None
    # The book's compiler and his year of death, for one of the nine books (app/services/books.py)
    compiler: str | None = None


class SiteSearchResponse(BaseModel):
    matches: list[SiteMatch] = Field(default_factory=list)


class EventIn(BaseModel):
    """A visit, search or chat question, reported by the main website."""

    type: Literal["visit", "search", "chat"]
    # Any stable anonymous id for the visitor (e.g. a random cookie value).
    # It is hashed before storage; never send an IP address or name here.
    visitor_id: str = Field(default="", max_length=200)
    query: str = Field(default="", max_length=2000)
    # Outcome of a search, e.g. "verified" / "distorted" / "no_match"
    result: str = Field(default="", max_length=50)
    latency_ms: int | None = Field(default=None, ge=0, le=600_000)


# --- Reports ---


class DailyStat(BaseModel):
    day: str
    visits: int
    visitors: int
    searches: int
    chats: int


class CountItem(BaseModel):
    label: str
    count: int


class ReportSummary(BaseModel):
    date_from: str
    date_to: str
    visits: int
    unique_visitors: int
    searches: int
    chats: int
    avg_search_latency_ms: int | None
    daily: list[DailyStat]
    top_searches: list[CountItem]
    top_questions: list[CountItem]
    search_results: list[CountItem]
    files: int
    chunks: int
    uploads_in_period: int
