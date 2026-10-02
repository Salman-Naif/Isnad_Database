"""
OCR for scanned pages: images and PDF pages without a usable text layer.

Engines
  - "vision" (default): a vision language model through OpenRouter transcribes the page.
    On printed hadith books (two columns, full diacritics) it is near-exact, where
    Tesseract loses words, mixes columns and misreads names.
  - "tesseract": the local open-source engine. Used on its own when OCR_ENGINE=tesseract
    or no OpenRouter key is set, and as the fallback when the vision model can't be reached.

How a page is read (vision)
  1. Layout: the page is straightened, the running header is cut off, and a two-column
     page is split at its gutter, so every image the model sees is a single column read top
     to bottom (text running across both columns — titles, footnotes — stays whole, in its
     place). Whole-page reading of two-column books was the main source of errors (a
     skipped line, columns interleaved); column by column, independent models agree on
     99.8-100% of the words.
  2. Double reading: each column is read by OCR_MODEL and, independently, by
     OCR_CHECK_MODEL. If the two readings agree, OCR_MODEL's text is kept.
  3. Referee: if they disagree (a phrase missing from one of them, or too many different
     words), OCR_REFEREE_MODEL reads the column too and the majority wins. If no two of the
     three agree, the page is reported for review.
"""

import base64
import difflib
import io
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class OcrUnavailable(Exception):
    """No OCR engine could read the image (Tesseract missing and vision model unreachable)."""


# --- Page layout ---

# A pixel darker than this (0-255) counts as ink.
INK_THRESHOLD = 128
# Skew correction: angles tried (degrees), and the smallest one worth rotating for.
DESKEW_MAX_ANGLE = 3.0
DESKEW_STEP = 0.25
DESKEW_MIN_ANGLE = 0.3
# The running header sits above a horizontal rule in the top part of the page.
HEADER_ZONE = 0.15
# A rule is solid ink along most of the width; a line of text, even its dense baseline,
# is broken by the gaps between words and letters.
HEADER_RULE_SEGMENT = 25  # px
HEADER_RULE_MIN_SOLID = 0.6  # share of segments that are solid ink
# The gutter between two columns is looked for in the middle of the page, in its upper
# three quarters (full-width footnotes at the bottom would hide it)...
GUTTER_ZONE = (0.3, 0.7)
GUTTER_PROBE_HEIGHT = 0.75
# ...as a vertical strip with (almost) no ink, possibly with a thin rule down its middle.
GUTTER_MAX_INK_RATIO = 0.25  # of the typical ink density of text columns
GUTTER_MIN_WIDTH = 0.004  # of the page width (≈ 8 px at 300 DPI)
GUTTER_RULE_MAX_WIDTH = 0.01  # a rule this thin inside the gutter doesn't break it
GUTTER_RULE_CLEARANCE = 0.004  # columns this close to the rule are not used to spot crossings
# Text crossing the gutter for at least this share of the page height is a full-width
# block (a title across both columns, footnotes); shorter crossings are specks.
SPAN_MIN_HEIGHT = 0.004
SPAN_MERGE_GAP = 0.02  # lines of one full-width block are this close together
# An image with less ink than this is blank (no request is sent for it).
BLANK_MAX_INK = 0.002


def _ink_mask(gray):
    return gray.point(lambda v: 255 if v < INK_THRESHOLD else 0)


def _profile(mask, axis: str) -> list[float]:
    """Share of ink per column ("x") or per row ("y"), averaged by PIL's box filter."""
    from PIL import Image

    size = (mask.width, 1) if axis == "x" else (1, mask.height)
    return [v / 255 for v in mask.resize(size, Image.BOX).tobytes()]


def ink_share(image) -> float:
    mask = _ink_mask(image.convert("L"))
    return sum(_profile(mask, "y")) / max(1, mask.height)


def deskew(gray):
    """Straighten a page scanned at a slight angle: lines of text then fall on pixel rows,
    which the column detection and the OCR both need."""
    from PIL import Image

    small = _ink_mask(gray.resize((600, max(1, round(600 * gray.height / gray.width)))))

    def sharpness(angle: float) -> float:
        rows = _profile(small.rotate(angle, resample=Image.NEAREST, fillcolor=0), "y")
        mean = sum(rows) / len(rows)
        return sum((r - mean) ** 2 for r in rows)

    steps = int(DESKEW_MAX_ANGLE / DESKEW_STEP)
    angles = [i * DESKEW_STEP for i in range(-steps, steps + 1)]
    best = max(angles, key=lambda a: (sharpness(a), -abs(a)))
    if abs(best) < DESKEW_MIN_ANGLE:
        return gray
    return gray.rotate(best, resample=Image.BICUBIC, fillcolor=255)


