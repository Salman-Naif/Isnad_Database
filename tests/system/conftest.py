"""System-test fixtures: the database service runs as a real uvicorn process on a free port,
with its storage in a temporary folder and OpenRouter replaced by a local stub server."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from tests.system.stub_openrouter import StubOpenRouter

REPO = Path(__file__).resolve().parents[2]
SITE_KEY = "system-test-site-key-0123456789abcdef"
OWNER, OWNER_PASSWORD = "owner", "first-password"
DIMENSIONS = 64
STARTUP_TIMEOUT = 60


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServiceProcess:
    """One running copy of the service; restart() keeps its storage."""

    def __init__(self, storage: Path, openrouter_url: str) -> None:
        self.storage = storage
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = storage / "service.log"
        # The service's settings come only from here (never from the test process or a .env).
        settings_names = {name.upper() for name in Settings.model_fields}
        self.env = {
            **{k: v for k, v in os.environ.items() if k.upper() not in settings_names},
            "PYTHONPATH": str(REPO),
            "PYTHONIOENCODING": "utf-8",
            "CHROMA_DIR": str(storage / "chroma"),
            "SQLITE_PATH": str(storage / "isnad.db"),
            "UPLOADS_DIR": str(storage / "uploads"),
            "SITE_API_KEY": SITE_KEY,
            "OPENROUTER_API_KEY": "sk-or-system-test",
            "OPENROUTER_BASE_URL": openrouter_url,
            "EMBEDDING_MODEL": "stub/embedding",
            "EMBEDDING_DIMENSIONS": str(DIMENSIONS),
            "ADMIN_USERNAME": OWNER,
            "ADMIN_PASSWORD": OWNER_PASSWORD,
            "OCR_CONCURRENCY": "2",
            "LOG_LEVEL": "WARNING",
        }
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        # Run from the storage folder, so the developer's .env is never read.
        self.process = subprocess.Popen(  # noqa: S603 — fixed command, test-only
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=self.storage, env=self.env,
            stdout=self.log.open("ab"), stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"service exited:\n{self.log.read_text(encoding='utf-8', errors='replace')}")
            try:
                if httpx.get(f"{self.url}/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError(f"service did not start:\n{self.log.read_text(encoding='utf-8', errors='replace')}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def restart(self) -> None:
        self.stop()
        self.start()


@pytest.fixture(scope="module")
def openrouter():
    with StubOpenRouter(DIMENSIONS) as stub:
        yield stub


@pytest.fixture(scope="module")
def service(tmp_path_factory, openrouter):
    storage = tmp_path_factory.mktemp("isnad-system")
    proc = ServiceProcess(storage, openrouter.url)
    proc.start()
    yield proc
    proc.stop()


@pytest.fixture
def browser(service):
    """An HTTP client with its own cookie jar, like one browser."""
    with httpx.Client(base_url=service.url, timeout=30) as client:
        yield client


@pytest.fixture
def website(service):
    """The main website's server-side client: the site key, no cookies."""
    with httpx.Client(base_url=f"{service.url}/api/v1", headers={"X-API-Key": SITE_KEY}, timeout=30) as client:
        yield client
