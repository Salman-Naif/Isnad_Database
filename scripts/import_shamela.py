"""
Convert hadith books from an installed المكتبة الشاملة (Shamela desktop, shamela.ws) into
Isnad's JSON format, ready to upload from the dashboard or with scripts/import_hadiths.py.

    python scripts/import_shamela.py --list                    # the hadith books installed
    python scripts/import_shamela.py 1681                      # صحيح البخاري - ط السلطانية
    python scripts/import_shamela.py 1681 --shamela D:/shamela --out data/structured

Then measure the cost and upload:

    python scripts/import_hadiths.py "data/structured/صحيح البخاري - ط السلطانية.json" --estimate

Shamela keeps each book's pages in a Lucene index (database/store/page). They are read with
Shamela's own Lucene jars and a small Java program (scripts/shamela/ShamelaExport.java,
compiled on the fly — needs a JDK 21+: `javac`). The pages carry the edition's own markup,
which gives what the text alone can't:

  - each hadith starts a line with its number «٢٠ - حدثنا…» (or numbers: «٤٠٨ - ٤٠٩ - »);
  - every narrator of the chain is linked to Shamela's narrators database
    (<a href="inr://man-5638">محمد بن سلام</a>) — so the sanad is taken as written, not guessed;
  - the Prophet's words are marked (<hadeeth-N>«…»<hadeeth>) — the matn, exactly;
  - chapter titles are marked (<span data-type='title'>باب …</span>) — the topic.

Rulings are not added: the team sets them (--hukm / --mohaddith), as for any other source.
"""

