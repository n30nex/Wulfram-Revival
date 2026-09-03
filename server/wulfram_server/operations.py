"""Small file-based operational contract for a supervised product server."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


RUNTIME_STATUS_SCHEMA_VERSION = 1
RUNTIME_STATUS_FILENAME = "runtime.json"
SHUTDOWN_REQUEST_FILENAME = "shutdown.request"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_runtime_status(server: Any, status: str, **details: Any) -> None:
    """Publish bounded, secret-free process identity for an operator or deployer."""

    state_directory = server.cfg.runtime.state_directory
    state_directory.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
        "status": status,
        "environment": server.cfg.runtime.environment,
        "process_id": os.getpid(),
        "release_version": server.release_identity.version,
        "git_commit": server.release_identity.git_commit,
        "content_identity": server.release_identity.content_identity,
        "physics_version": server.release_identity.physics_version,
        "tcp_port": server.cfg.network.tcp_port,
        "udp_port": server.cfg.network.udp_port,
        "updated_utc": _utc_now(),
    }
    document.update(details)
    _atomic_json(state_directory / RUNTIME_STATUS_FILENAME, document)


def prepare_operational_directories(server: Any) -> None:
    state_directory = server.cfg.runtime.state_directory
    log_directory = server.cfg.runtime.log_directory
    state_directory.mkdir(parents=True, exist_ok=True)
    log_directory.mkdir(parents=True, exist_ok=True)
    request = state_directory / SHUTDOWN_REQUEST_FILENAME
    try:
        request.unlink()
    except FileNotFoundError:
        pass
    write_runtime_status(server, "starting")


def consume_shutdown_request(server: Any) -> bool:
    request = server.cfg.runtime.state_directory / SHUTDOWN_REQUEST_FILENAME
    try:
        request.unlink()
    except FileNotFoundError:
        return False
    print(
        "WULFRAM_SERVER_STOP_REQUEST "
        f"environment={server.cfg.runtime.environment} source=state-directory"
    )
    return True
