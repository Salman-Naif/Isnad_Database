"""
Connection to and querying of the vector database (ChromaDB).

The collection is created with the cosine metric, so the distance returned by a query is:
    distance = 1 - cosine_similarity
i.e. similarity = 1 - distance

Embeddings are always computed by EmbeddingService and passed in explicitly;
the collection has no embedding function of its own. The collection records the
embedding model it was built with, and refuses to mix vectors from another model.
Once emptied (every source deleted), it is recreated for the current model on the next
write — Chroma would otherwise keep expecting vectors of the old model's size.
"""

import logging
import threading
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.config import get_settings

# Telemetry is disabled below, but chromadb 0.6 still logs an error for every event
# it skips (a posthog version mismatch). Harmless — silence it.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# Chroma rejects very large single writes; stay well below its limit.
WRITE_BATCH_SIZE = 500
READ_PAGE_SIZE = 5000


class VectorStoreError(Exception):
    """The stored vectors can't be used as-is (message is shown to the admin)."""


class VectorStore:
    """Wrapper around the ChromaDB client."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._collection = None
        self._lock = threading.Lock()

    def _connect(self):
        """Open a persistent connection to the on-disk database (once)."""
        if self._collection is None:
            with self._lock:
                if self._collection is None:
                    import chromadb
                    from chromadb.config import Settings as ChromaSettings

                    Path(self.settings.chroma_dir).mkdir(parents=True, exist_ok=True)
                    self._client = chromadb.PersistentClient(
                        path=self.settings.chroma_dir,
                        settings=ChromaSettings(anonymized_telemetry=False),
                    )
                    self._collection = self._client.get_or_create_collection(
                        name=self.settings.collection_name,
                        metadata=self._metadata(),
                        embedding_function=None,
                    )
        return self._collection

    def _metadata(self) -> dict[str, Any]:
        return {
            "hnsw:space": "cosine",
            "embedding_model": self.settings.embedding_model,
            "embedding_dimensions": self.settings.embedding_dimensions,
        }

    def _renew_if_empty_and_outdated(self) -> None:
        """An empty collection built for another embedding model is recreated for the current one.

        Deleting every source empties the collection but Chroma keeps the old vector size, so
        after a model change the first upload would be refused. Nothing is lost: it is empty.
        """
        collection = self._connect()
        meta = collection.metadata or {}
        outdated = (meta.get("embedding_model") != self.settings.embedding_model
                    or meta.get("embedding_dimensions") != self.settings.embedding_dimensions)
        if outdated and collection.count() == 0:
            with self._lock:
                logger.info("Recreating the empty collection for %s", self.settings.embedding_model)
                self._client.delete_collection(self.settings.collection_name)
                self._collection = self._client.create_collection(
                    name=self.settings.collection_name, metadata=self._metadata(), embedding_function=None,
                )

    def stored_dimensions(self) -> int | None:
        """Vector length of the stored vectors (None when there are none, or for a collection
        built before it was recorded)."""
        collection = self._connect()
        if collection.count() == 0:
            return None
        return (collection.metadata or {}).get("embedding_dimensions")

    def model_mismatch(self) -> str | None:
        """Why the stored vectors don't match EMBEDDING_MODEL / EMBEDDING_DIMENSIONS, or None."""
        collection = self._connect()
        if collection.count() == 0:
            return None
        meta = collection.metadata or {}
        built_with = meta.get("embedding_model")
        built_dims = meta.get("embedding_dimensions")
        if built_with != self.settings.embedding_model:
            return (
                f"قاعدة البيانات مبنية بنموذج {built_with or 'قديم'} والنموذج الحالي "
                f"{self.settings.embedding_model} — احذف المصادر وارفعها من جديد"
            )
        if built_dims is not None and built_dims != self.settings.embedding_dimensions:
            return (
                f"قاعدة البيانات مبنية بمتجهات {built_dims} بُعدًا والإعداد الحالي "
                f"{self.settings.embedding_dimensions} — أعد EMBEDDING_DIMENSIONS إلى {built_dims} "
                "أو احذف المصادر وارفعها من جديد"
            )
        return None

    def _check_dimensions(self, vectors: Sequence[Sequence[float]]) -> None:
        expected = self.settings.embedding_dimensions
        wrong = next((len(v) for v in vectors if len(v) != expected), None)
        if wrong is not None:
            raise VectorStoreError(f"متجه بـ{wrong} بُعدًا لا يطابق قاعدة البيانات ({expected} بُعدًا)")

    def _check_model(self) -> None:
        problem = self.model_mismatch()
        if problem:
            raise VectorStoreError(problem)

    def count(self) -> int:
        """Number of items currently indexed."""
        return self._connect().count()

    def upsert(
        self,
        ids: list[str],
        embeddings: Sequence[Sequence[float]],  # a list of lists, or a 2-D numpy array
        metadatas: list[dict[str, Any]],
        documents: list[str] | None = None,
    ) -> None:
        """Insert or replace items, in batches. Texts normally live in the passages table
        (app/services/text_index.py); `documents` stores them in Chroma as well."""
        self._renew_if_empty_and_outdated()
        self._check_model()
        self._check_dimensions(embeddings)
        from chromadb.errors import ChromaError

        collection = self._connect()
        for start in range(0, len(ids), WRITE_BATCH_SIZE):
            end = start + WRITE_BATCH_SIZE
            try:
                collection.upsert(
                    ids=ids[start:end],
                    documents=documents[start:end] if documents is not None else None,
                    embeddings=embeddings[start:end],
                    metadatas=metadatas[start:end],
                )
            except (ChromaError, ValueError) as exc:  # e.g. a vector size the index refuses
                raise VectorStoreError(f"رفضت قاعدة البيانات المتجهية الحفظ: {exc}") from exc

    def delete_source(self, source: str) -> int:
        """Delete every item that came from a given source. Returns how many were removed."""
        existing = self.ids_of(source)
        self.delete_ids(existing)
        return len(existing)

    def compact(self) -> None:
        """Give the disk space of deleted items back: SQLite files never shrink on their own.

        Chroma's own `chroma utils vacuum`, done in place: drop the write-ahead log already
        applied to the index, then rewrite the file without its free pages. An emptied
        collection is recreated first, so nothing of the old index is kept.
        """
        from chromadb.db.impl.sqlite import SqliteDB

        collection = self._connect()
        if collection.count() == 0:
            with self._lock:
                self._client.delete_collection(self.settings.collection_name)
                self._collection = self._client.create_collection(
                    name=self.settings.collection_name, metadata=self._metadata(), embedding_function=None,
                )
        sqlite = self._client._system.instance(SqliteDB)
        sqlite.purge_log(collection_id=self._collection.id)
        sqlite.vacuum()

    def ids_of(self, source: str) -> list[str]:
        """Ids of every item that came from a given source."""
        return self._connect().get(where={"source": source}, include=[])["ids"]

    def delete_ids(self, ids: list[str]) -> None:
        collection = self._connect()
        for start in range(0, len(ids), WRITE_BATCH_SIZE):
            collection.delete(ids=ids[start:start + WRITE_BATCH_SIZE])

    def get(self, ids: list[str]) -> list[dict[str, Any]]:
        """Items by id (text and metadata), in the order asked; unknown ids are left out."""
        if not ids:
            return []
        raw = self._connect().get(ids=ids, include=["documents", "metadatas"])
        found = {
            id_: {"id": id_, "text": doc or "", "metadata": meta or {}}
            for id_, doc, meta in zip(raw["ids"], raw["documents"], raw["metadatas"], strict=False)
        }
        return [found[i] for i in ids if i in found]

    def list_sources(self) -> list[dict[str, Any]]:
        """Indexed sources with their kind and number of chunks."""
        collection = self._connect()
        counts: Counter[tuple[str, str]] = Counter()
        offset = 0
        while True:
            page = collection.get(include=["metadatas"], limit=READ_PAGE_SIZE, offset=offset)
            for meta in page["metadatas"] or []:
                meta = meta or {}
                counts[(meta.get("source", ""), meta.get("type", "document"))] += 1
            if len(page["ids"]) < READ_PAGE_SIZE:
                break
            offset += READ_PAGE_SIZE
        return [
            {"source": source, "kind": kind, "chunks": n}
            for (source, kind), n in sorted(counts.items())
        ]

    def list_topics(self) -> list[dict[str, Any]]:
        """Topics of the structured hadiths with how many hadiths each has."""
        collection = self._connect()
        counts: Counter[str] = Counter()
        offset = 0
        while True:
            page = collection.get(
                where={"type": "structured_hadith"},
                include=["metadatas"],
                limit=READ_PAGE_SIZE,
                offset=offset,
            )
            for meta in page["metadatas"] or []:
                if meta and meta.get("topic"):
                    counts[meta["topic"]] += 1
            if len(page["ids"]) < READ_PAGE_SIZE:
                break
            offset += READ_PAGE_SIZE
        return [{"name": name, "count": n} for name, n in counts.most_common()]

    def query(self, embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """Find the texts closest to a given vector.

        Returns for each result: the id, the text, the metadata (ruling, sanad, topic,
        source) and the similarity computed from the distance.
        """
        collection = self._connect()
        if collection.count() == 0:
            return []
        self._check_model()
        self._check_dimensions([embedding])
        raw = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {
                "id": id_,
                "text": doc or "",
                "metadata": meta or {},
                "similarity": max(0.0, 1.0 - dist),
            }
            for id_, doc, meta, dist in zip(
                raw["ids"][0], raw["documents"][0], raw["metadatas"][0], raw["distances"][0], strict=False
            )
        ]

    def query_by_topic(self, topic: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch hadiths for a given topic without semantic search."""
        raw = self._connect().get(
            where={"topic": topic}, limit=limit, include=["documents", "metadatas"]
        )
        return [
            {"id": id_, "text": doc or "", "metadata": meta or {}}
            for id_, doc, meta in zip(raw["ids"], raw["documents"], raw["metadatas"], strict=False)
        ]
