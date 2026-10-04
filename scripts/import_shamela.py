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
_NOTE_MARK = re.compile(r"\(¬?([٠-٩]{1,3})\)")  # «(١)», or «(¬١)» as some editions write it
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
# A hadith starts a line with its number(s): «٢٠ - », «٤٠٨ - ٤٠٩ - », Muslim's «١٢٨ - (٧٤) » or
# «(١٦٩٧/ ١٦٩٨)» (a running number, then Abd al-Baqi's), or a number with a slash: the Muwatta
# ت الأعظمي's own number before the hadith's («٤/ ١ - », «٢٢٣٧/ »), Musnad Ahmad's parts of one
# hadith («٨٥٧١/ ١ - »). Lines end in \n or \r. Verse numbers that a page break put at the head of
# a line («[الأحزاب:⏎٢٨ - ٢٩]») are no hadith, nor a date («٤/ ٧/ ١٤١٢ هـ»).
_START = re.compile(
    r"(?:^|[\r\n])[ \t]*("
    r"(?:[٠-٩]+[ \t]*/[ \t]*(?:(?:[٠-٩]+[ \t]*-[ \t]*)+|(?=[^\s٠-٩]))|(?:[٠-٩]+[ \t]*-[ \t]*)+)"
    r"(?![ \t]*[٠-٩]+\])(?:\([٠-٩]+(?:[ \t]*/[ \t]*[٠-٩]+)?\)[ \t]*)?)"
)
_TITLE = re.compile(r"<span data-type=['\"]title['\"][^>]*>(.*?)</span>", re.S)
# A title some editions leave unmarked (Ibn Majah, al-Tirmidhi, Bukhari): a line of its own opening
# with «باب», «كتاب» or «أبواب» — al-Tirmidhi numbers it «(١٤) باب…» or «(١٩٦) (١٩٧) باب…» — after a
# line that closed a hadith or a title, or before a hadith's number. The word stands as a heading — bare, «بابُ» or
# «بابٌ» — not as a word of a narration («كتابَ الله», «كتابِه», «…لكل أهل عمل⏎بابٌ من أبواب الجنة»).
_HEADING_WORD = "|".join(
    "".join(c + "[\u064b-\u0652\u0670]*" for c in word[:-1]) + word[-1] + "[\u064c\u064f]?"
    for word in ("باب", "كتاب", "أبواب")
)
_HEADING_LINE = r"[ \t]*(?:\([٠-٩]+\)[ \t]*)*(" + _HEADING_WORD + r")(?=[\s:،.])([^\r\n<]{0,250})"
_PLAIN_TITLES = (
    re.compile(r"(?:^|[\r\n])" + _HEADING_LINE + r"(?=[\r\n]+[ \t]*[٠-٩]+[ \t]*-)"),
    re.compile(r"(?:^|(?<=[>».)\]﴾\"])[ \t]*[\r\n]+)" + _HEADING_LINE),
)
_NARRATOR = re.compile(r"<a href=\"inr://man-(\d+)\">(.*?)</a>", re.S)
_MATN = re.compile(r"<hadeeth-\d+>(.*?)<hadeeth>", re.S)
_TAG = re.compile(r"<[^>]+>")
_PAGE_MARK = re.compile(r"⦗[٠-٩0-9]+⦘")  # the printed edition's page numbers, inside the text
_FOOTNOTE_MARK = re.compile(r"\s*\(¬?(?:[٠-٩0-9]{1,3}|\*)\)")  # «(١)» / «(¬١)» / «(¬*)»: a pointer to a footnote, not taken
# A rule the edition draws across a page («_________»). After it, words without diacritics are the
# printer's own (Muslim ط التركية closes each volume with «تم بحمد الله تعالى في المطبعة العامرة…»);
# a narration carries on with its diacritics (Musnad Ahmad).
_RULE = re.compile(r"_{3,}")
# «• ١١٠٢٠/ قال عبد الله…»: Musnad Ahmad's mark for a narration of Abdullah ibn Ahmad within a
# hadith, with the hadith's number repeated — the number is not part of the text.
_ADDITION_NUMBER = re.compile(r"(?<=•)[ \t]*[٠-٩]+[ \t]*/")
# The basmala on a line of its own before a book: as the glyph «﷽» (always before a book), or
# spelled out before a title (a letter quoted in a hadith may open with it too).
_SPELLED_BASMALA = "".join(" +" if c == " " else c + "[\u064b-\u0652\u0670]*" for c in "بسم الله الرحمن الرحيم")
_BASMALA_LINE = re.compile(
    r"(?:^|[\r\n])[ \t]*(?:-[ \t]*)?(?:﷽[ \t.]*(?=[\r\n]|$)|"
    + _SPELLED_BASMALA + r"[ \t.]*(?=[\r\n]*[ \t]*<span data-type=['\"]title))"
)
# A few pages keep their footnotes in the body, after a blank line, and none in the footnotes
# field: «…فأدركت (٣).⏎⏎= ومسلم (١١٧٨)…⏎(١) إسناده صحيح…» (Musnad Ahmad ط الرسالة).
_NOTES_IN_BODY = re.compile(r"[\r\n][ \t]*[\r\n]\s*(?=(?:= |\(¬?١\)))")
_VOWELLED = re.compile(r"[ً-ْ]")
# A number inside a narration: Bukhari splits one narration under several numbers («… ٣٠٠ - وكان»);
# not a range of verses («[الأحزاب: ٢٨ - ٢٩]»).
_INLINE_NUMBER = re.compile(r"(?<=\s)[٠-٩]+[ \t]*-[ \t]+(?![ \t]*[٠-٩]+\])")
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
    text = _ADDITION_NUMBER.sub("", text)
    text = _RULE.sub(" ", text).replace("¬", "")  # «¬»: a joining mark some editions leave in the text
    return " ".join(text.replace("\r", " ").split()).removesuffix(" [")  # a bracket the next page opens


