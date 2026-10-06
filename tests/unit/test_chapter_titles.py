"""Unit tests: chapter titles are compared with the title searched for, each embedded once."""

import numpy as np

from app.services import chapter_titles


class CountingEmbedder:
    def __init__(self):
        self.embedded: list[str] = []

    def encode(self, texts, progress=None):
        self.embedded.extend(texts)
        return np.array([[1.0, 0.0] if "صدق" in t else [0.0, 1.0] for t in texts], dtype=np.float32)

    def encode_title_query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


def test_the_closest_chapter_scores_highest_and_each_title_is_embedded_once(monkeypatch):
    monkeypatch.setattr(chapter_titles, "_vectors", chapter_titles._TitleVectors())
    embedder = CountingEmbedder()
    chapters = ["باب فضل الصدقة", "باب مواقيت الصلاة", "باب فضل الصدقة", ""]
    first = chapter_titles.closeness(embedder, "الصدقة", chapters)
    assert first == {"باب فضل الصدقة": 1.0, "باب مواقيت الصلاة": 0.0}
    chapter_titles.closeness(embedder, "الزكاة", chapters)
    assert len(embedder.embedded) == 2  # the second search found both titles in memory


def test_the_oldest_titles_leave_memory_first(monkeypatch):
    monkeypatch.setattr(chapter_titles, "_vectors", chapter_titles._TitleVectors(size=2))
    embedder = CountingEmbedder()
    for title in ("باب أ", "باب ب", "باب ج"):
        chapter_titles.closeness(embedder, "س", [title])
    chapter_titles.closeness(embedder, "س", ["باب أ"])
    assert embedder.embedded.count("باب أ") == 2  # left memory when «باب ج» came, embedded again
