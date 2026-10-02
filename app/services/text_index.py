"""
Passage texts, and the literal index (SQLite FTS5) that finds a passage containing the
visitor's words exactly.

Each passage's text is stored here once, as shown to visitors; the vector store keeps only
vectors and metadata (storing the text there too tripled the disk space: Chroma also indexes
it for its own full-text search). A hadith's matn vector shows its narration's text.

Semantic search compares meanings, so a hadith quoted word for word inside a long narration
(chain of narrators + text) scores well below 1. This index answers the simpler question
"do these exact words appear in an approved source?" — a quote found here is reported with
similarity 1.0. Text is compared without diacritics, punctuation or letter-form differences
(أ/إ/آ/ا, ى/ي, ة/ه), the way a visitor may type it.

Rows mirror the vector store's items (same ids), so both are written and deleted together.
"""

import re
import unicodedata

from app.db.sqlite import connection
from app.services.text_processing import ARABIC_DIACRITICS, TATWEEL

# A quote must be at least this long to count ("إنما الأعمال بالنيات"); common short phrases
# ("قال رسول الله") are then ruled out by how many passages contain them.
MIN_QUOTE_WORDS = 3
# A short phrase found in more passages than this is a formula, not a quote of one text.
# From LONG_QUOTE_WORDS words on it is a real quote even when many narrations repeat it
# (the same hadith through 30 chains); the first MAX_QUOTE_MATCHES are returned.
MAX_QUOTE_MATCHES = 20
LONG_QUOTE_WORDS = 8

_DELETE_BATCH = 500

_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_NOT_WORD = re.compile(r"[^\w]+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = TATWEEL.sub("", ARABIC_DIACRITICS.sub("", text)).translate(_LETTERS)
    return " ".join(_NOT_WORD.sub(" ", text).split())


# Words too common to tell two texts apart (compared after normalize()).
_STOPWORDS = {
    "من", "في", "علي", "عن", "الي", "ما", "لا", "ان", "قال", "قالت", "ثم", "او", "و", "ف", "ب", "ل",
    "هو", "هي", "هذا", "هذه", "ذلك", "التي", "الذي", "كان", "يا", "قد", "لم", "لن", "كل", "مع", "اذا",
}


def word_overlap(query: str, text: str) -> float:
    """Share of the query's meaningful words that appear in the text (0–1).

    An altered quote of a real hadith keeps most of its words; a saying that only happens to
    sound like one shares almost none with the hadith it lands on — the second signal, next
    to semantic similarity, for telling a distortion from text that is not in the sources.
    """
    words = [w for w in normalize(query).split() if w not in _STOPWORDS and len(w) > 1]
    if not words:
        return 0.0
    present = set(normalize(text).split())
    return round(sum(w in present for w in words) / len(words), 4)


def add(rows: list[tuple[str, str, str]]) -> None:
    """Store and index (item_id, source, text) rows."""
    with connection() as conn:
        for item_id, source, text in rows:
            rowid = conn.execute(
                "INSERT INTO passages (item_id, source, text) VALUES (?, ?, ?)", (item_id, source, text)
            ).lastrowid
            conn.execute("INSERT INTO passages_fts (rowid, body) VALUES (?, ?)", (rowid, normalize(text)))


def delete_ids(item_ids: list[str]) -> None:
    with connection() as conn:
        for start in range(0, len(item_ids), _DELETE_BATCH):
            batch = item_ids[start:start + _DELETE_BATCH]
            marks = ",".join("?" * len(batch))
            # Fixed SQL: only "?" placeholders are joined in; the ids are bound parameters.
            rowids = [r[0] for r in conn.execute(
                f"SELECT rowid FROM passages WHERE item_id IN ({marks})", batch)]  # noqa: S608  # nosec B608
            _delete_rows(conn, rowids)


def texts(item_ids: list[str]) -> dict[str, str]:
    """The stored text of each passage (a matn item's is its narration's)."""
    owners = {item_id: text_owner(item_id) for item_id in item_ids}
    wanted = sorted(set(owners.values()))
    found: dict[str, str] = {}
    with connection() as conn:
        for start in range(0, len(wanted), _DELETE_BATCH):
            batch = wanted[start:start + _DELETE_BATCH]
            marks = ",".join("?" * len(batch))
            # Fixed SQL: only "?" placeholders are joined in; the ids are bound parameters.
            query = f"SELECT item_id, text FROM passages WHERE item_id IN ({marks})"  # noqa: S608  # nosec B608
            found.update(conn.execute(query, batch).fetchall())
    return {item_id: found[owner] for item_id, owner in owners.items() if found.get(owner)}


MATN_SUFFIX = "~matn"


def text_owner(item_id: str) -> str:
    """The passage whose text an item shows: a hadith's matn vector shows its narration."""
    return item_id.removesuffix(MATN_SUFFIX)


def delete_source(source: str) -> None:
    with connection() as conn:
        rowids = [r[0] for r in conn.execute("SELECT rowid FROM passages WHERE source = ?", (source,))]
        _delete_rows(conn, rowids)


def _delete_rows(conn, rowids: list[int]) -> None:
    conn.executemany("DELETE FROM passages_fts WHERE rowid = ?", [(r,) for r in rowids])
    conn.executemany("DELETE FROM passages WHERE rowid = ?", [(r,) for r in rowids])


def find_quote(query: str) -> list[str]:
    """Ids of the passages containing the query word for word (empty if it's too short or
    too common to identify a text)."""
    words = normalize(query).split()
    if len(words) < MIN_QUOTE_WORDS:
        return []
    phrase = '"' + " ".join(words) + '"'  # an FTS5 phrase: these words, adjacent, in order
    with connection() as conn:
        rows = conn.execute(
            """SELECT p.item_id FROM passages_fts f JOIN passages p ON p.rowid = f.rowid
               WHERE passages_fts MATCH ? LIMIT ?""",
            (phrase, MAX_QUOTE_MATCHES + 1),
        ).fetchall()
    if len(rows) > MAX_QUOTE_MATCHES and len(words) < LONG_QUOTE_WORDS:
        return []
    return [r["item_id"] for r in rows[:MAX_QUOTE_MATCHES]]
