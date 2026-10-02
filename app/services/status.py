"""
System status checks shown on the dashboard: the databases, the embedding model,
OCR, the API keys and the main website.

Each check returns ok = True (healthy), False (failing) or None (not configured yet).
Network checks run in parallel with short timeouts so the page stays fast.
"""

import shutil
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings
from app.db.sqlite import connection
from app.models.schemas import CheckResult, SystemStatus
from app.services.embeddings import EmbeddingService
from app.services.site_settings import get_site_settings
from app.services.vector_store import VectorStore

HTTP_TIMEOUT = 6.0
MIN_SITE_KEY_LENGTH = 24
LOW_DISK_BYTES = 500 * 1024 * 1024


def _run(name: str, check: Callable[[], tuple[bool | None, str]]) -> CheckResult:
    started = time.perf_counter()
    try:
        ok, detail = check()
    except Exception as exc:  # a broken check must never break the page
        ok, detail = False, f"خطأ: {str(exc)[:200]}"
    return CheckResult(
        name=name, ok=ok, detail=detail, latency_ms=int((time.perf_counter() - started) * 1000)
    )


# --- Local checks ---


def _app_db() -> tuple[bool, str]:
    with connection() as conn:
        admins = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        files = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    return True, f"تعمل — {admins} مستخدم، {files} ملف مسجّل"


def _vector_db(store: VectorStore) -> Callable[[], tuple[bool, str]]:
    def check() -> tuple[bool, str]:
        problem = store.model_mismatch()
        if problem:
            return False, problem
        return True, f"تعمل — {store.count()} مقطع مفهرس"

    return check


def _embedding_model(
    embedder: EmbeddingService, store: VectorStore
) -> Callable[[], tuple[bool | None, str]]:
    def check() -> tuple[bool | None, str]:
        settings = get_settings()
        if not settings.openrouter_api_key:
            return None, "يحتاج OPENROUTER_API_KEY"
        # A few tokens — costs a fraction of a cent. encode() itself rejects a wrong vector size.
        dim = len(embedder.encode_one("اختبار"))
        stored = store.stored_dimensions()
        if stored is not None and stored != dim:
            return False, f"{settings.embedding_model} يعطي {dim} بُعدًا وقاعدة البيانات مبنية بـ{stored}"
        return True, f"{settings.embedding_model} يعمل — {dim} بُعدًا، مطابق لقاعدة البيانات"

    return check


def _ocr() -> tuple[bool, str]:
    settings = get_settings()
    fallback_ok, fallback = _tesseract()
    if settings.ocr_engine == "vision":
        if not settings.openrouter_api_key:
            if fallback_ok:
                return False, f"يحتاج OPENROUTER_API_KEY لنموذج الرؤية — تُستعمل {fallback} مؤقتًا بدقة أقل"
            return False, f"يحتاج OPENROUTER_API_KEY لنموذج الرؤية، و{fallback}"
        readers = settings.ocr_model + (f" + تحقق {settings.ocr_check_model}" if settings.ocr_check_model else "")
        backup = f"الاحتياطي: {fallback}" if fallback_ok else f"بلا احتياطي ({fallback})"
        return True, f"نموذج الرؤية {readers} — {backup}"
    return fallback_ok, fallback


def _tesseract() -> tuple[bool, str]:
    try:
        import pytesseract
    except ImportError:
        return False, "مكتبة pytesseract غير مثبتة"
    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        version = pytesseract.get_tesseract_version()
        languages = pytesseract.get_languages(config="")
    except pytesseract.TesseractNotFoundError:
        return False, "برنامج Tesseract غير مثبت"
    if "ara" not in languages:
        return False, f"Tesseract {version} مثبت بدون اللغة العربية"
    return True, f"Tesseract {version} مع العربية"


def _disk() -> tuple[bool, str]:
    folder = Path(get_settings().chroma_dir)
    folder.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(folder)
    free_gb = usage.free / 1024**3
    return usage.free > LOW_DISK_BYTES, f"المساحة الفارغة {free_gb:.1f} GB من {usage.total / 1024**3:.1f} GB"


def _site_api_key() -> tuple[bool | None, str]:
    key = get_settings().site_api_key
    if not key:
        return None, "SITE_API_KEY غير مضبوط — الموقع الأساسي لن يستطيع الاتصال"
    if len(key) < MIN_SITE_KEY_LENGTH:
        return False, f"المفتاح قصير ({len(key)} حرفًا) — استخدم {MIN_SITE_KEY_LENGTH} حرفًا على الأقل"
    return True, "مضبوط"


# --- Network checks ---


def _openrouter_key() -> tuple[bool | None, str]:
    settings = get_settings()
    if not settings.openrouter_api_key:
        return None, "OPENROUTER_API_KEY غير مضبوط"
    res = httpx.get(
        f"{settings.openrouter_base_url}/key",
        headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        timeout=HTTP_TIMEOUT,
    )
    if res.status_code == 401:
        return False, "المفتاح غير صالح أو ملغى"
    res.raise_for_status()
    data = res.json().get("data", {})
    usage = data.get("usage")
    limit = data.get("limit")
    parts = ["صالح"]
    if usage is not None:
        parts.append(f"الاستهلاك ${usage:.4f}")
    if limit is not None:
        parts.append(f"الحد ${limit:.2f}")
        remaining = data.get("limit_remaining")
        if remaining is not None and remaining <= 0:
            return False, "صالح لكن الرصيد انتهى — " + " · ".join(parts[1:])
    return True, " · ".join(parts)


def _main_site() -> tuple[bool | None, str]:
    site = get_site_settings()
    if not site.main_site_url:
        return None, "رابط الموقع الأساسي غير مضبوط — أضفه من خانة التحكم بالموقع"
    res = httpx.get(f"{site.main_site_url}/health", timeout=HTTP_TIMEOUT, follow_redirects=True)
    mode = " (وضع الصيانة مفعّل)" if site.maintenance_mode else ""
    if res.status_code == 200:
        return True, f"يعمل — {site.main_site_url}{mode}"
    return False, f"استجاب بالرمز {res.status_code}{mode}"


def check_all(embedder: EmbeddingService, store: VectorStore) -> SystemStatus:
    # Local checks run one after another: they are fast, and loading libraries such as
    # numpy from several threads at once can fail with a "partially initialized module" error.
    local = [
        ("قاعدة بيانات التطبيق", _app_db),
        ("قاعدة البيانات المتجهية", _vector_db(store)),
        ("قراءة الملفات الممسوحة (OCR)", _ocr),
        ("مساحة التخزين", _disk),
        ("مفتاح الموقع الأساسي (SITE_API_KEY)", _site_api_key),
    ]
    # Network checks wait on other services, so they run in parallel.
    remote = [
        ("نموذج التمثيلات الدلالية", _embedding_model(embedder, store)),
        ("مفتاح OpenRouter", _openrouter_key),
        ("الموقع الأساسي", _main_site),
    ]
    results = {name: _run(name, check) for name, check in local}
    with ThreadPoolExecutor(max_workers=len(remote)) as pool:
        results.update(zip([n for n, _ in remote], pool.map(lambda c: _run(*c), remote), strict=False))

    order = ["قاعدة بيانات التطبيق", "قاعدة البيانات المتجهية", "نموذج التمثيلات الدلالية",
             "قراءة الملفات الممسوحة (OCR)", "مساحة التخزين", "مفتاح الموقع الأساسي (SITE_API_KEY)",
             "مفتاح OpenRouter", "الموقع الأساسي"]
    return SystemStatus(
        checked_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        checks=[results[name] for name in order],
    )
