"""Small file-based operational contract for a supervised product server."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import socket
from pathlib import Path
from typing import Any


RUNTIME_STATUS_SCHEMA_VERSION = 1
RUNTIME_STATUS_FILENAME = "runtime.json"
SHUTDOWN_REQUEST_FILENAME = "shutdown.request"


def notify_supervisor(message: str) -> None:
    """Use systemd's datagram contract without adding a runtime dependency."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
        notification.settimeout(.2)
        notification.sendto(message.encode("ascii"), address)


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


def write_public_match_status(server: Any) -> None:
    from wulfram_server.matches import public_snapshot
    _atomic_json(server.cfg.runtime.state_directory / "public.json", public_snapshot(server))


def write_qualification_status(server: Any) -> None:
    """Overwrite one private, bounded sample; never export player identities."""
    from collections import Counter
    metrics = server.physics.metrics
    sessions = tuple(server.sessions)
    bots = server.bots.bots
    live = [bot for bot in bots if bot.entity is not None and bot.entity.is_manned]
    navigation = server.bots.navigation
    rss = None
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                rss = int(line.split()[1])*1024
                break
    except FileNotFoundError:
        pass  # Linux provides current RSS; other hosts report it as unavailable.
    _atomic_json(server.cfg.runtime.state_directory / 'qualification.json', {
        'schema_version': 1, 'updated_utc': _utc_now(), 'process_id': os.getpid(),
        'git_commit': server.release_identity.git_commit, 'map': server.current_map_name,
        'changing_map': server.map_change_transition is not None,
        'physics_ticks': metrics.ticks, 'dropped_ticks': metrics.dropped_catch_up_ticks,
        'rss_bytes': rss, 'sessions': len(sessions),
        'bots': sum(bool(getattr(session,'is_bot',False)) for session in sessions),
        'live_bots': sum(bot.is_bot for bot in live),
        'entities': len(server.entities.get_all()),
        'route_fields': len(navigation.fields) if navigation else 0,
        'bot_orders': dict(Counter(bot.order for bot in live if bot.is_bot)),
    })


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