def text_regions(image) -> list:
    """The page's text as images in reading order, each a single column.

    A two-column page becomes [right column, left column]; a full-width block (a title
    across both columns, footnotes) stays whole, in its place. The running header is
    removed. A page with no gutter is returned as one image.
    """
    gray = deskew(image.convert("L"))
    mask = _ink_mask(gray)
    width, height = gray.size

    top = _header_bottom(mask)
    if top:
        gray, mask = gray.crop((0, top, width, height)), mask.crop((0, top, width, height))
    height = gray.height

    probe = _profile(mask.crop((0, 0, width, int(height * GUTTER_PROBE_HEIGHT))), "x")
    gutter = _find_gutter(probe, width)
    if gutter is None:
        return [gray]

    regions = []
    for y0, y1, full_width in _bands(mask, probe, gutter):
        if full_width:
            regions.append(gray.crop((0, y0, width, y1)))
        else:
            split = (gutter[0] + gutter[1]) // 2
            # Arabic reads right to left: the right-hand column comes first.
            regions.append(gray.crop((split, y0, width, y1)))
            regions.append(gray.crop((0, y0, split, y1)))
    return regions


def _header_bottom(mask) -> int:
    """The y just below the running header's rule, or 0 when the page has none."""
    from PIL import Image, ImageChops

    zone = mask.crop((0, 0, mask.width, int(mask.height * HEADER_ZONE)))
    # Thicken vertically: a thin rule left slightly slanted by the scan still fills a row.
    thick = zone
    for dy in (-3, -2, -1, 1, 2, 3):
        thick = ImageChops.lighter(thick, ImageChops.offset(zone, 0, dy))
    zone = thick
    segments = max(1, zone.width // HEADER_RULE_SEGMENT)
    solid = zone.resize((segments, zone.height), Image.BOX).tobytes()
    bottom = 0
    for y in range(zone.height):
        row = solid[y * segments:(y + 1) * segments]
        if sum(v > 245 for v in row) / segments >= HEADER_RULE_MIN_SOLID:
            bottom = y + 1
    return bottom


def _find_gutter(columns: list[float], width: int) -> tuple[int, int] | None:
    """(first, last) x of the blank strip between two columns, or None."""
    body = sorted(columns[int(width * 0.1):int(width * 0.9)])
    typical = body[len(body) // 2] if body else 0
    if typical <= 0:
        return None
    limit = max(0.003, typical * GUTTER_MAX_INK_RATIO)

    lo, hi = int(width * GUTTER_ZONE[0]), int(width * GUTTER_ZONE[1])
    runs: list[list[int]] = []  # [start, end] of blank strips, merged across thin rules
    for x in range(lo, hi):
        if columns[x] >= limit:
            continue
        if runs and x - runs[-1][1] <= max(2, int(width * GUTTER_RULE_MAX_WIDTH)):
            runs[-1][1] = x
        else:
            runs.append([x, x])
    if not runs:
        return None
    start, end = max(runs, key=lambda r: r[1] - r[0])
    if end - start < width * GUTTER_MIN_WIDTH:
        return None
    # Both sides must hold text; otherwise it's a margin, not a gutter.
    left, right = columns[:start], columns[end + 1:]
    if sum(left) / max(1, len(left)) < limit or sum(right) / max(1, len(right)) < limit:
        return None
    return start, end


def _bands(mask, probe: list[float], gutter: tuple[int, int]) -> list[tuple[int, int, bool]]:
    """Split the page top to bottom into (y0, y1, full_width) bands: two-column stretches,
    and full-width blocks where text runs across the gutter."""
    start, end = gutter
    # The cleanest columns of the gutter (not its rule, not stray ends of long lines).
    floor = min(probe[start:end + 1])
    blank = [x for x in range(start, end + 1) if probe[x] <= floor + 0.002]
    # Stay clear of the rule: ink bleeding from it would look like text crossing the gutter.
    rule = [x for x in range(start, end + 1) if x not in blank]
    clearance = max(3, int(mask.width * GUTTER_RULE_CLEARANCE))
    blank = [x for x in blank if all(abs(x - r) > clearance for r in rule)] or blank
    middle = (start + end) / 2
    height = mask.height
    # Ink per row in the blank columns on each side of the gutter's middle. Text running
    # across the gutter inks both sides; a rule drifting on a slanted scan touches one.
    sides = ([0] * height, [0] * height)
    for x in blank:
        side = sides[0] if x < middle else sides[1]
        for y, v in enumerate(mask.crop((x, 0, x + 1, height)).tobytes()):
            if v:
                side[y] += 1
    crossing = [min(left, right) for left, right in zip(*sides, strict=False)]

    spans: list[list[int]] = []  # [y0, y1] of rows with text across the gutter
    merge_gap = int(height * SPAN_MERGE_GAP)
    for y, count in enumerate(crossing):
        if count < 2:
            continue
        if spans and y - spans[-1][1] <= merge_gap:
            spans[-1][1] = y
        else:
            spans.append([y, y])
    spans = [s for s in spans if s[1] - s[0] >= height * SPAN_MIN_HEIGHT]

    bands: list[tuple[int, int, bool]] = []
    cursor = 0
    pad = merge_gap // 2
    for y0, y1 in spans:
        y0, y1 = max(cursor, y0 - pad), min(height, y1 + pad)
        if y0 > cursor:
            bands.append((cursor, y0, False))
        bands.append((y0, y1, True))
        cursor = y1
    if cursor < height:
        bands.append((cursor, height, False))
    return [b for b in bands if b[1] - b[0] > 0]


# --- Text normalization for OCR output ---

_PERSIAN_TO_ARABIC = str.maketrans({
    "۰": "٠", "۱": "١", "۲": "٢", "۳": "٣", "۴": "٤",
    "۵": "٥", "۶": "٦", "۷": "٧", "۸": "٨", "۹": "٩",
    "ی": "ي", "ک": "ك",
})
_NEWLINES = re.compile(r"\s*\n\s*")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def tidy(text: str) -> str:
    """Normalize model output: no code fences, Arabic (not Persian) digits and letters."""
    text = _FENCE.sub("", text.strip())
    return unicodedata.normalize("NFC", text.translate(_PERSIAN_TO_ARABIC)).strip()


# --- Comparing two readings ---

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_PUNCTUATION = re.compile(r"[^\w\s]|_")
_LETTER_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})

