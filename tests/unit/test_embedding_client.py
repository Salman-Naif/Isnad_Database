"""Unit tests: the embeddings API client (OpenRouter), with the network replaced by a fake."""

import json
import math

import httpx
import pytest

from app.config import get_settings
from app.services import embeddings
from app.services.embeddings import EmbeddingError, EmbeddingService


class FakeClock:
    """time.sleep and time.monotonic for the client: waiting advances the clock instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(embeddings.time, "sleep", fake.sleep)
    monkeypatch.setattr(embeddings.time, "monotonic", fake.monotonic)
    return fake


@pytest.fixture
def service(monkeypatch, clock):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(get_settings(), "embedding_dimensions", 2)  # the fake API returns 2-D vectors
    return EmbeddingService()


def use(service: EmbeddingService, handler) -> list[dict]:
    """Route the service's HTTP calls to `handler`; returns the request bodies it received."""
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    service._client = httpx.Client(transport=httpx.MockTransport(record))
    return seen


def vectors_for(texts: list[str]) -> dict:
    # Unnormalized on purpose, in reverse order, like a real API may return them.
    data = [{"index": i, "embedding": [3.0, 4.0 + i]} for i in range(len(texts))]
    return {"data": list(reversed(data))}


def test_encode_sends_model_and_key_and_normalizes(service):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=vectors_for(json.loads(request.content)["input"]))

    bodies = use(service, handler)
    [vec] = service.encode(["اختبار"])

    assert bodies[0] == {"model": "qwen/qwen3-embedding-4b", "input": ["اختبار"], "dimensions": 2,
                         "encoding_format": "base64"}
    assert requests[0].headers["authorization"] == "Bearer sk-or-test"
    assert str(requests[0].url).endswith("/embeddings")
    assert vec == pytest.approx([0.6, 0.8])
    assert math.isclose(sum(v * v for v in vec), 1.0)


def test_results_keep_input_order(service):
    use(service, lambda r: httpx.Response(200, json=vectors_for(json.loads(r.content)["input"])))
    first, second = service.encode(["أ", "ب"])
    assert first == pytest.approx([3 / 5, 4 / 5])
    assert second == pytest.approx([3 / math.hypot(3, 5), 5 / math.hypot(3, 5)])


def test_large_inputs_are_batched(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 3)
    bodies = use(service, lambda r: httpx.Response(200, json=vectors_for(json.loads(r.content)["input"])))

    assert len(service.encode([f"نص {i}" for i in range(7)])) == 7
    assert [len(b["input"]) for b in bodies] == [3, 3, 1]


def test_transient_errors_are_retried(service):
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json=vectors_for(["x"]))])
    bodies = use(service, lambda r: next(responses))
    assert len(service.encode(["x"])) == 1
    assert len(bodies) == 3


def test_gives_up_after_the_last_retry(service):
    bodies = use(service, lambda r: httpx.Response(503))
    with pytest.raises(EmbeddingError):
        service.encode(["x"])
    assert len(bodies) == embeddings.MAX_ATTEMPTS


def test_a_busy_model_is_waited_for(service, clock):
    # The provider's "Model busy, retry later" (429), seen while indexing a 7,000-hadith book.
    replies = iter([httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "Model busy"}),
                    httpx.Response(429, json={"error": "Model busy"})])
    bodies = use(service, lambda r: next(replies, None) or httpx.Response(200, json=vectors_for(["x"])))
    assert len(service.encode(["x"])) == 1 and len(bodies) == 3
    # the API's own Retry-After (7 s), then the second pause of the schedule
    assert clock.slept == pytest.approx(7 + embeddings.RATE_LIMIT_PAUSES[1], abs=1)


def test_retry_after_is_capped(service, clock):
    replies = iter([httpx.Response(429, headers={"Retry-After": "3600"})])
    use(service, lambda r: next(replies, None) or httpx.Response(200, json=vectors_for(["x"])))
    service.encode(["x"])
    assert clock.slept == pytest.approx(embeddings.MAX_RETRY_AFTER, abs=1)


def test_rate_limits_are_waited_out_far_longer_than_errors(service, clock):
    # Many 429s in a row don't count as failures: only RATE_LIMIT_PATIENCE ends the wait.
    replies = iter([httpx.Response(429)] * (embeddings.MAX_ATTEMPTS + 3))
    bodies = use(service, lambda r: next(replies, None) or httpx.Response(200, json=vectors_for(["x"])))
    assert len(service.encode(["x"])) == 1
    assert len(bodies) == embeddings.MAX_ATTEMPTS + 4


def test_endless_rate_limiting_gives_up_with_a_clear_message(service, clock):
    use(service, lambda r: httpx.Response(429))
    with pytest.raises(EmbeddingError, match="429"):
        service.encode(["x"])
    assert clock.slept >= embeddings.RATE_LIMIT_PATIENCE


