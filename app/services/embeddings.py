"""
Text to semantic embedding conversion, through the OpenRouter embeddings API.

No model runs on this server: texts are sent to EMBEDDING_MODEL on OpenRouter
(OPENROUTER_API_KEY) and vectors come back. This keeps the service at ~150 MB of
memory instead of ~800 MB with a local PyTorch model.

Large inputs are fast and light:
  - batches are sent EMBEDDING_CONCURRENCY at a time, and their order is kept; when the
    provider answers 429 ("slow down"), every request pauses for the time it asks and the
    number sent at once is halved, then grows back one by one as requests succeed;
  - vectors are requested as base64 (a quarter of the size of JSON numbers) and kept as
    float32 arrays (a tenth of the memory of Python lists of floats).

The same model must be used when building the database and when embedding
queries, otherwise the vectors are not comparable — see VectorStore, which
records the model a collection was built with.
"""

import base64
import binascii
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 520, 522, 524, 529}
# Waits between attempts after a failure (an error or an unusable reply).
RETRY_DELAYS = (2, 5, 10, 20, 30)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
MAX_RETRY_AFTER = 60  # seconds — the longest single pause a 429 can ask for
# 429 means "slow down", not "down": it is waited out for up to this long per batch before
# the upload is given up (measured: a 7,000-hadith book met a few minutes of 429s).
RATE_LIMIT_PATIENCE = 300  # seconds
RATE_LIMIT_PAUSES = (2, 5, 10, 20, 30, 60)
# Models that accept a "dimensions" parameter (they can return shorter vectors on request).
_RESIZABLE_PREFIXES = ("openai/text-embedding-3", "qwen/qwen3-embedding")


class _MalformedReply(Exception):
    """HTTP 200, but no usable list of vectors in the body."""


def _retry_after(res: httpx.Response) -> float:
    """Seconds the API asks to wait (Retry-After header), capped; 0 if it doesn't say."""
    try:
        return min(float(res.headers.get("retry-after", 0)), MAX_RETRY_AFTER)
    except ValueError:
        return 0


class EmbeddingError(Exception):
    """The embeddings API could not be reached or refused the request (message is shown)."""