# Two readings agree when they differ by at most this many words (or this share of the
# words, on a long column)...
AGREEMENT_MAX_WORDS = 2
AGREEMENT_MAX_SHARE = 0.02
# ...and neither has a run of this many words the other lacks (a skipped line or phrase).
AGREEMENT_MAX_GAP = 3


def _comparable_words(text: str) -> list[str]:
    """Words reduced to what matters for agreeing on the text: no diacritics, one form of
    alef/yaa/taa marbuta, and no alef inside a word — printed books write إسحٰق and هٰرون
    where models may write إسحاق and هارون. Numbers (hadith and page numbering) are left
    out: models differ on whether to copy marginal numbers, never on the text."""
    text = unicodedata.normalize("NFKC", text)
    text = _DIACRITICS.sub("", text).translate(_LETTER_VARIANTS)
    words = (w[0] + w[1:].replace("ا", "") for w in _PUNCTUATION.sub(" ", text).split())
    return [w for w in words if not w.isdigit()]


def compare(a: str, b: str) -> tuple[float, int, int]:
    """(share of matching words, number of differing words, longest differing run)."""
    wa, wb = _comparable_words(a), _comparable_words(b)
    if not wa and not wb:
        return 1.0, 0, 0
    matcher = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    runs = [max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"]
    return matcher.ratio(), sum(runs), max(runs, default=0)


def agree(a: str, b: str) -> bool:
    _, differing, gap = compare(a, b)
    words = max(len(_comparable_words(a)), len(_comparable_words(b)))
    return gap < AGREEMENT_MAX_GAP and differing <= max(AGREEMENT_MAX_WORDS, words * AGREEMENT_MAX_SHARE)


# --- Vision model (OpenRouter) ---

PROMPT = """انسخ النص العربي المطبوع في هذه الصورة حرفيًا كما هو، من أول سطر إلى آخر سطر، دون إسقاط أي سطر أو كلمة ودون إضافة أي شيء.
- حافظ على الحروف والتشكيل وعلامات الترقيم والأقواس والأرقام كما هي.
- إن كانت الصورة عمودين فانسخ العمود الأيمن كاملًا ثم العمود الأيسر، وتجاهل رأس الصفحة.
- اكتب ﷺ حيث يظهر رمز الصلاة على النبي.
- ابدأ كل حديث أو فقرة أو عنوان في سطر جديد.
- لا تكتب أي شرح أو تعليق أو تنسيق Markdown. إن لم يكن في الصورة نص فلا تكتب شيئًا."""

# Transient failures worth retrying: rate limits and provider/server errors.
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}
RETRY_DELAYS = (3, 10, 30)

# Models that reject requests with reasoning disabled; remembered after the first refusal.
_needs_reasoning: set[str] = set()


class VisionError(Exception):
    pass


