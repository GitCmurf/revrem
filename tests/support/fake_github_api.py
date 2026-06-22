"""Minimal stub GitHub REST API for testing post_pr_comment.py (PLAN-005 T4).

An ``http.server``-based stub that implements just the two endpoints
``post_pr_comment`` touches: ``GET /repos/.../issues/<n>/comments`` (to find an
existing marked comment) and ``POST/PATCH`` on comments (to create/update).
Records every request so tests assert ordering and payload without network.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class FakeGitHubServer:
    """A controllable GitHub API stub running on a background thread."""

    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self._next_id = 1000
        self.requests: list[dict[str, Any]] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""
        #: Page size used when serving the comments listing endpoint. Set <total
        #: to exercise the client's Link-header pagination. None (default) means
        #: "serve all comments in one response" (the original behaviour).
        self.page_size: int | None = None

    def start(self) -> str:
        handler = self._make_handler()
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        return self.base_url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # noqa: A002 - silence
                pass

            def _record(self, method, path, body):
                server.requests.append(
                    {
                        "method": method,
                        "path": path,
                        "body": body,
                        "headers": {k: v for k, v in self.headers.items()},
                    }
                )

            def do_GET(self):  # noqa: N802 - http.server convention
                self._record("GET", self.path, None)
                # /repos/{repo}/issues/{pr}/comments[?per_page=...&page=...]
                path_only = self.path.split("?", 1)[0]
                parts = [p for p in path_only.split("/") if p]
                # ["repos", owner, repo, "issues", pr, "comments"]
                if parts and parts[-1] == "comments":
                    all_comments = list(server.comments.values())
                    query = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                    per_page = int(query.get("per_page", ["100"])[0]) if query.get("per_page") else 100
                    page = int(query.get("page", ["1"])[0]) if query.get("page") else 1
                    page_size = server.page_size if server.page_size is not None else max(1, len(all_comments))
                    total_pages = max(1, (len(all_comments) + page_size - 1) // page_size)
                    start = (page - 1) * page_size
                    page_comments = all_comments[start : start + page_size]
                    body = json.dumps(page_comments).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    if page < total_pages and server.page_size is not None:
                        host = self.headers.get("Host", "127.0.0.1")
                        base = f"http://{host}{path_only}"
                        link = (
                            f'<{base}?per_page={per_page}&page={page + 1}>; rel="next", '
                            f'<{base}?per_page={per_page}&page={total_pages}>; rel="last"'
                        )
                        self.send_header("Link", link)
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw)
                self._record("POST", self.path, payload)
                comment_id = server._next_id
                server._next_id += 1
                comment = {"id": comment_id, "body": payload.get("body", "")}
                server.comments[comment_id] = comment
                body = json.dumps(comment).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PATCH(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw)
                self._record("PATCH", self.path, payload)
                parts = [p for p in self.path.split("/") if p]
                comment_id = int(parts[-1])
                if comment_id in server.comments:
                    server.comments[comment_id]["body"] = payload.get("body", "")
                    body = json.dumps(server.comments[comment_id]).encode()
                    self.send_response(200)
                else:
                    body = b'{"error": "not found"}'
                    self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