class _Throttle:
    """How many requests may be in flight, shared by all threads of one service.

    A 429 halves the allowance and pauses everyone until the provider's wait is over; each
    run of successes lets one more request through again, up to the configured limit.
    """

    def __init__(self, limit: int) -> None:
        self.limit = self.allowed = max(1, limit)
        self.active = 0
        self.resume_at = 0.0
        self.successes = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self.resume_at and self.active < self.allowed:
                    self.active += 1
                    return
                delay = self.resume_at - now if now < self.resume_at else 0.05
            time.sleep(min(delay, 1.0))

    def release(self) -> None:
        with self._lock:
            self.active -= 1

    def succeeded(self) -> None:
        with self._lock:
            self.successes += 1
            if self.allowed < self.limit and self.successes >= 2 * self.allowed:
                self.allowed += 1
                self.successes = 0

    def slow_down(self, pause: float) -> None:
        with self._lock:
            self.allowed = max(1, self.allowed // 2)
            self.successes = 0
            self.resume_at = max(self.resume_at, time.monotonic() + pause)


class EmbeddingService:
    """Client for the embeddings API. One shared instance reuses its HTTP connections."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = httpx.Client(
            timeout=self.settings.embedding_timeout_seconds,
            limits=httpx.Limits(max_connections=self.settings.embedding_concurrency * 2),
        )
        self._throttle = _Throttle(self.settings.embedding_concurrency)

    def encode(self, texts: list[str], progress: Callable[[int, int], None] | None = None) -> np.ndarray:
        """Unit-length vectors for the texts, as a float32 array of shape (len(texts), dimensions),
        in the same order. `progress(done, total)` is called as batches finish."""
        size = self.settings.embedding_batch_size
        batches = [texts[start:start + size] for start in range(0, len(texts), size)]
        results: list[np.ndarray | None] = [None] * len(batches)
        done = 0
        workers = max(1, min(self.settings.embedding_concurrency, len(batches)))
        with ThreadPoolExecutor(workers, thread_name_prefix="embed") as pool:
            futures = {pool.submit(self._request, batch): i for i, batch in enumerate(batches)}
            try:
                for future in as_completed(futures):
                    index = futures[future]
                    results[index] = future.result()
                    done += len(batches[index])
                    if progress:
                        progress(done, len(texts))
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        if not results:
            return np.empty((0, self.settings.embedding_dimensions), dtype=np.float32)
        return np.vstack(results)

    def encode_one(self, text: str) -> np.ndarray:
        """Shortcut for embedding a single text."""
        return self.encode([text])[0]

    def encode_query(self, text: str) -> np.ndarray:
        """Embed a search query (with the model's query instruction, if it takes one)."""
        return self.encode_one(query_instruction(self.settings) + text)

    def encode_title_query(self, text: str) -> np.ndarray:
        """Embed a title searched for, to be compared with chapter titles («باب بر الوالدين»)."""
        return self.encode_one(title_instruction(self.settings) + text)

    def _request(self, batch: list[str]) -> np.ndarray:
        if not self.settings.openrouter_api_key:
            raise EmbeddingError("OPENROUTER_API_KEY غير مضبوط — لا يمكن إنشاء التمثيلات الدلالية")

        failures = 0  # errors and unusable replies
        rate_limited = 0  # 429s, waited out separately: they mean "slow down"
        started = time.monotonic()
        while True:
            self._throttle.acquire()
            try:
                res = self._client.post(
                    f"{self.settings.openrouter_base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.settings.openrouter_api_key}"},
                    json=self._payload(batch),
                )
            except httpx.HTTPError as exc:
                res, error = None, exc
            finally:
                self._throttle.release()

            if res is not None and res.status_code == 200:
                try:
                    vectors = self._parse(res.json(), len(batch), self.settings.embedding_dimensions)
                except _MalformedReply:
                    # An overloaded provider sometimes answers 200 with an error inside.
                    logger.warning("Embeddings API sent an unusable reply: %s", res.text[:300])
                    error = EmbeddingError("خدمة التمثيلات الدلالية أعادت ردًا غير صالح")
                else:
                    self._throttle.succeeded()
                    return vectors
            elif res is not None and res.status_code == 429:
                if time.monotonic() - started > RATE_LIMIT_PATIENCE:
                    raise EmbeddingError("خدمة التمثيلات الدلالية مزدحمة (429) — أعد رفع الملف بعد قليل")
                pause = max(_retry_after(res), RATE_LIMIT_PAUSES[min(rate_limited, len(RATE_LIMIT_PAUSES) - 1)])
                rate_limited += 1
                logger.warning("Embeddings API is rate limiting (429); pausing %ss", pause)
                self._throttle.slow_down(pause)
                continue
            elif res is not None:
                if res.status_code == 401:
                    raise EmbeddingError("مفتاح OpenRouter غير صالح")
                if res.status_code == 402:
                    raise EmbeddingError("رصيد OpenRouter غير كافٍ")
                logger.error("Embeddings API error %s: %s", res.status_code, res.text[:300])
                error = EmbeddingError(f"خدمة التمثيلات الدلالية أعادت خطأ ({res.status_code})")
                if res.status_code not in RETRY_STATUSES:
                    raise error

            failures += 1
            if failures >= MAX_ATTEMPTS:
                if isinstance(error, EmbeddingError):
                    raise error
                raise EmbeddingError("تعذّر الاتصال بخدمة التمثيلات الدلالية، حاول مرة أخرى") from error
            wait = RETRY_DELAYS[failures - 1]
            if res is not None:
                wait = max(wait, _retry_after(res))
            logger.warning("Embeddings attempt %d/%d failed; retrying in %ss", failures, MAX_ATTEMPTS, wait)
            time.sleep(wait)

    def _payload(self, batch: list[str]) -> dict:
        limit = self.settings.embedding_max_input_chars
        payload = {
            "model": self.settings.embedding_model,
            "input": [text[:limit] for text in batch],
            # Little-endian float32 bytes in base64: a quarter of the size of JSON numbers.
            "encoding_format": "base64",
        }
        if self.settings.embedding_model.startswith(_RESIZABLE_PREFIXES):
            payload["dimensions"] = self.settings.embedding_dimensions
        return payload

    def _parse(self, body: dict, expected: int, dimensions: int) -> np.ndarray:
        try:
            items = sorted(body["data"], key=lambda d: d["index"])
            if len(items) != expected:
                raise _MalformedReply
            vectors = np.vstack([_decode(item["embedding"]) for item in items])
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise _MalformedReply from exc
        if vectors.shape[1] != dimensions:
            # A vector of the wrong size can't be compared with the stored ones at all.
            raise EmbeddingError(
                f"النموذج {self.settings.embedding_model} أعاد متجهات بـ{vectors.shape[1]} بُعدًا "
                f"والمتوقع {dimensions} — اضبط EMBEDDING_DIMENSIONS على {vectors.shape[1]}"
            )
        # Normalized so cosine similarity is comparable across models.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vectors / norms).astype(np.float32)


QWEN3_QUERY_INSTRUCTION = "Instruct: ابحث عن الحديث النبوي الذي يطابق هذا النص\nQuery: "


def query_instruction(settings) -> str:
    """The text put before a search query (stored passages never get one)."""
    configured = settings.embedding_query_instruction
    if configured == "-":
        return ""
    if configured:
        return configured
    return QWEN3_QUERY_INSTRUCTION if settings.embedding_model.startswith("qwen/qwen3-embedding") else ""


QWEN3_TITLE_INSTRUCTION = "Instruct: ابحث عن عنوان الباب الذي يتناول هذا الموضوع\nQuery: "


def title_instruction(settings) -> str:
    """The text put before a title searched for among chapter titles (none when the query
    instruction is turned off, or the model takes none)."""
    return QWEN3_TITLE_INSTRUCTION if query_instruction(settings) else ""


def _decode(embedding) -> np.ndarray:
    """One vector from the API: base64 float32 bytes, or a plain list of numbers."""
    if isinstance(embedding, str):
        return np.frombuffer(base64.b64decode(embedding, validate=True), dtype="<f4")
    return np.asarray(embedding, dtype=np.float32)