def without_colophon(page: str) -> str:
    """The page without what the printer added after a rule (see _RULE)."""
    rule = _RULE.search(page)
    if rule is None:
        return page
    after = " ".join(_TAG.sub(" ", page[rule.end():]).split()[:12])
    return page if _VOWELLED.search(after) else page[:rule.start()]


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


def export_pages(shamela: Path, book: Book, work: Path) -> tuple[list[str], list[str], list[int]]:
    """The book's page bodies and footnotes, in the edition's order, and the pages that open a
    volume."""
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
        parts = [(i, part) for i, part in db.execute("select id, part from page order by id") if i in pages]
    finally:
        db.close()
    kept = [notes_apart(pages[i], feet[i]) for i, _ in parts]
    volumes = [n for n in range(1, len(parts)) if parts[n][1] != parts[n - 1][1]]
    return [body for body, _ in kept], [foot for _, foot in kept], volumes


def notes_apart(body: str, foot: str) -> tuple[str, str]:
    """A page's text and its footnotes, where the page keeps them in its text (see _NOTES_IN_BODY)."""
    found = None if foot.strip() else _NOTES_IN_BODY.search(body)
    if found is None:
        return body, foot
    return body[:found.start()], body[found.end():]


def split_hadiths(pages: list[str], feet: list[str] | None = None,
                  volumes: list[int] | None = None) -> list[Hadith]:
    """The numbered hadiths of a book, each with the chapter it falls under (and, given the
    pages' footnotes, the notes its marks point to). A hadith ends where the next one or a title
    begins, or where a volume opens (with its title page and introduction) or the basmala stands
    on its own line before a book."""
    pages = [without_colophon(page) for page in pages]
    text = "\n".join(pages)
    starts = list(itertools.accumulate((len(p) + 1 for p in pages), initial=0))
    # Where every hadith starts and every title stands, in the order of the book.
    marks = [(m.start(1), "hadith", m) for m in _START.finditer(text)]
    marks += [(m.start(), "title", m) for m in _TITLE.finditer(text)]
    plain_titles = {m.start(1): m for rule in _PLAIN_TITLES for m in rule.finditer(text)}
    marks += [(m.start(), "title", m) for m in plain_titles.values()]
    marks += [(m.start(), "end", m) for m in _BASMALA_LINE.finditer(text)]
    marks += [(starts[n], "end", None) for n in volumes or []]
    marks.sort(key=lambda mark: (mark[0], mark[1] != "end"))
    hadiths: list[Hadith] = []
    kitab = bab = ""
    for i, (_start, kind, match) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if kind == "end":
            continue
        if kind == "title":
            title = plain("".join(match.groups()))
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
    parts = re.split(r"\(¬?([٠-٩]{1,3})\)\s*", foot or "")
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


