"""
Settings for the Isnad database service, read from environment variables
(.env locally, or Variables on Railway).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Identity ---
    app_name: str = "Isnad"

    # --- API keys ---
    # Key the main Isnad website sends (X-API-Key header) to read from this database
    # and to report visits and questions. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    site_api_key: str = ""
    # OpenRouter: this service uses it for embeddings and for reading scanned pages (OCR).
    # (The chat model belongs to the main website — see the Isnad_app repository.)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # --- User accounts ---
    # Default user, created on startup only while the database has no users at all
    # (i.e. on the very first deploy). Its password is marked as "must change": the
    # dashboard keeps asking until it is changed. Override both on Railway if you like.
    admin_username: str = "salman"
    admin_password: str = "123456"  # noqa: S105 — documented first-login default, must be changed
    session_hours: int = 12
    login_attempts_per_15_minutes: int = 10
    # Per account, whatever address the attempts claim to come from
    login_attempts_per_account_per_15_minutes: int = 20
    # The interactive API docs (/docs) list every endpoint. Off unless needed locally.
    enable_api_docs: bool = False

    # --- Storage (everything lives under one folder = one Railway Volume) ---
    chroma_dir: str = str(BASE_DIR / "chroma_db")
    collection_name: str = "isnad_hadiths"
    # Admin accounts, sessions, uploaded-file registry, site settings, visit/question stats
    sqlite_path: str = str(BASE_DIR / "chroma_db" / "isnad.db")
    # Original uploaded files, kept so admins can download them again
    uploads_dir: str = str(BASE_DIR / "chroma_db" / "uploads")

    # --- Embedding model (OpenRouter API — nothing runs locally) ---
    # Chosen after comparing 17 embedding models on OpenRouter with hadiths from Bukhari,
    # Muslim, Tirmidhi and Ibn Majah: it found every reworded hadith first, with the widest
    # gap to the next-best wrong passage, for $0.02 / 1M tokens.
    # Changing it later requires re-uploading all sources (vectors aren't comparable).
    embedding_model: str = "qwen/qwen3-embedding-4b"
    # Length of every vector, asked of the model (Qwen3 and OpenAI text-embedding-3 can give
    # fewer than their full size: qwen3-embedding-4b up to 2560). 1024 matched 2560 on hadith
    # search (the right hadith first in 80/80 quotes, 79/80 altered quotes — measured on
    # Bukhari) with 2.5× less memory and storage. Every vector is checked against it and the
    # vector database records it, so indexed passages and search queries always match.
    embedding_dimensions: int = 1024
    # Qwen3 embeddings are instruction-aware: a search query embedded after a one-line task
    # description is matched more sharply (measured on 50,000 hadith vectors: paraphrases in
    # a visitor's own words found at a median 0.79 instead of 0.73). Stored passages are
    # embedded without it. Empty = the built-in instruction for Qwen3 models, none otherwise;
    # set "-" to turn it off.
    embedding_query_instruction: str = ""
    # Longer inputs are cut before embedding (the stored text stays whole). ~6000 Arabic
    # characters stay well inside the model's input limit; normal passages are ~400.
    embedding_max_input_chars: int = 6000
    # Passages per request, and requests at the same time. Measured on hadith collections:
    # the provider returns ~70-80 passages a second whatever the split; 64 × 8 was the
    # fastest, and 2-4× faster than one request at a time.
    embedding_batch_size: int = 64
    embedding_concurrency: int = 8
    embedding_timeout_seconds: float = 60.0

    # --- Document ingestion ---
    # Passages of ~400 Arabic characters: about one hadith each, so a search matches
    # the specific narration rather than a whole page.
    chunk_max_chars: int = 400
    chunk_overlap_chars: int = 60
    # Passages with fewer letters (or fewer than two words) are dropped as extraction junk.
    chunk_min_letters: int = 8
    # Large books are fine: files are streamed to disk and processed in the background.
    max_upload_mb: int = 100

    # --- OCR (scanned PDFs and images) ---
    # "vision": a vision model on OpenRouter reads the pages (near-exact on printed Arabic
    # books, ~$0.005-0.01 per page with the second reading). "tesseract": free and local,
    # but it loses words and misreads names on dense, fully vowelled hadith pages.
    # Without OPENROUTER_API_KEY, Tesseract is used whatever this says.
    ocr_engine: str = "vision"
    # Main reader. Chosen by comparing OpenRouter's vision models on pages of Bukhari,
    # Muslim, Tirmidhi and Ibn Majah: the most faithful reading for its price.
    ocr_model: str = "google/gemini-3-flash-preview"
    # Independent second reading of every column; empty turns it off (half the cost, and
    # a skipped line or misread word then goes unnoticed).
    ocr_check_model: str = "google/gemini-3.1-flash-lite"
    # Reads a column a third time when the first two disagree; the majority wins.
    ocr_referee_model: str = "google/gemini-3.8-flash"
    # Pages read at the same time. Higher is faster, within OpenRouter's rate limits.
    ocr_concurrency: int = 12
    ocr_timeout_seconds: float = 180.0
    # Resolution scanned PDF pages are rendered at for OCR.
    ocr_dpi: int = 300
    # Tesseract (fallback, or OCR_ENGINE=tesseract). Leave tesseract_cmd empty when
    # tesseract is on PATH (e.g. in Docker).
    # Windows example: C:\Program Files\Tesseract-OCR\tesseract.exe
    tesseract_cmd: str = ""
    # Arabic only: with "+eng" Tesseract reads Arabic glyphs as English words ("BE gall")
    # and Arabic-Indic digits as letters (٧٧ → "VY"). Hadith sources are Arabic.
    ocr_languages: str = "ara"

    # --- Reports ---
    # TTF font with Arabic glyphs for PDF reports. Empty = auto-detect
    # (Noto Naskh Arabic in Docker, Tahoma/Arial on Windows).
    report_font_path: str = ""
    # Events are stored in UTC; reports group them by day in this offset (Saudi Arabia = +3).
    report_utc_offset_hours: int = 3

    # --- Logging ---
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Single settings instance reused everywhere."""
    return Settings()
