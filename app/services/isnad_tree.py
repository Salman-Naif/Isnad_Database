"""
Chains of narration (isnad) read from a hadith's own text, and drawn as a tree.

The public datasets keep the chain inside the narration: «حدثنا قتيبة، حدثنا أبو عوانة، عن
سماك، ح وحدثنا هناد، حدثنا وكيع، عن إسرائيل، عن سماك، عن مصعب بن سعد، عن ابن عمر، عن النبي
صلى الله عليه وسلم قال …». The chain is the part before the Prophet ﷺ is named; narrators are
separated by the words of transmission (حدثنا، أخبرنا، عن، سمعت، قال، أن …); «ح» starts another
chain of the same hadith, which joins the main one at a shared narrator.

The tree is rooted at the Prophet ﷺ (or, for a saying of a companion or a later narrator, at
the earliest narrator named) and branches towards the compilers: each path from the root to a
leaf is one chain, ending with the book's author.

This is read automatically from the wording, not taken from an isnad database: names are kept
as they are written, and a phrase the reader can't tell from a name may slip in. The page says
so. A hadith uploaded with its own structured sanad (Isnad's JSON format) uses that instead.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from app.models.schemas import Narrator
from app.services import books
from app.services.text_processing import clean

PROPHET = "النبي ﷺ"

# Where the chain ends: the Prophet ﷺ named (after clean(), «ﷺ» reads «صلى الله عليه وسلم»).
_PROPHET_NAMED = re.compile(r"صلى الله عليه وسلم")
# «ح» (تحويل): another chain of the same hadith begins.
# «ح وحدثنا», or «ح و حدثنا» with the و apart (consumed, so it isn't read as a name).
_TAHWIL = re.compile(r"(?:^|[\s،,])ح\s*[،,]?\s+(?:و\s+)?(?=و?(?:حدث|أخبر|أنبأ|ثنا))")
# Words of transmission between two narrators (with an optional و / ف before them).
_LINKS = (
    "حدثنا|حدثني|حدثناه|حدثنيه|حدثه|حدثهم|حدثتني|أخبرنا|أخبرني|أخبرناه|أخبره|أخبرهم|أخبرتني|"
    "أنبأنا|أنبأني|نبأنا|ثنا|سمعت|سمعنا|سمع|عن|قال|قالت|قالا|قالوا|يقول|تقول|يحدث|أنه|أنها|أن|"
    "أنهم|إن|أخبرته|ذكر|بلغني|بلغه|رواه|قرأت على|قرأت"
)
_SEPARATOR = re.compile(rf"([،,:؛\"«»()\[\]\-–]|\b[وف]?(?:{_LINKS})\b)")
_HONORIFIC = re.compile(r"رض[يى] الله (?:تعالى )?عن(?:ه|ها|هما|هم)|رحمه الله|عليه السلام|صلى الله عليه وسلم")
# Words that end a name: what follows is the story, a clarification, or the text itself.
_STOP_WORDS = {
    "لما", "إذا", "اذا", "كان", "كانت", "على", "في", "وهو", "وهي", "يعني", "وهذا", "هذا", "رفعه",
    "يرفعه", "مرفوعا", "نحوه", "بنحوه", "مثله", "بمثله", "بإسناده", "بهذا", "بهذه", "الحديث", "ما",
    "لا", "ثم", "حين", "أمر", "رأيت", "رأى", "أتى", "جاء", "قام", "دخل", "خرج", "سئل", "سأل",
    "يوما", "وكان", "فقال", "فقالت", "قد", "لقد", "من", "إلى", "الى", "حتى", "واللفظ", "بمثل", "بنحو",
}
# Narrators whose name begins with و — not "and so-and-so".
_WAW_NAMES = {"وكيع", "وهب", "وهيب", "واصل", "وائل", "ورقاء", "وبرة", "وراد", "وحشي", "وابصة", "وردان"}
# A single word that can't identify a narrator on its own.
_TOO_GENERIC = {"عبد", "الآخران", "الآخرون", "غيره", "أبي", "أبيه", "جده", "أمه", "رجل", "رجلا", "أصحابه", "أحد"}
MAX_NAME_WORDS = 7
MIN_CHAIN = 2  # fewer names than this is more likely a stray phrase than a chain
MAX_CHAIN = 20


@dataclass
class Node:
    name: str
    children: list["Node"] = field(default_factory=list)
    grade: str | None = None

    def child(self, name: str, grade: str | None = None) -> "Node":
        for existing in self.children:
            if same_narrator(existing.name, name):
                return existing
        node = Node(name, grade=grade)
        self.children.append(node)
        return node

    def as_dict(self) -> dict:
        return {"name": self.name, "grade": self.grade, "children": [c.as_dict() for c in self.children]}


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKC", name)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    words = [w.removeprefix("ال") for w in text.split()]
    return " ".join(words)


def same_narrator(a: str, b: str) -> bool:
    """The same name, ignoring hamza forms and the article («الليث» = «ليث»)."""
    return _key(a) == _key(b)


def _joins(short: str, long: str) -> bool:
    """A narrator named shortly in one chain and fully in another («سماك» / «سماك بن حرب»)."""
    a, b = _key(short).split(), _key(long).split()
    if not a or len(a) > len(b) or b[: len(a)] != a:
        return False
    return len(a) >= 2 or a[0] not in {"عبد", "محمد", "احمد", "علي", "عمر", "ابو", "ابي", "ابن"}


# Words that open the text of a narration, never a name («قال دخلت على …», «أن ناسا …»).
_TEXT_OPENERS = {
    "دخلت", "دخل", "دخلنا", "كان", "كانت", "كنت", "كنا", "إن", "إنما", "أن", "ما", "لا", "لم", "أمرنا",
    "أمر", "نهانا", "نهى", "بينما", "بينا", "فبينا", "فبينما", "أرسل", "أرسله", "أرسلني", "سألت", "سأل",
    "سئل", "رأيت", "رأى", "أتى", "أتيت", "أتانا", "جاء", "جئت", "خرج", "خرجنا", "قام", "صليت", "صلى",
    "صلينا", "فتلت", "سمعته", "سمعه", "أول", "إذا", "لما", "يا", "هل", "من", "أي", "كيف", "لقي", "مر",
    "بعث", "بعثني", "شهدت", "حججنا", "غزونا", "أقبل", "أصاب", "أصبنا", "نزل", "توفي", "مات", "اشترى",
    "باع", "أعطى", "قدم", "قدمنا", "قلت", "قلنا", "فقلت", "ألا", "لو", "لقد", "قيل", "حضرت", "ناسا",
    "رجلا", "امرأة", "نعم", "والله", "ينبغي",
}
# Common words that a stray separator can leave on their own.
_NOT_NAMES = {"الصلاة", "الناس", "القوم", "الوضوء", "الماء", "حديثه", "لفظه", "الحديث", "مثله", "نحوه", "جميعا"}
# Words that can only introduce a narrator; after any other separator («قال», «أن», «:») the
# text may have begun, so a name is only taken there when it is plainly one.
_STRONG_LINKS = re.compile(r"^[وف]?(?:حدث|أخبر|أنبأ|نبأ|ثنا|سمع|عن$|قرأت|بلغ)")
_CLARIFIES = ("يعني", "وهو", "هو")
_PROPHET_WORDS = re.compile(r"رسول الله|النبي|نبي الله|رسول")

# The grammar of a narrator's name: «أبو بكر بن أبي شيبة», «عبد الله بن مسلمة القعنبي»,
# «كريب مولى ابن عباس». A word that fits none of it ends the name.
_NAME_PREFIX = {"أبو", "أبي", "أبا", "أم", "عبد", "ابن", "ابنة", "بنت", "ذو", "ذي"}
_NASAB = {"بن", "ابن", "بنت", "مولى", "مولاة", "أخي", "أخو", "أخا", "زوج"}
MAX_NISBAS = 3


def _unit(words: list[str], i: int) -> int | None:
    """End of one name unit at i («عبد الله», «ابن أبي ذئب», «هشام»), or None."""
    if i >= len(words) or words[i] in _STOP_WORDS or words[i] in _TEXT_OPENERS or words[i] in ("بن", "بنت"):
        return None
    if words[i] in _NAME_PREFIX and i + 1 < len(words) and words[i + 1] not in ("بن", "بنت"):
        return _unit(words, i + 1) or i + 1
    return i + 1


def _parse_name(words: list[str], i: int = 0) -> int:
    """End of the narrator's name that starts at i (i itself when there is none)."""
    end = _unit(words, i)
    if end is None:
        return i
    nisbas = 0
    while end < len(words):
        if end + 1 < len(words) and words[end] in _NASAB and (nxt := _unit(words, end + 1)) is not None:
            end = nxt  # «… بن معاذ», «… مولى ابن عباس»
        elif nisbas < MAX_NISBAS and _is_nisba(words[end]):
            end, nisbas = end + 1, nisbas + 1  # «… العنبري», «عبيد الله …»
        else:
            break
    return end