# A narration opens with one of these words (matched without diacritics); a record that repeats an
# earlier number and opens without any is not a hadith — the introduction Musnad Ahmad ط الرسالة
# puts at the head of every volume («نسخة المكتبة القادرية ببغداد، ورمزها (ق)…», «وضعنا رقم
# الجزء…»), or a chapter title the edition left unmarked. A hadith split under its own number
# («قال: فحدثت…») keeps its first number and stays.
_NARRATION = re.compile(
    r"(?:^|\s)[وف]?(?:حدثنا|حدثني|حدثناه|حدثنيه|أخبرنا|أخبرني|أنبأنا|أنبأني|ثنا|عن|سمعت|سمع|قال|"
    r"قالت|أن|كان|رأيت|بلغه|بلغني)(?=[\s:،.]|$)"
)
_OPENING_WORDS = 8
# The copyist's line that closes a book («كمل كتاب الصلاة، والحمد لله كثيرا»), numbered as a
# paragraph by the Muwatta ت الأعظمي.
_BOOK_CLOSED = re.compile(r"^(?:كمل|تم) (?:كتاب|الكتاب)")
_CLOSING_LINE_CHARS = 200
_ARABIC_LETTER = re.compile(r"[\u0621-\u064a]")


def narrations_only(records: list[HadithRecord]) -> list[HadithRecord]:
    """Without the records that are no hadith: empty ones (an edition prints «……» for a hadith it
    leaves out), the copyist's closing lines (see _BOOK_CLOSED), and repeated numbers that open
    with no narration (see _NARRATION)."""
    seen: set[str] = set()
    kept = []
    for record in records:
        first = record.id
        repeated = first in seen
        seen.add(first)
        if not _ARABIC_LETTER.search(record.text):
            continue
        bare = _DIACRITICS.sub("", record.text)
        if len(bare) < _CLOSING_LINE_CHARS and _BOOK_CLOSED.match(bare):
            continue
        opening = " ".join(bare.split()[:_OPENING_WORDS])
        if repeated and not _NARRATION.search(opening):
            continue
        kept.append(record)
    return kept


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
            pages, feet, volumes = export_pages(args.shamela, book, Path(work))
        hadiths = split_hadiths(pages, feet, volumes)
        coded_rulings(hadiths, book, feet)
        records = unique_ids(narrations_only(
            [r for h in hadiths if (r := to_record(h, book, args.hukm, args.mohaddith))]))
        out = args.out / f"{unicodedata.normalize('NFC', book.name)}.json"
        out.write_bytes(to_isnad_json(Collection(records)))
        with_chain = sum(1 for r in records if r.sanad)
        with_matn = sum(1 for r in records if r.matn)
        graded = sum(1 for r in records if r.hukm)
        print(f"{book.name}: {len(pages)} pages → {len(records)} hadiths "
              f"({with_chain} with their chain, {with_matn} with their matn marked, {graded} graded) → {out}")


if __name__ == "__main__":
    main()
