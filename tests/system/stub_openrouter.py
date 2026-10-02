"""A local stand-in for the OpenRouter API, served over real HTTP for the system tests.

  POST /embeddings        deterministic bag-of-characters vectors (EMBEDDING_DIMENSIONS long)
  POST /chat/completions  an image in the message → a fixed transcription (OCR);
                          otherwise → a fixed chat answer
  GET  /key               a valid key with some usage

Every request is recorded, so tests can check what the service sent.
"""

import hashlib
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OCR_TEXT = "حدثنا قتيبة بن سعيد قال حدثنا الليث عن نافع عن ابن عمر أن رسول الله ﷺ قال الدين النصيحة"
CHAT_ANSWER = "هذا الحديث في المصادر المعتمدة وحكمه صحيح."


def embed(text: str, dimensions: int) -> list[float]:
    vec = [0.0] * dimensions
    for ch in text:
        vec[int(hashlib.md5(ch.encode(), usedforsecurity=False).hexdigest(), 16) % dimensions] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class StubOpenRouter:
    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions
        self.requests: list[tuple[str, dict]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output clean
                pass

            def _reply(self, status: int, body: dict) -> None:
                data = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                stub.requests.append((self.path, {}))
                if self.path.endswith("/key"):
                    self._reply(200, {"data": {"usage": 0.25, "limit": 10, "limit_remaining": 9.75}})
                else:
                    self._reply(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                stub.requests.append((self.path, body))
                if self.headers.get("Authorization", "") != "Bearer sk-or-system-test":
                    self._reply(401, {"error": "bad key"})
                elif self.path.endswith("/embeddings"):
                    size = body.get("dimensions", stub.dimensions)
                    self._reply(200, {"data": [
                        {"index": i, "embedding": embed(t, size)} for i, t in enumerate(body["input"])
                    ]})
                elif self.path.endswith("/chat/completions"):
                    content = body["messages"][-1]["content"]
                    has_image = isinstance(content, list) and any(p.get("type") == "image_url" for p in content)
                    self._reply(200, {
                        "choices": [{"message": {"content": OCR_TEXT if has_image else CHAT_ANSWER},
                                     "finish_reason": "stop"}],
                        "usage": {"cost": 0.001},
                    })
                else:
                    self._reply(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "StubOpenRouter":
        self.thread.start()
        return self

    def __exit__(self, *_) -> None:
        self.server.shutdown()
        self.server.server_close()

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]