def test_throttle_halves_on_429_and_grows_back(clock):
    throttle = embeddings._Throttle(8)
    throttle.slow_down(5)
    assert throttle.allowed == 4
    start = clock.now
    throttle.acquire()  # waits out the pause
    assert clock.now - start >= 5
    throttle.release()
    for _ in range(8):
        throttle.succeeded()
    assert throttle.allowed == 5
    for _ in range(100):
        throttle.succeeded()
    assert throttle.allowed == 8  # never above the configured limit


def test_throttle_never_lets_more_than_allowed_through(clock):
    throttle = embeddings._Throttle(2)
    throttle.acquire()
    throttle.acquire()
    assert throttle.active == 2
    throttle.release()
    throttle.acquire()  # a free slot: no wait
    assert throttle.active == 2


@pytest.mark.parametrize("body", [{"error": {"message": "overloaded"}}, {"data": None}, {"data": []}])
def test_an_ok_reply_without_vectors_is_retried(service, body):
    replies = iter([httpx.Response(200, json=body)])
    bodies = use(service, lambda r: next(replies, None) or httpx.Response(200, json=vectors_for(["x"])))
    assert len(service.encode(["x"])) == 1 and len(bodies) == 2


def test_an_ok_reply_without_vectors_fails_clearly_in_the_end(service):
    use(service, lambda r: httpx.Response(200, json={"error": "overloaded"}))
    with pytest.raises(EmbeddingError, match="غير صالح"):
        service.encode(["x"])


@pytest.mark.parametrize(("status_code", "message"), [(401, "غير صالح"), (402, "رصيد")])
def test_key_and_credit_errors_are_explained(service, status_code, message):
    bodies = use(service, lambda r: httpx.Response(status_code))
    with pytest.raises(EmbeddingError, match=message):
        service.encode(["x"])
    assert len(bodies) == 1  # not retried


def test_missing_key(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "")
    with pytest.raises(EmbeddingError, match="OPENROUTER_API_KEY"):
        service.encode(["x"])


def test_wrong_vector_size_from_the_api_is_rejected(service):
    use(service, lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}))
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSIONS"):
        service.encode(["x"])


def test_dimensions_are_only_requested_from_models_that_support_them(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_model", "baai/bge-m3")
    bodies = use(service, lambda r: httpx.Response(200, json=vectors_for(["x"])))
    service.encode(["x"])
    assert "dimensions" not in bodies[0]


def test_very_long_input_is_cut_before_embedding(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_max_input_chars", 10)
    bodies = use(service, lambda r: httpx.Response(200, json=vectors_for(["x"])))
    service.encode(["ب" * 50])
    assert bodies[0]["input"] == ["ب" * 10]


# --- base64 vectors, float32 arrays, parallel batches ---

import base64  # noqa: E402

import numpy as np  # noqa: E402


def b64(vector) -> str:
    return base64.b64encode(np.asarray(vector, dtype="<f4").tobytes()).decode()


def test_base64_vectors_are_decoded_and_normalized(service):
    use(service, lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": b64([3.0, 4.0])}]}))
    vectors = service.encode(["x"])
    assert vectors.dtype == np.float32 and vectors.shape == (1, 2)
    assert vectors[0] == pytest.approx([0.6, 0.8])


def test_corrupt_base64_is_an_unusable_reply(service, clock):
    replies = iter([httpx.Response(200, json={"data": [{"index": 0, "embedding": "not base64!"}]})])
    use(service, lambda r: next(replies, None) or httpx.Response(200, json={"data": [{"index": 0, "embedding": b64([1, 0])}]}))
    assert service.encode(["x"])[0] == pytest.approx([1.0, 0.0])


def test_parallel_batches_keep_the_input_order(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
    monkeypatch.setattr(get_settings(), "embedding_concurrency", 4)

    def handler(request):
        texts = json.loads(request.content)["input"]
        # each text's vector encodes its number, so order can be checked
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [float(t), 1.0]} for i, t in enumerate(texts)]})

    use(service, handler)
    progress = []
    vectors = service.encode([str(n) for n in range(1, 10)], lambda done, total: progress.append(done))
    ratios = vectors[:, 0] / vectors[:, 1]
    assert ratios == pytest.approx(list(range(1, 10)), rel=1e-5)
    assert sorted(progress) == progress and progress[-1] == 9


def test_no_texts_no_requests(service):
    bodies = use(service, lambda r: httpx.Response(500))
    assert service.encode([]).shape == (0, get_settings().embedding_dimensions) and bodies == []


def test_queries_carry_the_instruction_but_passages_do_not(service, monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_model", "qwen/qwen3-embedding-4b")
    bodies = use(service, lambda r: httpx.Response(200, json=vectors_for(json.loads(r.content)["input"])))
    service.encode(["نص مخزن"])
    service.encode_query("سؤال الزائر")
    assert bodies[0]["input"] == ["نص مخزن"]
    assert bodies[1]["input"] == [embeddings.QWEN3_QUERY_INSTRUCTION + "سؤال الزائر"]