def _is_nisba(word: str) -> bool:
    return word.startswith("ال") and len(word) > 3 and word not in _NOT_NAMES and word not in _STOP_WORDS


def _plainly_a_name(words: list[str]) -> bool:
    """A name that can't be the start of a sentence: it has a kunya or a «بن»."""
    return len(words) > 1 and (words[0] in _NAME_PREFIX or any(w in _NASAB for w in words[1:]))


def _names_in(piece: str) -> tuple[list[str], bool]:
    """The narrators named in a piece (several when they narrated together), and whether the
    piece held nothing but names."""
    words = _HONORIFIC.sub(" ", piece).split()
    found: list[str] = []
    i = 0
    while i < len(words):
        end = _parse_name(words, i)
        if end == i:
            break
        name = words[i:end]
        # «الحميدي عبد الله بن الزبير»: a laqab, then the full name of the same man.
        if len(name) == 1 and name[0].startswith("ال") and not found:
            rest = _parse_name(words, end)
            if rest > end + 1:
                name, end = words[i:rest], rest
        found.append(" ".join(name))
        i = end
        # «… القواريري وإسحاق بن إبراهيم»: another narrator who heard it with him.
        # («وهو يخطب» is the story, not a narrator called «هو».)
        if (i < len(words) and words[i].startswith("و") and len(words[i]) > 2 and words[i] not in _WAW_NAMES
                and words[i] not in _STOP_WORDS):
            words[i] = words[i][1:]
            continue
        break
    return found, bool(found) and i == len(words)


