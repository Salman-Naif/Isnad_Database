"""
Reading hadith collections published as JSON or CSV into structured hadith records.

Formats read (detected from the content, not the file name):

  - Isnad's own JSON: an array of records like docs/hadith_format.example.json
    (id, text, hukm, mohaddith, sanad, topic, source).
  - A collection per book: {"metadata": {...}, "chapters": [...], "hadiths": [...]} (or one
    chapter per file). Each hadith's "arabic" text is used; its chapter becomes the topic;
    scholars' grades, when the file has them ("english.grades"), become the ruling and the
    scholar who gave it.
  - CSV, one hadith per row (one column headed by the book's name, or number and text). The
    hadith is the column with the longest texts; a column of numbers, if any, gives each
    hadith its number.

Isnad's own sources (the Shamela editions) are converted by scripts/import_shamela.py into
Isnad's JSON format: docs/DATA_SOURCES.md.

Rulings are only ever taken from the file itself, or from a ruling the team sets explicitly for
a whole book (`default_hukm`) — never guessed.
"""

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.models.schemas import HadithRecord
from app.services import books
from app.services.extraction import ExtractionError
from app.services.text_processing import clean

COLLECTION_EXTENSIONS = {".json", ".csv"}

_records_adapter = TypeAdapter(list[HadithRecord])
_ARABIC = re.compile(r"[؀-ۿ]")

# Grades as collections write them in English → the Arabic term. Checked in order: "hasan sahih"
# before "hasan" and "sahih". A grade not listed here is kept exactly as written.
_GRADE_TERMS = [
    ("hasan sahih", "حسن صحيح"), ("sahih", "صحيح"), ("hasan", "حسن"),
    ("da'if jiddan", "ضعيف جدًا"), ("da'if", "ضعيف"), ("daif", "ضعيف"), ("da`if", "ضعيف"),
    ("weak", "ضعيف"), ("mawdu", "موضوع"), ("maudu", "موضوع"), ("fabricated", "موضوع"),
    ("munkar", "منكر"), ("shadh", "شاذ"),
]
_GRADERS = {
    "al-albani": "الألباني", "shuaib al arnaut": "شعيب الأرناؤوط", "zubair ali zai": "زبير علي زئي",
    "darussalam": "دار السلام", "ahmad muhammad shakir": "أحمد محمد شاكر",
}
# When several scholars graded a hadith, the first of these is shown.
_GRADER_PREFERENCE = list(_GRADERS)


@dataclass
class Collection:
    records: list[HadithRecord]
    title: str = ""  # the book's title, when the file names it
    skipped: int = 0  # rows/entries without any Arabic text
    graded: int = 0  # records whose ruling came from the file
    notes: list[str] = field(default_factory=list)


def read_collection(
    data: bytes,
    filename: str,
    *,
    source: str = "",
    default_hukm: str = "",
    default_mohaddith: str = "",
) -> Collection:
    """Parse a JSON or CSV collection. `source` names the book (default: the title in the
    file, else the file name); `default_hukm` / `default_mohaddith` fill in a ruling the team
    has decided for the whole book, for records that carry none of their own."""
    ext = Path(filename).suffix.lower()
    text = _decode(data)
    if ext == ".csv":
        collection = _from_csv(text)
    elif ext == ".json":
        collection = _from_json(text)
    else:
        raise ExtractionError(f"نوع الملف غير مدعوم: {ext or filename}")

    book = source or arabic_title(collection.title or Path(filename).stem)
    for record in collection.records:
        record.source = arabic_title(record.source or book)
        if not record.hukm and default_hukm:
            record.hukm = default_hukm
            record.mohaddith = record.mohaddith or default_mohaddith

    if not collection.records:
        raise ExtractionError("الملف لا يحتوي أي حديث")
    duplicates = _duplicates([r.id for r in collection.records])
    if duplicates:
        raise ExtractionError(f"أرقام أحاديث مكررة في الملف: {', '.join(duplicates[:10])}")
    return collection


# The hadith's own words (matn) start after the first mention of the Prophet ﷺ in the
# narration; the words that introduce them ("قال", "يقول", ":") are skipped.
_PROPHET = re.compile(r"صلى الله عليه وسلم|ﷺ")
_MATN_LEAD = re.compile(r"^(?:[\s:،,.«»\"'()]|قال|قالت|فقال|فقالت|وقال|يقول|أنه|انه)+")
# Shorter matns get no vector of their own: a 4-word text lands close to almost any short
# query (measured: «قيل لي أنت منهم» at 0.86 for «صوموا تصحوا»). Their words are still found
# exactly through the literal-quote index, and the whole narration keeps its vector.
MATN_MIN_WORDS = 8
MATN_MAX_SHARE = 0.85  # a "matn" nearly as long as the whole text adds nothing


def record_matn(record: HadithRecord) -> str:
    """The matn to index separately: the one the edition marks, else the one found in the text
    — either way only when long enough to stand on its own."""
    if record.matn:
        return record.matn if len(record.matn.split()) >= MATN_MIN_WORDS else ""
    return matn_of(record.text)


def matn_of(text: str) -> str:
    """The hadith's text without its chain of narrators, or "" when it can't be told apart
    (no mention of the Prophet ﷺ, e.g. a companion's saying, or almost no chain at all)."""
    text = unicodedata.normalize("NFKC", text)  # "ﷺ" → "صلى الله عليه وسلم"
    bare = _DIACRITIC_MARKS.sub("", text)
    found = _PROPHET.search(bare)
    if not found:
        return ""
    matn = _MATN_LEAD.sub("", bare[found.end():]).strip(" «»\"'.")
    if len(matn.split()) < MATN_MIN_WORDS or len(matn) > MATN_MAX_SHARE * len(bare):
        return ""
    return matn


