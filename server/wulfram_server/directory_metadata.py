"""Bounded v1 directory metadata shared by the server and directory service."""

from __future__ import annotations

import json
import re
from typing import Any

from wulfram_server import PROTOCOL_VERSION


SCHEMA_VERSION = 1
MAX_METADATA_BYTES = 16 * 1024
HASH_PATTERN = re.compile(r"^(?:sha256:[0-9a-f]{64}|source-checkout)$")
CLIENT_FAMILIES = frozenset({"patched-original", "unity"})


class MetadataError(ValueError):
    pass


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MetadataError(f"{label} must be a non-empty string of at most {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise MetadataError(f"{label} contains control characters")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise MetadataError(f"{label} must be between {minimum} and {maximum}")
    return value


def _hash(value: Any, label: str) -> str:
    text = _text(value, label, 96)
    if HASH_PATTERN.fullmatch(text) is None:
        raise MetadataError(f"{label} must be source-checkout or a sha256 identity")
    return text


def _exact(document: dict[str, Any], keys: set[str], label: str) -> None:
    unknown = sorted(set(document) - keys)
    missing = sorted(keys - set(document))
    if unknown or missing:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise MetadataError(f"{label}: {'; '.join(details)}")


def validate_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MetadataError("metadata must be an object")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise MetadataError(f"metadata exceeds {MAX_METADATA_BYTES} bytes")
    _exact(
        value,
        {"schema_version", "release", "status", "game_mode", "mods", "client_support", "routes", "host_mode"},
        "metadata",
    )
    if value["schema_version"] != SCHEMA_VERSION:
        raise MetadataError("unsupported metadata schema_version")

    release = value["release"]
    if not isinstance(release, dict):
        raise MetadataError("release must be an object")
    _exact(release, {"server_version", "protocol_version", "physics_version", "content_identity"}, "release")
    _text(release["server_version"], "release.server_version", 64)
    _integer(release["protocol_version"], "release.protocol_version", 0, 0x7FFFFFFF)
    _text(release["physics_version"], "release.physics_version", 64)
    _hash(release["content_identity"], "release.content_identity")

    status = value["status"]
    if not isinstance(status, dict):
        raise MetadataError("status must be an object")
    _exact(status, {"name", "motd", "joinable", "passworded", "uptime_seconds", "players", "bots", "spectators", "player_limit", "map_id", "map_content_hash", "match_phase"}, "status")
    _text(status["name"], "status.name", 80)
    _text(status["motd"], "status.motd", 256)
    for key in ("joinable", "passworded"):
        if not isinstance(status[key], bool):
            raise MetadataError(f"status.{key} must be boolean")
    for key, maximum in (("uptime_seconds", 0x7FFFFFFF), ("players", 64), ("bots", 64), ("spectators", 64), ("player_limit", 64)):
        _integer(status[key], f"status.{key}", 0 if key != "player_limit" else 1, maximum)
    if status["players"] + status["bots"] > status["player_limit"]:
        raise MetadataError("players plus bots exceeds player_limit")
    _text(status["map_id"], "status.map_id", 64)
    _hash(status["map_content_hash"], "status.map_content_hash")
    _text(status["match_phase"], "status.match_phase", 32)

    mode = value["game_mode"]
    if not isinstance(mode, dict):
        raise MetadataError("game_mode must be an object")
    _exact(mode, {"id", "display_name", "version", "settings_hash", "settings_summary"}, "game_mode")
    _text(mode["id"], "game_mode.id", 64)
    _text(mode["display_name"], "game_mode.display_name", 64)
    _text(mode["version"], "game_mode.version", 32)
    _hash(mode["settings_hash"], "game_mode.settings_hash")
    summary = mode["settings_summary"]
    if not isinstance(summary, dict) or len(summary) > 16:
        raise MetadataError("game_mode.settings_summary must contain at most 16 entries")
    for key, item in summary.items():
        _text(key, "game_mode.settings_summary key", 40)
        if not isinstance(item, (str, int, float, bool)) or isinstance(item, str) and len(item) > 80:
            raise MetadataError("game_mode.settings_summary values must be bounded scalars")

    mods = value["mods"]
    if not isinstance(mods, dict):
        raise MetadataError("mods must be an object")
    _exact(mods, {"modded", "manifest_hash", "items"}, "mods")
    if not isinstance(mods["modded"], bool) or not isinstance(mods["items"], list) or len(mods["items"]) > 32:
        raise MetadataError("mods fields are invalid or contain too many items")
    _hash(mods["manifest_hash"], "mods.manifest_hash")
    for index, item in enumerate(mods["items"]):
        if not isinstance(item, dict):
            raise MetadataError(f"mods.items[{index}] must be an object")
        _exact(item, {"id", "version", "content_hash", "required"}, f"mods.items[{index}]")
        _text(item["id"], f"mods.items[{index}].id", 96)
        _text(item["version"], f"mods.items[{index}].version", 32)
        _hash(item["content_hash"], f"mods.items[{index}].content_hash")
        if not isinstance(item["required"], bool):
            raise MetadataError(f"mods.items[{index}].required must be boolean")
    if mods["modded"] != bool(mods["items"]):
        raise MetadataError("mods.modded must agree with mods.items")

    clients = value["client_support"]
    if not isinstance(clients, list) or not clients or len(clients) > 4 or len(set(clients)) != len(clients):
        raise MetadataError("client_support must be a short unique array")
    if any(client not in CLIENT_FAMILIES for client in clients):
        raise MetadataError("client_support contains an unsupported family")
    routes = value["routes"]
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], dict):
        raise MetadataError("v1 requires exactly one legacy-direct route")
    _exact(routes[0], {"kind", "tcp_port", "udp_port"}, "routes[0]")
    if routes[0]["kind"] != "legacy-direct":
        raise MetadataError("v1 supports only legacy-direct routes")
    _integer(routes[0]["tcp_port"], "routes[0].tcp_port", 1, 65535)
    _integer(routes[0]["udp_port"], "routes[0].udp_port", 1, 65535)
    if value["host_mode"] not in ("dedicated", "player-hosted"):
        raise MetadataError("host_mode is invalid")
    return value


