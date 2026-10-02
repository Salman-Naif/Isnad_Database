"""System tests: the Postman collection in docs/postman, run by Newman against the live service.

The collection is what the team uses to check a deployment by hand; running it here keeps
it in step with the API. Needs Node.js (npx); skipped without it.
"""

import json
import shutil
import subprocess
import time

import httpx
import pytest

from tests.system.conftest import OWNER, OWNER_PASSWORD, REPO, SITE_KEY

COLLECTION = REPO / "docs" / "postman" / "Isnad.postman_collection.json"
NPX = shutil.which("npx")
HADITH = "إنما الأعمال بالنيات وإنما لكل امرئ ما نوى"


@pytest.mark.skipif(NPX is None, reason="Node.js (npx) is not installed")
def test_postman_collection_passes_against_the_live_service(service, tmp_path):
    with httpx.Client(base_url=service.url, timeout=30) as owner:
        assert owner.post("/api/auth/login", json={"username": OWNER, "password": OWNER_PASSWORD}).status_code == 200
        # The first-start password must be replaced before the account can upload.
        assert owner.post("/api/auth/change-password", json={
            "current_password": OWNER_PASSWORD, "new_password": "postman-owner-password"}).status_code == 204
        body = json.dumps([{"id": "p1", "text": HADITH, "hukm": "صحيح"}], ensure_ascii=False).encode()
        source = owner.post("/api/sources", files={"file": ("postman.json", body)}).json()
        deadline = time.monotonic() + 30
        while owner.get(f"/api/sources/{source['id']}").json()["status"] == "processing":
            assert time.monotonic() < deadline
            time.sleep(0.3)

    report = tmp_path / "newman.json"
    result = subprocess.run(  # noqa: S603 — fixed command, test-only
        [NPX, "--yes", "newman@6", "run", str(COLLECTION),
         "--env-var", f"base_url={service.url}", "--env-var", f"site_key={SITE_KEY}",
         "--env-var", f"query={HADITH}",
         "--reporters", "json", "--reporter-json-export", str(report)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    run = json.loads(report.read_text(encoding="utf-8"))["run"]
    failures = [f"{f['source']['name']}: {f['error']['message']}" for f in run["failures"]]
    assert result.returncode == 0 and not failures, failures or result.stdout[-2000:]
    assert run["stats"]["assertions"]["total"] >= 10