_DIACRITIC_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

def arabic_title(name: str) -> str:
    """The published Arabic title of a known book from any name it comes with («Sahih Bukhari
    Without_Tashkel», «موطأ مالك» → «موطأ الإمام مالك»), or the name unchanged."""
    return books.title(name)


def to_isnad_json(collection: Collection) -> bytes:
    """The records in Isnad's own JSON format, ready to upload from the dashboard."""
    return json.dumps(
        [r.model_dump() for r in collection.records], ensure_ascii=False, indent=1
    ).encode("utf-8")


# --- JSON ---


def _from_json(text: str) -> Collection:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"ملف JSON غير صالح: {exc}") from exc

    if isinstance(data, list):
        try:
            return Collection(_records_adapter.validate_python(data))
        except ValidationError as exc:
            raise ExtractionError(f"بنية الأحاديث غير صحيحة: {exc.errors()[0]['msg']}") from exc
    if isinstance(data, dict) and isinstance(data.get("hadiths"), list):
        return _from_sunnah_json(data)
    raise ExtractionError(
        "صيغة JSON غير معروفة: المطلوب مصفوفة أحاديث، أو ملف كتاب فيه \"hadiths\""
    )


def _from_sunnah_json(data: dict) -> Collection:
    metadata = data.get("metadata") or {}
    title = _arabic_field(metadata, "title")
    chapters = {c.get("id"): _arabic_field(c, "title") or _plain(c.get("arabic"))
                for c in data.get("chapters") or [] if isinstance(c, dict)}
    if isinstance(data.get("chapter"), dict):  # by_chapter layout: one chapter per file
        chapter = data["chapter"]
        chapters[chapter.get("id")] = _arabic_field(chapter, "title") or _plain(chapter.get("arabic"))

    collection = Collection([], title=title)
    for number, hadith in enumerate(data["hadiths"], start=1):
        arabic = hadith.get("arabic")
        body = _tidy(arabic.get("text", "") if isinstance(arabic, dict) else str(arabic or ""))
        if not _ARABIC.search(body):
            collection.skipped += 1
            continue
        hukm, mohaddith = _grade((hadith.get("english") or {}).get("grades") or hadith.get("grades") or [])
        collection.graded += bool(hukm)
        collection.records.append(HadithRecord(
            id=str(hadith.get("idInBook") or hadith.get("id") or number),
            text=body,
            hukm=hukm,
            mohaddith=mohaddith,
            topic=chapters.get(hadith.get("chapterId"), "") or "",
        ))
    return collection


def _arabic_field(obj: dict, key: str) -> str:
    arabic = obj.get("arabic")
    return _tidy(arabic.get(key, "")) if isinstance(arabic, dict) else ""


def _plain(value) -> str:
    return _tidy(value) if isinstance(value, str) else ""


def _grade(grades: list) -> tuple[str, str]:
    """(ruling, scholar) from a list like [{"name": "Al-Albani", "grade": "Sahih"}]."""
    graded = [g for g in grades if isinstance(g, dict) and g.get("grade")]
    if not graded:
        return "", ""

    def rank(g: dict) -> int:
        name = str(g.get("name", "")).strip().lower()
        return _GRADER_PREFERENCE.index(name) if name in _GRADER_PREFERENCE else len(_GRADER_PREFERENCE)

    best = min(graded, key=rank)
    grade = str(best["grade"]).strip()
    lowered = grade.lower()
    term = next((arabic for english, arabic in _GRADE_TERMS if lowered.startswith(english)), grade)
    name = str(best.get("name", "")).strip()
    return term, _GRADERS.get(name.lower(), name)


# --- CSV ---


def _from_csv(text: str) -> Collection:
    csv.field_size_limit(10_000_000)  # some hadiths with their commentary are very long
    try:
        dialect = csv.Sniffer().sniff(text[:20_000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]
    rows = [row for row in rows if any(row)]
    if not rows:
        return Collection([])

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    text_column = max(range(width), key=lambda c: sum(len(r[c]) for r in rows))
    number_column = next(
        (c for c in range(width) if c != text_column and all(r[c].isdigit() for r in rows[1:] if r[c])
         and any(r[c] for r in rows[1:])),
        None,
    )

    title = ""
    if _is_header(rows, text_column, number_column):
        title = rows[0][text_column]  # e.g. the book's name, or a column name
        rows = rows[1:]

    collection = Collection([], title=title)
    for index, row in enumerate(rows, start=1):
        body = _tidy(row[text_column])
        if not _ARABIC.search(body):
            collection.skipped += 1
            continue
        number = row[number_column] if number_column is not None and row[number_column] else str(index)
        collection.records.append(HadithRecord(id=number, text=body))
    return collection


def _is_header(rows: list[list[str]], text_column: int, number_column: int | None) -> bool:
    """The first row names the columns (or the book) rather than holding a hadith."""
    first = rows[0]
    if not _ARABIC.search(first[text_column]):
        return True
    if number_column is not None:
        return not first[number_column].isdigit()
    others = [len(r[text_column]) for r in rows[1:]]
    return bool(others) and len(first[text_column]) < 20 < sum(others) / len(others)


# --- Helpers ---


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("تعذّرت قراءة ترميز الملف — احفظه بترميز UTF-8")


def _tidy(text: str) -> str:
    """Invisible direction marks and doubled spaces removed; diacritics kept for display."""
    return " ".join(clean(text, strip_diacritics=False).split())


def _duplicates(ids: list[str]) -> list[str]:
    seen, dupes = set(), []
    for i in ids:
        if i in seen and i not in dupes:
            dupes.append(i)
        seen.add(i)
    return dupes