def build_server_metadata(server: Any) -> dict[str, Any]:
    players = sum(
        1
        for session in server.sessions
        if session.is_logged_in and not bool(getattr(session, "is_bot", False))
    )
    bots = len(getattr(server.bots, "bots", ()))
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "release": {
            "server_version": server.release_identity.version,
            "protocol_version": PROTOCOL_VERSION,
            "physics_version": server.release_identity.physics_version,
            "content_identity": server.release_identity.content_identity,
        },
        "status": {
            "name": server.cfg.game.display_name,
            "motd": server.cfg.game.motd,
            "joinable": players + bots < server.cfg.game.player_limit,
            "passworded": True,
            "uptime_seconds": int(max(0.0, __import__("time").monotonic() - server.started_monotonic)),
            "players": players,
            "bots": bots,
            "spectators": 0,
            "player_limit": server.cfg.game.player_limit,
            "map_id": server.current_map_name,
            "map_content_hash": server.release_identity.content_identity,
            "match_phase": "playing",
        },
        "game_mode": {
            "id": "wulfram.conquest",
            "display_name": "Conquest",
            "version": "1.0.0",
            "settings_hash": server.release_identity.content_identity,
            "settings_summary": {},
        },
        "mods": {"modded": False, "manifest_hash": "source-checkout", "items": []},
        "client_support": ["patched-original", "unity"],
        "routes": [{"kind": "legacy-direct", "tcp_port": server.cfg.network.tcp_port, "udp_port": server.cfg.network.udp_port}],
        "host_mode": "dedicated",
    }
    return validate_metadata(metadata)
