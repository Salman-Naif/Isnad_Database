"""Unit tests: the indexes are searched once at startup, before /health answers."""

import app.main as main


class Store:
    def __init__(self, count=5, fail=False):
        self.queries, self._count, self.fail = [], count, fail

    def count(self):
        if self.fail:
            raise RuntimeError("disk")
        return self._count

    def query(self, embedding, top_k=5):
        self.queries.append((len(embedding), top_k))
        return []


def test_the_vector_index_is_searched_once_with_a_vector_of_its_size(monkeypatch):
    store = Store()
    monkeypatch.setattr(main, "get_vector_store", lambda: store)
    main.warm_up()
    assert store.queries == [(main.settings.embedding_dimensions, 1)]


def test_an_empty_or_broken_store_does_not_stop_the_service(monkeypatch):
    empty = Store(count=0)
    monkeypatch.setattr(main, "get_vector_store", lambda: empty)
    main.warm_up()
    assert empty.queries == []
    monkeypatch.setattr(main, "get_vector_store", lambda: Store(fail=True))
    main.warm_up()  # logged, not raised
