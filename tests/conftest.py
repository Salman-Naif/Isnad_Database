"""Shared test setup."""

import atexit
import hashlib
import math
import os
import shutil
import tempfile
import uuid
from pathlib import Path

# Must be set before the app (and its cached settings) is imported:
# environment variables take precedence over the developer's .env file.
SITE_API_KEY = "test-site-key-0123456789abcdef"
TEST_CHROMA_DIR = tempfile.mkdtemp(prefix="isnad-test-chroma-")
# Removed when the run ends. On Windows ChromaDB holds some files open until the process
# exits, so each run also clears what earlier runs could not.
atexit.register(shutil.rmtree, TEST_CHROMA_DIR, ignore_errors=True)
for _stale in Path(tempfile.gettempdir()).glob("isnad-test-chroma-*"):
    if str(_stale) != TEST_CHROMA_DIR:
        shutil.rmtree(_stale, ignore_errors=True)
os.environ["CHROMA_DIR"] = TEST_CHROMA_DIR
os.environ["SITE_API_KEY"] = SITE_API_KEY
os.environ["EMBEDDING_DIMENSIONS"] = "64"  # FakeEmbedder's vector size
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["ADMIN_USERNAME"] = ""
os.environ["ADMIN_PASSWORD"] = ""

# Tests never read the developer's .env: only the values above and the code's defaults apply.
from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import get_embedder, get_vector_store  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth, sources  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402

get_settings.cache_clear()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct-horse-battery"


class FakeEmbedder:
    """Deterministic bag-of-characters vectors — no model download needed."""

    DIM = 64

    def encode(self, texts: list[str], progress=None) -> list[list[float]]:
        vectors = [self.encode_one(t) for t in texts]
        if progress:
            progress(len(vectors), len(texts))
        return vectors

    def encode_query(self, text: str) -> list[float]:
        return self.encode_one(text)

    def encode_title_query(self, text: str) -> list[float]:
        return self.encode_one(text)

    def encode_one(self, text: str) -> list[float]:
        vec = [0.0] * self.DIM
        for ch in text:
            vec[int(hashlib.md5(ch.encode(), usedforsecurity=False).hexdigest(), 16) % self.DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InlineExecutor:
    """Runs background indexing jobs immediately, so tests see the finished result."""

    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Each test gets its own SQLite file, uploads folder and rate-limit counters."""
    monkeypatch.setattr(get_settings(), "sqlite_path", str(tmp_path / "isnad.db"))
    monkeypatch.setattr(get_settings(), "uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(sources, "_executor", InlineExecutor())
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def store() -> VectorStore:
    """A fresh, empty collection for each test."""
    vs = VectorStore()
    vs.settings = get_settings().model_copy(update={"collection_name": f"t_{uuid.uuid4().hex}"})
    return vs


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def client(store, embedder):
    """An anonymous caller (not logged in). The context manager runs the app's startup."""
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_embedder] = lambda: embedder
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin(client) -> auth.Admin:
    return auth.create_admin(ADMIN_USERNAME, ADMIN_PASSWORD)


@pytest.fixture
def admin_client(client, admin):
    """The same client, logged in as an admin (session cookie set)."""
    res = client.post(
        "/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
    )
    assert res.status_code == 200, res.text
    return client


@pytest.fixture
def site_headers() -> dict[str, str]:
    """Headers the main website sends."""
    return {"X-API-Key": SITE_API_KEY}


LEVELS = ("unit", "integration", "api", "security", "system")


def pytest_collection_modifyitems(items):
    """Mark every test with its level, taken from its folder (tests/<level>/test_*.py),
    so one level can be run on its own: pytest -m unit."""
    for item in items:
        level = Path(str(item.fspath)).parent.name
        if level in LEVELS:
            item.add_marker(getattr(pytest.mark, level))