class OutOfCredit(VisionError):
    """OpenRouter refused for lack of credit: every following page would fail the same way."""


OUT_OF_CREDIT_MESSAGE = (
    "رصيد OpenRouter لا يكفي لقراءة الصفحات الممسوحة — اشحن الرصيد ثم أعد رفع الملف"
)


@dataclass
class Reading:
    text: str
    cost: float = 0.0


def _image_payload(image) -> str:
    buf = io.BytesIO()
    image.convert("L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def vision_read(image, model: str, client: httpx.Client | None = None) -> Reading:
    """Transcribe one image with a vision model. Raises VisionError on failure."""
    settings = get_settings()
    content = [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_image_payload(image)}"}},
    ]
    owns_client = client is None
    client = client or httpx.Client(timeout=settings.ocr_timeout_seconds)
    try:
        for attempt in range(len(RETRY_DELAYS) + 1):
            reasoning_off = model not in _needs_reasoning
            body = {
                "model": model,
                "temperature": 0,
                "max_tokens": 8192,
                # Transcription needs no reasoning, and reasoning tokens cost money and time.
                "reasoning": {"enabled": False} if reasoning_off else {"effort": "low"},
                "messages": [{"role": "user", "content": content}],
            }
            try:
                res = client.post(
                    f"{settings.openrouter_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "X-Title": "Isnad"},
                    json=body,
                    timeout=settings.ocr_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                error = f"network: {exc!r}"
            else:
                if res.status_code == 400 and "reason" in res.text.lower() and reasoning_off:
                    _needs_reasoning.add(model)
                    continue
                if res.status_code == 200:
                    return _parse(res.json(), model)
                error = f"HTTP {res.status_code}: {res.text[:200]}"
                if res.status_code == 402:
                    raise OutOfCredit(error)
                if res.status_code not in RETRY_STATUS:
                    raise VisionError(error)
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])
        raise VisionError(error)
    finally:
        if owns_client:
            client.close()


def _parse(data: dict, model: str) -> Reading:
    try:
        choice = data["choices"][0]
        text = choice["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionError(f"{model}: unexpected response {str(data)[:200]}") from exc
    finish = (choice.get("finish_reason") or "").lower()
    if finish and finish not in ("stop", "end_turn"):
        # "length" = cut off; "content_filter"/"recitation" = blocked. Neither is a full page.
        raise VisionError(f"{model}: incomplete transcription ({finish})")
    # The prompt puts every hadith, paragraph and heading on its own line: make each one a
    # paragraph, so each becomes its own passage in the database.
    text = _NEWLINES.sub("\n\n", tidy(text))
    return Reading(text, float((data.get("usage") or {}).get("cost") or 0))


# --- Tesseract ---


def prepare_for_tesseract(image):
    """Grayscale, enlarge low-resolution scans, and stretch the contrast."""
    from PIL import Image, ImageOps

    image = image.convert("L")
    longest = max(image.size)
    if longest < TESSERACT_TARGET_LONG_SIDE:
        scale = min(TESSERACT_MAX_UPSCALE, TESSERACT_TARGET_LONG_SIDE / longest)
        if scale > 1.1:
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)), Image.LANCZOS
            )
    # Faded or grey scans: spread the darkest/lightest 1% to full black/white.
    return ImageOps.autocontrast(image, cutoff=1)


# Images whose longer side is below this are enlarged for Tesseract (≈ A4 at 300 DPI).
TESSERACT_TARGET_LONG_SIDE = 3000
TESSERACT_MAX_UPSCALE = 3.0


def tesseract_read(image) -> str:
    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailable("مكتبة pytesseract غير مثبتة") from exc

    settings = get_settings()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    try:
        # --psm 4: one column of text of variable sizes — regions are already single columns
        return tidy(pytesseract.image_to_string(
            prepare_for_tesseract(image), lang=settings.ocr_languages, config="--psm 4"
        ))
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailable("برنامج Tesseract غير مثبت على الخادم") from exc
    except pytesseract.TesseractError as exc:
        raise OcrUnavailable(f"فشل Tesseract: {exc}") from exc


# --- Reading a page ---


@dataclass
class PageResult:
    text: str
    cost: float = 0.0
    fallback: bool = False  # read with Tesseract because the vision model failed
    disputed: bool = False  # the three models disagreed: worth a human look


