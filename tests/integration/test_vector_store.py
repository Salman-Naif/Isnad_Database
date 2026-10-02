"""Integration tests: the vector database guards against vectors of another model or size."""

import pytest

from app.services.vector_store import VectorStoreError


def test_vectors_from_another_model_are_refused(store, embedder, monkeypatch):
    store.upsert(["a"], [embedder.encode_one("نص")], [{"source": "a.txt"}])
    assert store.model_mismatch() is None

    store.settings = store.settings.model_copy(update={"embedding_model": "another/model"})
    assert "another/model" in store.model_mismatch()
    with pytest.raises(VectorStoreError):
        store.query(embedder.encode_one("نص"))


def test_store_refuses_vectors_of_another_size(store, embedder):
    with pytest.raises(VectorStoreError, match="بُعدًا"):
        store.upsert(["a"], [[0.1, 0.2, 0.3]], [{"source": "a.txt"}])
    store.upsert(["a"], [embedder.encode_one("نص")], [{"source": "a.txt"}])
    with pytest.raises(VectorStoreError):
        store.query([0.1, 0.2, 0.3])


def test_collection_records_its_dimensions(store, embedder):
    store.upsert(["a"], [embedder.encode_one("نص")], [{"source": "a.txt"}])
    assert store.stored_dimensions() == 64
    assert store.model_mismatch() is None

    store.settings = store.settings.model_copy(update={"embedding_dimensions": 512})
    assert "512" in store.model_mismatch()


def test_emptied_collection_takes_a_new_models_vectors(store, embedder):
    # What happened on Railway: sources indexed with the old model (1536-d) were all deleted,
    # the model was changed, and the next upload's vectors were refused by Chroma.
    old = store.settings.model_copy(update={"embedding_model": "openai/text-embedding-3-small",
                                            "embedding_dimensions": 3})
    new = store.settings
    store.settings = old
    store.upsert(["a"], [[0.1, 0.2, 0.3]], [{"source": "old.pdf"}])
    store.delete_source("old.pdf")

    store.settings = new
    assert store.stored_dimensions() is None and store.model_mismatch() is None
    store.upsert(["b"], [embedder.encode_one("نص")], [{"source": "new.csv"}])
    assert store.count() == 1 and store.stored_dimensions() == 64
    assert store.query(embedder.encode_one("نص"))[0]["id"] == "b"


def test_a_collection_with_old_vectors_is_never_dropped(store, embedder):
    store.upsert(["a"], [embedder.encode_one("نص")], [{"source": "kept.txt"}])
    store.settings = store.settings.model_copy(update={"embedding_model": "another/model"})
    with pytest.raises(VectorStoreError):
        store.upsert(["b"], [embedder.encode_one("نص")], [{"source": "new.txt"}])
    store.settings = store.settings.model_copy(update={"embedding_model": "qwen/qwen3-embedding-4b"})
    assert store.count() == 1  # the existing sources are still there


def test_chroma_write_errors_become_a_clear_message(store, embedder, monkeypatch):
    from chromadb.errors import InvalidDimensionException

    store.upsert(["a"], [embedder.encode_one("نص")], [{"source": "a.txt"}])
    collection = store._connect()

    def refuse(**kwargs):
        raise InvalidDimensionException("Embedding dimension 2560 does not match collection dimensionality 1536")

    monkeypatch.setattr(collection, "upsert", refuse)
    with pytest.raises(VectorStoreError, match="رفضت"):
        store.upsert(["b"], [embedder.encode_one("نص")], [{"source": "b.txt"}])
