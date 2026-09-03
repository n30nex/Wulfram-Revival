"""Best-effort directory lease client; outages never stop a running match."""

from __future__ import annotations

import json
import os
import random
import threading
import urllib.error
import urllib.request
from typing import Any

from wulfram_server.directory_metadata import build_server_metadata


class DirectoryClient:
    def __init__(self, server: Any):
        self.server = server
        self.config = server.cfg.directory
        if self.config is None:
            raise ValueError("directory client requires directory configuration")
        self.credential = os.environ[self.config.credential_environment]
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _request(self, path: str, document: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.config.url + path,
            data=payload,
            headers={"Authorization": "Bearer " + self.credential, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10.0) as response:
            return json.loads(response.read())

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="wulfram-directory-heartbeat")
        self.thread.start()

    def _run(self) -> None:
        registered = False
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                document = {
                    "schema_version": 1,
                    "server_id": self.config.server_id,
                    "instance_id": self.server.instance_id,
                    "metadata": build_server_metadata(self.server),
                }
                path = "/v1/instances/heartbeat" if registered else "/v1/instances/register"
                self._request(path, document)
                registered = True
                backoff = 1.0
                self.stop_event.wait(self.config.heartbeat_seconds)
            except urllib.error.HTTPError as error:
                if error.code == 409:
                    registered = False
                print(f"[directory] heartbeat rejected: HTTP {error.code}")
                delay = min(60.0, backoff) * random.uniform(0.8, 1.2)
                self.stop_event.wait(delay)
                backoff = min(60.0, backoff * 2.0)
            except (OSError, ValueError, urllib.error.URLError) as error:
                print(f"[directory] heartbeat unavailable: {error}")
                delay = min(60.0, backoff) * random.uniform(0.8, 1.2)
                self.stop_event.wait(delay)
                backoff = min(60.0, backoff * 2.0)

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        try:
            self._request(
                "/v1/instances/release",
                {"schema_version": 1, "server_id": self.config.server_id, "instance_id": self.server.instance_id},
            )
        except (OSError, ValueError, urllib.error.URLError):
            pass
