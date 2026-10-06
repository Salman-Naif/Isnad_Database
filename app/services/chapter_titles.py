"""
Chapter titles as vectors, for a search by title.

The compilers' chapter titles («باب بر الوالدين», «باب ما جاء في فضل الصدقة») name what each hadith
is about. A title searched for («الصدقة», «الأم») is compared with the chapter titles of the texts
found, and the closest chapters come first. Measured on Sunan Ibn Majah and Jami' at-Tirmidhi,
30 one-word titles: texts from a chapter on the title among the first five went from 97 of 150
(the closest texts, then those holding its words) to 135 of 150 — «الصدقة» 0 → 5, «الجنة» 2 → 5.

Titles are embedded once, like stored texts (no instruction), and kept in memory.
"""

from collections import OrderedDict
from threading import Lock

import numpy as np

from app.services.embeddings import EmbeddingService
from app.services.text_processing import clean

MAX_TITLES = 5000  # ~20 MB of 1024-dimension vectors


class _TitleVectors:
    def __init__(self, size: int = MAX_TITLES) -> None:
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()
        self._size = size
        self._lock = Lock()

    def get_many(self, embedder: EmbeddingService, titles: list[str]) -> dict[str, np.ndarray]:
        with self._lock:
            known = {t: self._items[t] for t in titles if t in self._items}
            for t in known:
                self._items.move_to_end(t)
        new = [t for t in dict.fromkeys(titles) if t not in known]
        if new:
            vectors = embedder.encode([clean(t) for t in new])
            with self._lock:
                for t, v in zip(new, vectors, strict=True):
                    self._items[t] = v
                    known[t] = v
                while len(self._items) > self._size:
                    self._items.popitem(last=False)
        return known


_vectors = _TitleVectors()


def closeness(embedder: EmbeddingService, title: str, chapters: list[str]) -> dict[str, float]:
    """How close each chapter title is to the title searched for (cosine, −1–1)."""
    chapters = [c for c in dict.fromkeys(chapters) if c and c.strip()]
    if not chapters:
        return {}
    query = embedder.encode_title_query(clean(title))
    vectors = _vectors.get_many(embedder, chapters)
    return {c: float(np.dot(vectors[c], query)) for c in chapters}