def _usable(name: str) -> bool:
    first = name.split()[0]
    return (
        name not in _TOO_GENERIC and name not in _NOT_NAMES and first not in _TEXT_OPENERS
        and not _PROPHET_WORDS.search(name) and len(name.split()) <= MAX_NAME_WORDS
    )


def _chain(part: str, ends_at_prophet: bool) -> list[str]:
    """Narrators of one chain, in the order written (the compiler's teacher first)."""
    pieces = [p for p in _SEPARATOR.split(part) if p and p.strip()]
    # The words right before the Prophet ﷺ is named refer to him («قال رسول الله») or
    # begin the story («بينما نحن …»): they are not a narrator.
    if ends_at_prophet and pieces and not _SEPARATOR.fullmatch(pieces[-1]):
        pieces.pop()
    names: list[str] = []
    previous = ""
    for piece in pieces:
        if _SEPARATOR.fullmatch(piece):
            if piece.strip() not in ("-", "–") or not previous:
                previous = piece.strip()
            continue
        raw = piece.strip()
        first = raw.split()[0]
        if first in _CLARIFIES and names:  # «عبد العزيز - يعني ابن محمد -»
            detail = raw.split()[1:]
            # Only a name is a clarification of the narrator; «وهو يخطب الناس» is the story.
            if detail and len(detail) <= 4 and _parse_name(detail) == len(detail):
                names[-1] = f"{names[-1]} ({' '.join(detail)})"
            continue
        if first in ("وهذا", "واللفظ", "وهذه", "جميعا"):
            continue
        if names and raw in ("أبي", "أبيه"):  # «حدثنا أبي»: the previous narrator's father
            names.append(f"والد {names[-1]}")
            continue
        strong = not previous or bool(_STRONG_LINKS.match(previous))
        together = first.startswith("و") and len(first) > 2 and first not in _WAW_NAMES
        found, only_names = _names_in(raw[1:] if together else raw)
        found = [n for n in found if _usable(n)]
        honoured = bool(_HONORIFIC.search(raw))
        plain = bool(found) and (only_names or honoured or _plainly_a_name(found[0].split()))
        if not found or (not strong and not plain):
            if strong:
                continue  # an odd piece in the chain; the next link goes on
            break  # the text of the narration has begun
        if names and previous in ("،", ","):
            # «X، وY»: two who narrated it together; «أبو خيثمة، زهير بن حرب»: one man named twice.
            names[-1] = f"{names[-1]}{' و' if together else ' '}{' و'.join(found)}"
            continue
        names.append(" و".join(found))
    return names