import argparse
import bisect
import glob
import itertools
import json
import re
import shutil
import sqlite3
import subprocess  # nosec B404 — runs javac/java on the team's own machine, fixed arguments
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python scripts/...` from any folder
sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles can't print Arabic otherwise

from app.models.schemas import HadithRecord, Narrator  # noqa: E402
from app.services import books  # noqa: E402
from app.services.hadith_import import Collection, to_isnad_json  # noqa: E402

EXPORTER = ROOT / "scripts" / "shamela" / "ShamelaExport.java"
LUCENE_JARS = ("lucene-core-10.4.0.jar", "lucene-backward-codecs-10.4.0.jar", "lucene-codecs-10.4.0.jar")
OUT_DIR = ROOT / "data" / "structured"
HADITH_CATEGORY = "كتب السنة"
PROPHET = "النبي ﷺ"

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# Shamela writes honorifics as single characters that Unicode doesn't decompose.
_HONORIFICS = {
    "\ufd40": "رحمه الله", "\ufd41": "رضي الله عنه", "\ufd42": "رضي الله عنها",
    "\ufd43": "رضي الله عنهم", "\ufd44": "رضي الله عنهما", "\ufd45": "رضي الله عنهن",
    "\ufd47": "عليه السلام", "\ufd48": "عليهم السلام", "\ufd49": "عليهما السلام",
    "\ufd4a": "عليه الصلاة والسلام", "\ufd4d": "عليها السلام", "\ufd4e": "تبارك وتعالى",
    "\ufdff": "عز وجل", "\ufdfd": "بسم الله الرحمن الرحيم",
}
_HONORIFICS["﵏"] = "رحمهم الله"
_UNMAPPED_LIGATURE = re.compile(r"[﵀-﵏]")  # any other honorific glyph: dropped, never shown raw
# Words of transmission: the first hadith of a book has one. Numbered points before it are the
# editors' introduction (Musnad Ahmad ط الرسالة numbers its own), which is not taken.
# «ح» standing alone — «ح»، «(ح)»، «،ح،» — starts another chain of the same hadith.
_TAHWIL = re.compile(r"(?:^|[^ء-ي])ح(?:[^ء-ي]|$)")
_PROPHET_NAMED = re.compile(r"ﷺ|صلى الله عليه وسلم|رسول الله|النبي")  # matched without diacritics
_NOTE_MARK = re.compile(r"\(([٠-٩]{1,3})\)")
# al-Tirmidhi's words on a hadith, matched without diacritics: «هذا حديث حسن صحيح غريب».
_TIRMIDHI_GRADE = re.compile(r"هذا حديث ((?:(?:حسن|صحيح|غريب|ضعيف|منكر|مرسل)\s?){1,3})")
# A footnote that opens with a grading: «إسناده صحيح على شرط الشيخين»، «حسن»، «حديث صحيح، وهذا إسناد ضعيف».
_NOTE_GRADE = re.compile(
    r"^(?:حديث |إسناده |إسناد |صحيح|حسن|ضعيف|موضوع|منكر)[^.\n]{0,60}?(?=[،.]|\s(?:رجاله|وهذا|وأخرجه|فقد|لأن)|$)"
)
# Editions whose editors grade each hadith in a footnote, and how they are credited.
GRADING_EDITORS = {25794: "شعيب الأرنؤوط وآخرون (مسند أحمد ط الرسالة)"}
# Scholars whose rulings editions record under a code, by the code's label.
CODED_SCHOLARS = {"حكم الألباني": "الألباني"}
MIN_BODY_RUN = 50  # numbers rising in a row, from a «1», that mark the hadiths (not an introduction)
_TRANSMISSION = re.compile(r"(?:^|\s)و?(?:حدثنا|حدثني|اخبرنا|اخبرني|انبانا)(?:\s|$)")
# A hadith starts a line with its number(s): «٢٠ - », «٤٠٨ - ٤٠٩ - », or Muslim's «١٢٨ - (٧٤) »
# (a running number, then Abd al-Baqi's). Lines end in \n or \r.
_START = re.compile(r"(?:^|[\r\n])[ \t]*((?:[٠-٩]+[ \t]*-[ \t]*)+(?:\([٠-٩]+\)[ \t]*)?)")
_TITLE = re.compile(r"<span data-type=['\"]title['\"][^>]*>(.*?)</span>", re.S)
_NARRATOR = re.compile(r"<a href=\"inr://man-(\d+)\">(.*?)</a>", re.S)
_MATN = re.compile(r"<hadeeth-\d+>(.*?)<hadeeth>", re.S)
_TAG = re.compile(r"<[^>]+>")
_PAGE_MARK = re.compile(r"⦗[٠-٩0-9]+⦘")  # the printed edition's page numbers, inside the text
_FOOTNOTE_MARK = re.compile(r"\s*\([٠-٩0-9]{1,3}\)")  # «(١)»: a pointer to a footnote, not taken
# A number inside a narration: Bukhari splits one narration under several numbers («… ٣٠٠ - وكان»).
_INLINE_NUMBER = re.compile(r"(?<=\s)[٠-٩]+[ \t]*-[ \t]+")
_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u0640]")
# «حدثنا أبي / عن أبيه»: a narrator named by kinship to the one before him.
_KIN = {"ابيه": "والد", "ابي": "والد", "ابيها": "والد", "جده": "جد", "امه": "أم", "عمه": "عم", "خاله": "خال"}


@dataclass
class Book:
    id: int
    name: str
    path: Path  # its database/book/<nnn>/<id>.db
    shorts: dict[str, str] = field(default_factory=dict)  # the edition's codes: {"0": "[حكم الألباني] :"}


@dataclass
class Hadith:
    numbers: list[int]
    raw: str  # the edition's markup, from the number to the next hadith or title
    topic: str
    narrators: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # the footnotes its «(n)» marks point to
    pages: tuple[int, int] = (0, 0)  # first and last page it is on
    ruling: tuple[str, str] = ("", "")  # (ruling, scholar) from a code in the page's notes


def plain(markup: str) -> str:
    """Readable text: no tags, page marks or inline numbers; honorifics spelled out."""
    text = _TAG.sub("", markup)
    text = _PAGE_MARK.sub("", text)
    text = _FOOTNOTE_MARK.sub("", text)
    for glyph, words in _HONORIFICS.items():
        text = text.replace(glyph, f" {words} ")
    text = _UNMAPPED_LIGATURE.sub("", text)
    text = _INLINE_NUMBER.sub("", text)
    return " ".join(text.replace("\r", " ").split())


def _bare(text: str) -> str:
    return _DIACRITICS.sub("", text).translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا"})).strip(" ،,.:؛")


def installed_books(shamela: Path) -> list[Book]:
    """The books of «كتب السنة» installed in this Shamela library."""
    master = sqlite3.connect(f"file:{shamela / 'database' / 'master.db'}?mode=ro", uri=True)
    try:
        categories = dict(master.execute("select category_id, category_name from category"))
        rows = master.execute("select book_id, book_name, book_category, meta_data from book").fetchall()
    finally:
        master.close()
    found = {int(Path(p).stem): Path(p) for p in glob.glob(str(shamela / "database" / "book" / "*" / "*.db"))}
    return [Book(i, name, found[i], _shorts(meta)) for i, name, category, meta in rows
            if i in found and categories.get(category) == HADITH_CATEGORY]


def _shorts(meta: str | None) -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in (json.loads(meta or "{}").get("shorts") or {}).items()}
    except (ValueError, AttributeError):
        return {}


def export_pages(shamela: Path, book: Book, work: Path) -> tuple[list[str], list[str]]:
    """The book's page bodies and footnotes, in the edition's order."""
    jars = [shamela / "app" / "lucene" / "2" / jar for jar in LUCENE_JARS]
    missing = [str(j) for j in jars if not j.exists()]
    if missing:
        raise SystemExit(f"Shamela's Lucene jars were not found: {missing}")
    javac, java = shutil.which("javac"), shutil.which("java")
    if not (javac and java):
        raise SystemExit("A JDK 21+ is needed (javac and java on the PATH)")
    classpath = ";".join(map(str, jars)) if sys.platform == "win32" else ":".join(map(str, jars))
    subprocess.run([javac, "-d", str(work), "-cp", classpath, str(EXPORTER)], check=True)  # noqa: S603  # nosec B603
    out = work / "pages.jsonl"
    subprocess.run(  # noqa: S603  # nosec B603
        [java, "-cp", f"{classpath}{';' if sys.platform == 'win32' else ':'}{work}", "ShamelaExport",
         str(shamela / "database" / "store" / "page"), str(book.id), str(out)],
        check=True, capture_output=True,
    )
    pages, feet = {}, {}
    for line in out.read_text(encoding="utf-8").splitlines():
        page = json.loads(line)
        pages[page["page"]], feet[page["page"]] = page["body"], page["foot"]
    db = sqlite3.connect(f"file:{book.path}?mode=ro", uri=True)
    try:
        order = [row[0] for row in db.execute("select id from page order by id")]
    finally:
        db.close()
    kept = [i for i in order if i in pages]
    return [pages[i] for i in kept], [feet[i] for i in kept]


def split_hadiths(pages: list[str], feet: list[str] | None = None) -> list[Hadith]:
    """The numbered hadiths of a book, each with the chapter it falls under (and, given the
    pages' footnotes, the notes its marks point to)."""
    text = "\n".join(pages)
    starts = list(itertools.accumulate((len(p) + 1 for p in pages), initial=0))
    # Where every hadith starts and every title stands, in the order of the book.
    marks = [(m.start(1), "hadith", m) for m in _START.finditer(text)]
    marks += [(m.start(), "title", m) for m in _TITLE.finditer(text)]
    marks.sort(key=lambda mark: mark[0])
    hadiths: list[Hadith] = []
    kitab = bab = ""
    for i, (_start, kind, match) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if kind == "title":
            title = plain(match.group(1))
            if _bare(title).startswith("كتاب"):
                kitab, bab = title, ""
            elif _bare(title) not in ("باب", "بابٌ"):
                bab = title
            continue
        numbers = [int(n.translate(_DIGITS)) for n in re.findall(r"[٠-٩]+", match.group(1))]
        raw = text[match.end(1):end]
        notes = _notes_of(text, match.end(1), end, starts, feet) if feet else []
        span = (bisect.bisect_right(starts, match.end(1)) - 1, bisect.bisect_right(starts, max(end - 1, 0)) - 1)
        hadiths.append(Hadith(numbers, raw, bab or kitab, notes=notes, pages=span))
    hadiths = without_front_matter(hadiths)
    for hadith in hadiths:
        hadith.narrators = chain_of(hadith.raw)
    return hadiths


def _notes_of(text: str, start: int, end: int, starts: list[int], feet: list[str]) -> list[str]:
    """The footnotes the «(n)» marks between start and end point to, each from its own page."""
    notes = []
    for mark in _NOTE_MARK.finditer(text, start, end):
        page = bisect.bisect_right(starts, mark.start()) - 1
        note = _footnotes(feet[page]).get(mark.group(1)) if 0 <= page < len(feet) else None
        if note:
            notes.append(note)
    return notes


def _footnotes(foot: str) -> dict[str, str]:
    """A page's footnotes by their number: «(١) إسناده صحيح… (٢) …»."""
    parts = re.split(r"\(([٠-٩]{1,3})\)\s*", foot or "")
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def coded_rulings(hadiths: list[Hadith], book: Book, feet: list[str]) -> None:
    """Rulings an edition records under one of its codes — «[حكم الألباني] :» is «<s0>» in the
    notes of Sunan Abi Dawud ت محيي الدين, «<s2>» in Sunan Ibn Majah ت عبد الباقي — given to
    the hadiths of the page they stand on, in order."""
    for code, label in book.shorts.items():
        scholar = next((name for key, name in CODED_SCHOLARS.items() if key in label), None)
        if not scholar:
            continue
        mark = re.compile(rf"<s{re.escape(code)}>\s*([^\r\n<]{{1,80}})")
        found = [(i, m.group(1).strip(" :.،")) for i, foot in enumerate(feet) for m in mark.finditer(foot or "")]
        taken = 0
        for hadith in hadiths:
            first, last = hadith.pages
            while taken < len(found) and found[taken][0] < first:
                taken += 1  # a ruling on a page with no hadith of its own
            if taken < len(found) and found[taken][0] <= last and found[taken][1]:
                hadith.ruling = (found[taken][1], scholar)
                taken += 1


def ruling_of(hadith: Hadith, book: Book, text: str) -> tuple[str, str]:
    """(ruling, who gave it), only as the edition records it — never added here.

    - al-Tirmidhi rules on his hadiths in the text itself: «هذا حديث حسن صحيح».
    - Where the edition's editors grade every hadith in a footnote (Musnad Ahmad ط الرسالة),
      the grading phrase opening that footnote, attributed to them; nothing else of the note.
    - Where the edition records a scholar's ruling under a code (al-Albani's, see
      coded_rulings), that ruling.
    """
    if hadith.ruling[0]:
        return hadith.ruling
    if "ترمذي" in _bare(book.name):
        found = _TIRMIDHI_GRADE.search(_bare(text))
        if found:
            return found.group(1).strip(), "الترمذي"
    editors = GRADING_EDITORS.get(book.id)
    if editors:
        for note in hadith.notes:
            graded = _NOTE_GRADE.match(_DIACRITICS.sub("", note))
            if graded:
                return graded.group(0).strip(" ،,.=-"), editors
    return "", ""


def without_front_matter(hadiths: list[Hadith]) -> list[Hadith]:
    """From the «1» that starts the book's own numbering: the first place numbered 1 that is a
    narration and is followed by a long run of rising numbers. An editors' introduction numbers
    short lists of its own (Musnad Ahmad ط الرسالة; it even quotes chains, «حدثنا سفيان…»); the
    hadiths run on for hundreds. (Muslim ط التركية starts its running number again in every
    كتاب, so the first long run is the right one, not the longest.)"""
    for i, hadith in enumerate(hadiths):
        if hadith.numbers[0] != 1 or not _TRANSMISSION.search(_bare(plain(hadith.raw))):
            continue
        run, last = 1, 1
        for following in hadiths[i + 1:i + MIN_BODY_RUN]:
            if following.numbers[0] < last:
                break
            run, last = run + 1, following.numbers[0]
        if run >= MIN_BODY_RUN:
            return hadiths[i:]
    return hadiths


def chain_of(raw: str) -> list[str]:
    """The narrators linked before the Prophet's words, compiler's teacher first; empty when the
    narration has «ح» (several chains — the database reads those from the wording)."""
    head = raw.split("<hadeeth", 1)[0]
    if _TAHWIL.search(_bare(_TAG.sub(" ", head))):
        return []
    links = list(_NARRATOR.finditer(head))
    names: list[str] = []
    for i, link in enumerate(links):
        name = plain(link.group(2)).strip(" ،,:؛")
        between = _bare(plain(head[links[i - 1].end():link.start()])) if i else ""
        # «قتيبة، وأبو بكر» / «أبا هريرة وأبا سعيد» narrated together; Shamela puts the «و»
        # either between the two links or inside the second one.
        joined = between == "" and _bare(name).startswith("و")
        if names and (joined or between in ("و", "و،") or between.endswith(" و")):
            second = re.sub(r"^و[ً-ْ]*", "", name) if joined else name
            names[-1] = f"{names[-1]} و{second}"
            continue
        kin = _KIN.get(_bare(name))
        names.append(f"{kin} {names[-1]}" if kin and names else name)
    return names


def to_record(hadith: Hadith, book: Book, hukm: str, mohaddith: str) -> HadithRecord | None:
    text = plain(hadith.raw)
    if not text:
        return None
    matn = " ".join(plain(m) for m in _MATN.findall(hadith.raw)).strip(" «»\"")
    sanad: list[Narrator] = []
    if hadith.narrators:
        chain = [Narrator(name=n) for n in reversed(hadith.narrators)]
        # Raised to the Prophet ﷺ: the edition marks his words, or the narration names him (not every
        # edition marks the words of every hadith). Else it ends with the last narrator named.
        raised = bool(matn) or bool(_PROPHET_NAMED.search(_bare(text)))
        sanad = ([Narrator(name=PROPHET)] if raised else []) + chain
    found, by = ruling_of(hadith, book, text)
    return HadithRecord(
        id=f"{book.id}-{'-'.join(map(str, hadith.numbers))}",
        text=text, matn=matn, sanad=sanad, topic=hadith.topic,
        source=books.title(book.name),
        hukm=found or hukm, mohaddith=by if found else mohaddith,
    )


def unique_ids(records: list[HadithRecord]) -> list[HadithRecord]:
    """An edition can print a number twice (Bukhari ط السلطانية has 8, 23, 3756 and 3934 twice):
    the second keeps its number with «-b» («-c»…), so neither hadith is lost."""
    seen: dict[str, int] = {}
    for record in records:
        count = seen.get(record.id, 0)
        seen[record.id] = count + 1
        if count:
            record.id = f"{record.id}-{chr(ord('a') + count)}"
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Shamela hadith books to Isnad's JSON")
    parser.add_argument("book_ids", nargs="*", type=int, help="Shamela book ids (see --list)")
    parser.add_argument("--shamela", type=Path, default=Path("C:/shamela"), help="the Shamela folder")
    parser.add_argument("--list", action="store_true", help="list the hadith books installed")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="where to write the JSON files")
    parser.add_argument("--hukm", default="", help="a ruling the team has decided for the whole book")
    parser.add_argument("--mohaddith", default="", help="the scholar the ruling is attributed to")
    args = parser.parse_args()

    installed = {b.id: b for b in installed_books(args.shamela)}
    if args.list or not args.book_ids:
        for book in sorted(installed.values(), key=lambda b: b.name):
            print(f"{book.id:>7}  {book.name}")
        return
    args.out.mkdir(parents=True, exist_ok=True)
    for book_id in args.book_ids:
        book = installed.get(book_id)
        if book is None:
            raise SystemExit(f"Book {book_id} is not an installed hadith book (see --list)")
        with tempfile.TemporaryDirectory() as work:
            pages, feet = export_pages(args.shamela, book, Path(work))
        hadiths = split_hadiths(pages, feet)
        coded_rulings(hadiths, book, feet)
        records = unique_ids([r for h in hadiths if (r := to_record(h, book, args.hukm, args.mohaddith))])
        out = args.out / f"{unicodedata.normalize('NFC', book.name)}.json"
        out.write_bytes(to_isnad_json(Collection(records)))
        with_chain = sum(1 for r in records if r.sanad)
        with_matn = sum(1 for r in records if r.matn)
        graded = sum(1 for r in records if r.hukm)
        print(f"{book.name}: {len(pages)} pages → {len(records)} hadiths "
              f"({with_chain} with their chain, {with_matn} with their matn marked, {graded} graded) → {out}")


if __name__ == "__main__":
    main()
