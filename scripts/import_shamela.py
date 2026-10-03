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
import glob
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
# A hadith starts a line with its number(s): «٢٠ - » or «٤٠٨ - ٤٠٩ - ». Lines end in \n or \r.
_START = re.compile(r"(?:^|[\r\n])[ \t]*((?:[٠-٩]+[ \t]*-[ \t]*)+)")
_TITLE = re.compile(r"<span data-type=['\"]title['\"][^>]*>(.*?)</span>", re.S)
_NARRATOR = re.compile(r"<a href=\"inr://man-(\d+)\">(.*?)</a>", re.S)
_MATN = re.compile(r"<hadeeth-\d+>(.*?)<hadeeth>", re.S)
_TAG = re.compile(r"<[^>]+>")
_PAGE_MARK = re.compile(r"⦗[٠-٩0-9]+⦘")  # the printed edition's page numbers, inside the text
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


@dataclass
class Hadith:
    numbers: list[int]
    raw: str  # the edition's markup, from the number to the next hadith or title
    topic: str
    narrators: list[str] = field(default_factory=list)


def plain(markup: str) -> str:
    """Readable text: no tags, page marks or inline numbers; honorifics spelled out."""
    text = _TAG.sub("", markup)
    text = _PAGE_MARK.sub("", text)
    for glyph, words in _HONORIFICS.items():
        text = text.replace(glyph, f" {words} ")
    text = _INLINE_NUMBER.sub("", text)
    return " ".join(text.replace("\r", " ").split())


def _bare(text: str) -> str:
    return _DIACRITICS.sub("", text).translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا"})).strip(" ،,.:؛")


def installed_books(shamela: Path) -> list[Book]:
    """The books of «كتب السنة» installed in this Shamela library."""
    master = sqlite3.connect(f"file:{shamela / 'database' / 'master.db'}?mode=ro", uri=True)
    try:
        categories = dict(master.execute("select category_id, category_name from category"))
        rows = master.execute("select book_id, book_name, book_category from book").fetchall()
    finally:
        master.close()
    found = {int(Path(p).stem): Path(p) for p in glob.glob(str(shamela / "database" / "book" / "*" / "*.db"))}
    return [Book(i, name, found[i]) for i, name, category in rows
            if i in found and categories.get(category) == HADITH_CATEGORY]


def export_pages(shamela: Path, book: Book, work: Path) -> list[str]:
    """The book's page bodies, in the edition's order."""
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
    pages = {}
    for line in out.read_text(encoding="utf-8").splitlines():
        page = json.loads(line)
        pages[page["page"]] = page["body"]
    db = sqlite3.connect(f"file:{book.path}?mode=ro", uri=True)
    try:
        order = [row[0] for row in db.execute("select id from page order by id")]
    finally:
        db.close()
    return [pages[i] for i in order if i in pages]


def split_hadiths(pages: list[str]) -> list[Hadith]:
    """The numbered hadiths of a book, each with the chapter it falls under."""
    text = "\n".join(pages)
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
        hadiths.append(Hadith(numbers, raw, bab or kitab))
    for hadith in hadiths:
        hadith.narrators = chain_of(hadith.raw)
    return hadiths


def chain_of(raw: str) -> list[str]:
    """The narrators linked before the Prophet's words, compiler's teacher first; empty when the
    narration has «ح» (several chains — the database reads those from the wording)."""
    head = raw.split("<hadeeth", 1)[0]
    links = list(_NARRATOR.finditer(head))
    names: list[str] = []
    for i, link in enumerate(links):
        name = plain(link.group(2)).strip(" ،,:؛")
        between = _bare(plain(head[links[i - 1].end():link.start()])) if i else ""
        if re.search(r"(?:^|\s)ح(?:\s|$)", between):
            return []
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
        sanad = ([Narrator(name=PROPHET)] if matn else []) + chain
    return HadithRecord(
        id=f"{book.id}-{'-'.join(map(str, hadith.numbers))}",
        text=text, matn=matn, sanad=sanad, topic=hadith.topic,
        source=books.title(book.name), hukm=hukm, mohaddith=mohaddith,
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
            pages = export_pages(args.shamela, book, Path(work))
        hadiths = split_hadiths(pages)
        records = unique_ids([r for h in hadiths if (r := to_record(h, book, args.hukm, args.mohaddith))])
        out = args.out / f"{unicodedata.normalize('NFC', book.name)}.json"
        out.write_bytes(to_isnad_json(Collection(records)))
        with_chain = sum(1 for r in records if r.sanad)
        with_matn = sum(1 for r in records if r.matn)
        print(f"{book.name}: {len(pages)} pages → {len(records)} hadiths "
              f"({with_chain} with their chain, {with_matn} with their matn marked) → {out}")


if __name__ == "__main__":
    main()