@dataclass
class OcrStats:
    pages: int = 0
    cost: float = 0.0
    fallback_pages: list[int] = field(default_factory=list)
    disputed_pages: list[int] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, page_number: int, result: PageResult) -> None:
        with self._lock:
            self.pages += 1
            self.cost += result.cost
            if result.fallback:
                self.fallback_pages.append(page_number)
            if result.disputed:
                self.disputed_pages.append(page_number)

    def note(self) -> str | None:
        """Arabic note for the dashboard about pages that deserve a look, if any."""
        parts = []
        if self.disputed_pages:
            parts.append(f"صفحات اختلفت فيها قراءات النماذج وتستحق المراجعة: {_page_list(self.disputed_pages)}")
        if self.fallback_pages:
            parts.append(f"صفحات قُرئت بـ Tesseract لتعذّر نموذج الرؤية: {_page_list(self.fallback_pages)}")
        return " — ".join(parts) or None


def _page_list(pages: list[int], limit: int = 30) -> str:
    pages = sorted(pages)
    shown = "، ".join(str(p) for p in pages[:limit])
    return shown + (f" و{len(pages) - limit} غيرها" if len(pages) > limit else "")


def vision_enabled() -> bool:
    settings = get_settings()
    return settings.ocr_engine == "vision" and bool(settings.openrouter_api_key)


class PageReader:
    """Reads page images, with the settings' engine and models. Thread-safe."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = httpx.Client(
            timeout=settings.ocr_timeout_seconds,
            limits=httpx.Limits(max_connections=settings.ocr_concurrency * 3),
        )
        # Second and third readings of a column run alongside the first one.
        self._side = ThreadPoolExecutor(settings.ocr_concurrency * 2, thread_name_prefix="ocr-check")

    def close(self) -> None:
        self._side.shutdown(wait=False, cancel_futures=True)
        self.client.close()

    def __enter__(self) -> "PageReader":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def read(self, image) -> PageResult:
        regions = [r for r in text_regions(image) if ink_share(r) > BLANK_MAX_INK]
        results = [self._read_region(r) for r in regions]
        return PageResult(
            text="\n\n".join(r.text for r in results if r.text),
            cost=sum(r.cost for r in results),
            fallback=any(r.fallback for r in results),
            disputed=any(r.disputed for r in results),
        )

    def _read_region(self, image) -> PageResult:
        if not vision_enabled():
            return PageResult(tesseract_read(image))

        s = self.settings
        check = self._side.submit(vision_read, image, s.ocr_check_model, self.client) if s.ocr_check_model else None
        readings: list[Reading] = []
        try:
            readings.append(vision_read(image, s.ocr_model, self.client))
        except OutOfCredit as exc:
            # Stop the file instead of quietly reading the rest of the book with Tesseract.
            raise OcrUnavailable(OUT_OF_CREDIT_MESSAGE) from exc
        except VisionError as exc:
            logger.warning("OCR model %s failed: %s", s.ocr_model, exc)
        if check is not None:
            try:
                readings.append(check.result())
            except OutOfCredit as exc:
                raise OcrUnavailable(OUT_OF_CREDIT_MESSAGE) from exc
            except VisionError as exc:
                logger.warning("OCR check model %s failed: %s", s.ocr_check_model, exc)

        cost = sum(r.cost for r in readings)
        if len(readings) == 2 and not agree(readings[0].text, readings[1].text) and s.ocr_referee_model:
            try:
                referee = vision_read(image, s.ocr_referee_model, self.client)
                readings.append(referee)
                cost += referee.cost
            except OutOfCredit as exc:
                raise OcrUnavailable(OUT_OF_CREDIT_MESSAGE) from exc
            except VisionError as exc:
                logger.warning("OCR referee model %s failed: %s", s.ocr_referee_model, exc)
            best, disputed = pick_majority([r.text for r in readings])
            return PageResult(best, cost, disputed=disputed)
        if readings:
            return PageResult(readings[0].text, cost)

        # Vision model unreachable: fall back to Tesseract rather than lose the page.
        try:
            return PageResult(tesseract_read(image), cost, fallback=True)
        except OcrUnavailable as exc:
            raise OcrUnavailable(f"تعذّر التعرّف الضوئي: نموذج الرؤية غير متاح و{exc}") from exc


def pick_majority(texts: list[str]) -> tuple[str, bool]:
    """Choose among [main, check, referee] readings: the first of two that agree (the main
    model's reading when it is one of them), and whether no two agreed."""
    if len(texts) < 3:
        return texts[0], True
    for i, j in ((0, 1), (0, 2), (1, 2)):
        if agree(texts[i], texts[j]):
            return texts[i], False
    # No majority: keep the reading closest to the other two, and flag the page.
    scores = [
        sum(compare(t, other)[0] for j, other in enumerate(texts) if j != i)
        for i, t in enumerate(texts)
    ]
    return texts[max(range(3), key=lambda i: (scores[i], -i))], True