def extract_chains(text: str) -> tuple[list[list[str]], bool]:
    """(chains in the order written, whether they reach the Prophet ﷺ)."""
    plain = clean(text)
    named = _PROPHET_NAMED.search(plain)
    head = plain[: named.start()] if named else plain[:400]
    parts = _TAHWIL.split(head)
    # Only the last «ح» chain runs on to the Prophet ﷺ; the others stop where they join it.
    chains = [_chain(part, bool(named) and i == len(parts) - 1) for i, part in enumerate(parts)]
    chains = [c for c in chains if c]
    if not named and chains:
        # A saying without the Prophet ﷺ: keep the names before the text starts.
        chains = [c[:6] for c in chains]
    return chains, bool(named)


def book_author(book: str) -> str:
    """The compiler of a book — the last link of every chain in it — from its title or a
    reference that names it («صحيح مسلم، 12»)."""
    found = books.find(book)
    return found.compiler_short if found else ""


def tree_from_text(text: str, book: str = "") -> Node | None:
    """The isnad tree of one narration (several branches when it has «ح» chains), or None
    when no chain of at least two narrators can be read from it."""
    chains, reaches_prophet = extract_chains(text)
    chains = [c[:MAX_CHAIN] for c in chains]
    if not chains or len(max(chains, key=len)) < MIN_CHAIN:
        return None
    main = max(chains, key=len)
    author = book_author(book)
    if any(same_narrator(author, n) or _joins(author, n) for n in main):
        author = ""  # the compiler is in the chain already («يحيى، عن مالك» in the Muwatta)
    ordered = list(reversed(main))  # from the source down to the compiler's teacher
    root = Node(PROPHET) if reaches_prophet else Node(ordered.pop(0))
    _add_path(root, ordered, author)
    for other in chains:
        if other is main:
            continue
        # A «ح» chain stops at the narrator where it joins the main one.
        path = _path_to(root, other[-1])
        if path is not None:
            _add_path(path, list(reversed(other[:-1])), author)
        elif len(other) < len(main):
            # No narrator in common: the chains ran side by side and both heard it from the
            # main chain's next narrator («يزيد بن هارون … ح … الليث بن سعد، قالا: أنبأنا يحيى»).
            path = _path_to(root, main[len(other)])
            if path is not None:
                _add_path(path, list(reversed(other)), author)
    return root


def tree_from_sanad(narrators: list[Narrator], book: str = "") -> Node | None:
    """The tree of a structured sanad (Isnad's JSON format, listed from the Prophet ﷺ)."""
    if not narrators:
        return None
    root = Node(narrators[0].name, grade=narrators[0].grade)
    node = root
    for n in narrators[1:]:
        node = node.child(n.name, n.grade)
    _add_author(node, book_author(book))
    return root


def tree_for(text: str, narrators: list[Narrator], book: str = "") -> tuple[Node | None, bool]:
    """(the tree to show, whether it was read from the wording rather than given)."""
    if narrators:
        return tree_from_sanad(narrators, book), False
    tree = tree_from_text(text, book)
    return tree, tree is not None


def _add_path(node: Node, names: list[str], author: str) -> None:
    for name in names:
        node = node.child(name)
    _add_author(node, author)


def _add_author(node: Node, author: str) -> None:
    """End the chain with the book's compiler, unless it already does («الإمام البخاري»)."""
    if author and _key(author) not in _key(node.name):
        node.child(author)


def _path_to(node: Node, name: str) -> Node | None:
    if same_narrator(node.name, name) or _joins(name, node.name) or _joins(node.name, name):
        return node
    for child in node.children:
        found = _path_to(child, name)
        if found:
            return found
    return None
