from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import time
import tomllib
from typing import Any


_SERVER_START = time.monotonic()
SUPPORTED_ENVIRONMENTS = frozenset({"staging", "production"})
MAP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ConfigurationError(ValueError):
    """Raised before startup when a production configuration is unsafe."""


def get_ticks() -> int:
    return int((time.monotonic() - _SERVER_START) * 1000) & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    host: str = "127.0.0.1"
    server_ip: str = "auto"
    tcp_port: int = 2627
    udp_port: int = 2627


@dataclass(frozen=True, slots=True)
class GameConfig:
    display_name: str = "Wulfram Server"
    motd: str = "Welcome to Wulfram!"
    map_name: str = "crossroads"
    map_rotation: tuple[str, ...] = ("crossroads", "mayhem", "meltdown")
    player_limit: int = 20


@dataclass(frozen=True, slots=True)
class PlayerConfig:
    nametag: str = "SERVER"


@dataclass(frozen=True, slots=True)
class DebugConfig:
    debug_packets: bool = False
    show_ascii: bool = False
    debug_actions: bool = False
    debug_action_packets: bool = False


@dataclass(frozen=True, slots=True)
class PhysicsConfig:
    tick_milliseconds: int = 40
    network_hz: float = 30.0
    view_update_hz: float = 5.0
    max_catch_up_steps: int = 5
    metrics_interval_seconds: float = 5.0
    jump_velocity: float = 200.0
    jump_acceleration: float = 20.0
    jump_fuel_cost: float = 6000.0
    fuel_regeneration_per_second: float = 350.0
    resting_fuel_multiplier: float = 1.65


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    environment: str = "staging"
    state_directory: Path = Path(".")
    log_directory: Path = Path(".")
    shutdown_timeout_seconds: float = 15.0


@dataclass(frozen=True, slots=True)
class DirectoryConfig:
    url: str
    server_id: str
    credential_environment: str
    heartbeat_seconds: float = 30.0


DEFAULT_ADMIN_PASSWORD_ENVIRONMENT = "WULFRAM_SERVER_ADMIN_PASSWORD"


@dataclass(frozen=True, slots=True)
class AuthenticationConfig:
    password_environment: str = "WULFRAM_SERVER_PASSWORD"
    admin_password_environment: str = DEFAULT_ADMIN_PASSWORD_ENVIRONMENT


@dataclass(frozen=True, slots=True)
class Config:
    network: NetworkConfig = field(default_factory=NetworkConfig)
    game: GameConfig = field(default_factory=GameConfig)
    player: PlayerConfig = field(default_factory=PlayerConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    authentication: AuthenticationConfig = field(default_factory=AuthenticationConfig)
    directory: DirectoryConfig | None = None

    @classmethod
    def load_strict(
        cls,
        filename: str | Path,
        *,
        gameplay_filename: str | Path,
        environment: Mapping[str, str] | None = None,
    ) -> Config:
        values = os.environ if environment is None else environment
        test_variables = sorted(name for name in values if name.startswith("RE_TEST_"))
        if test_variables:
            raise ConfigurationError(
                "staging/production startup rejects RE_TEST_* variables: "
                + ", ".join(test_variables)
            )

        config_path = Path(filename).resolve()
        document = _read_required_toml(config_path, "server configuration")
        _require_required_and_allowed_keys(
            document,
            required={"server", "network", "authentication", "logging"},
            allowed={"server", "network", "authentication", "logging", "directory"},
            label="configuration root",
        )

        server = _table(document, "server")
        _require_required_and_allowed_keys(
            server,
            required={
                "environment",
                "display_name",
                "motd",
                "map_name",
                "player_nametag",
                "player_limit",
                "state_directory",
                "log_directory",
                "shutdown_timeout_seconds",
            },
            allowed={
                "environment",
                "display_name",
                "motd",
                "map_name",
                "map_rotation",
                "player_nametag",
                "player_limit",
                "state_directory",
                "log_directory",
                "shutdown_timeout_seconds",
            },
            label="[server]",
        )
        network = _table(document, "network")
        _require_exact_keys(
            network,
            {"host", "server_ip", "tcp_port", "udp_port"},
            "[network]",
        )
        authentication = _table(document, "authentication")
        _require_required_and_allowed_keys(
            authentication,
            required={"password_environment"},
            allowed={"password_environment", "admin_password_environment"},
            label="[authentication]",
        )
        logging = _table(document, "logging")
        _require_exact_keys(
            logging,
            {"debug_packets", "show_ascii", "debug_actions", "debug_action_packets"},
            "[logging]",
        )
        directory_config: DirectoryConfig | None = None
        if "directory" in document:
            directory = _table(document, "directory")
            _require_required_and_allowed_keys(
                directory,
                required={"url", "server_id", "credential_environment"},
                allowed={
                    "url", "server_id", "credential_environment", "heartbeat_seconds"
                },
                label="[directory]",
            )
            directory_url = _string(directory, "url", "[directory]").rstrip("/")
            if not directory_url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
                raise ConfigurationError(
                    "directory.url must use HTTPS (HTTP is allowed only for loopback testing)"
                )
            directory_credential_environment = _string(
                directory, "credential_environment", "[directory]"
            )
            if not values.get(directory_credential_environment, ""):
                raise ConfigurationError(
                    "required directory credential is absent: "
                    + directory_credential_environment
                )
            directory_config = DirectoryConfig(
                url=directory_url,
                server_id=_string(directory, "server_id", "[directory]"),
                credential_environment=directory_credential_environment,
                heartbeat_seconds=(
                    _number(
                        directory,
                        "heartbeat_seconds",
                        "[directory]",
                        minimum=5.0,
                    )
                    if "heartbeat_seconds" in directory
                    else 30.0
                ),
            )

        environment_name = _string(server, "environment", "[server]").lower()
        if environment_name not in SUPPORTED_ENVIRONMENTS:
            raise ConfigurationError(
                "server.environment must be 'staging' or 'production'"
            )

        display_name = _string(server, "display_name", "[server]")
        lowered_display_name = display_name.casefold()
        if environment_name == "production" and any(
            marker in lowered_display_name for marker in ("test", "staging")
        ):
            raise ConfigurationError(
                "production display_name must not identify itself as test or staging"
            )
        if environment_name == "staging" and not any(
            marker in lowered_display_name for marker in ("test", "staging")
        ):
            raise ConfigurationError(
                "staging display_name must visibly contain 'staging' or 'test'"
            )

        state_directory = _absolute_directory_value(
            server, "state_directory", "[server]", environment_name
        )
        log_directory = _absolute_directory_value(
            server, "log_directory", "[server]", environment_name
        )
        if state_directory == log_directory:
            raise ConfigurationError(
                "server.state_directory and server.log_directory must be different"
            )

        password_environment = _string(
            authentication, "password_environment", "[authentication]"
        )
        admin_password_environment = (
            _string(authentication, "admin_password_environment", "[authentication]")
            if "admin_password_environment" in authentication
            else DEFAULT_ADMIN_PASSWORD_ENVIRONMENT
        )
        for key, secret_name in (
            ("password_environment", password_environment),
            ("admin_password_environment", admin_password_environment),
        ):
            if secret_name.startswith("RE_TEST_"):
                raise ConfigurationError(
                    f"authentication.{key} must not use RE_TEST_*"
                )
            if not values.get(secret_name, ""):
                raise ConfigurationError(
                    f"required authentication secret is absent: {secret_name}"
                )
        if password_environment == admin_password_environment:
            raise ConfigurationError(
                "player and admin password environment names must be different"
            )
        if values[password_environment] == values[admin_password_environment]:
            raise ConfigurationError(
                "player and admin passwords must be different"
            )

        gameplay_path = Path(gameplay_filename).resolve()
        physics = load_gameplay_config(gameplay_path)
        map_name = _string(server, "map_name", "[server]")
        map_rotation = (
            _string_list(server, "map_rotation", "[server]")
            if "map_rotation" in server
            else (map_name,)
        )
        content_root = gameplay_path.parent
        map_root = content_root / "shared" / "data" / "maps" / map_name
        for filename_part in ("land", "state"):
            required_path = map_root / filename_part
            if not required_path.is_file():
                raise ConfigurationError(
                    f"configured map is missing {filename_part}: {required_path}"
                )
        for rotation_map in map_rotation:
            if MAP_NAME_PATTERN.fullmatch(rotation_map) is None:
                raise ConfigurationError(
                    "server.map_rotation contains an invalid map name: "
                    f"{rotation_map!r}"
                )
            required_land = (
                content_root / "shared" / "data" / "maps" / rotation_map / "land"
            )
            if not required_land.is_file():
                raise ConfigurationError(
                    f"rotation map is missing land: {required_land}"
                )

        tcp_port = _integer(network, "tcp_port", "[network]", minimum=1, maximum=65535)
        udp_port = _integer(network, "udp_port", "[network]", minimum=1, maximum=65535)

        return cls(
            network=NetworkConfig(
                host=_string(network, "host", "[network]"),
                server_ip=_string(network, "server_ip", "[network]"),
                tcp_port=tcp_port,
                udp_port=udp_port,
            ),
            game=GameConfig(
                display_name=display_name,
                motd=_string(server, "motd", "[server]"),
                map_name=map_name,
                map_rotation=map_rotation,
                player_limit=_integer(
                    server, "player_limit", "[server]", minimum=1, maximum=64
                ),
            ),
            player=PlayerConfig(
                nametag=_string(server, "player_nametag", "[server]")
            ),
            debug=DebugConfig(
                debug_packets=_boolean(logging, "debug_packets", "[logging]"),
                show_ascii=_boolean(logging, "show_ascii", "[logging]"),
                debug_actions=_boolean(logging, "debug_actions", "[logging]"),
                debug_action_packets=_boolean(
                    logging, "debug_action_packets", "[logging]"
                ),
            ),
            physics=physics,
            runtime=RuntimeConfig(
                environment=environment_name,
                state_directory=state_directory,
                log_directory=log_directory,
                shutdown_timeout_seconds=_number(
                    server,
                    "shutdown_timeout_seconds",
                    "[server]",
                    minimum=0.1,
                ),
            ),
            authentication=AuthenticationConfig(
                password_environment=password_environment,
                admin_password_environment=admin_password_environment,
            ),
            directory=directory_config,
        )


def load_gameplay_config(filename: str | Path) -> PhysicsConfig:
    document = _read_required_toml(Path(filename), "gameplay configuration")
    _require_exact_keys(document, {"physics"}, "gameplay configuration root")
    physics = _table(document, "physics")
    expected = {
        "tick_milliseconds",
        "network_hz",
        "view_update_hz",
        "max_catch_up_steps",
        "metrics_interval_seconds",
        "jump_velocity",
        "jump_acceleration",
        "jump_fuel_cost",
        "fuel_regeneration_per_second",
        "resting_fuel_multiplier",
    }
    _require_exact_keys(physics, expected, "[physics]")
    return PhysicsConfig(
        tick_milliseconds=_integer(
            physics, "tick_milliseconds", "[physics]", minimum=1, maximum=1000
        ),
        network_hz=_number(physics, "network_hz", "[physics]", minimum=0.1),
        view_update_hz=_number(
            physics, "view_update_hz", "[physics]", minimum=0.1
        ),
        max_catch_up_steps=_integer(
            physics, "max_catch_up_steps", "[physics]", minimum=1, maximum=100
        ),
        metrics_interval_seconds=_number(
            physics, "metrics_interval_seconds", "[physics]", minimum=0.1
        ),
        jump_velocity=_number(physics, "jump_velocity", "[physics]", minimum=0.0),
        jump_acceleration=_number(
            physics, "jump_acceleration", "[physics]", minimum=0.0
        ),
        jump_fuel_cost=_number(
            physics, "jump_fuel_cost", "[physics]", minimum=0.0
        ),
        fuel_regeneration_per_second=_number(
            physics,
            "fuel_regeneration_per_second",
            "[physics]",
            minimum=0.0,
        ),
        resting_fuel_multiplier=_number(
            physics, "resting_fuel_multiplier", "[physics]", minimum=0.0
        ),
    )


def _read_required_toml(path: Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"{description} is missing: {path}")
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"{description} is unreadable: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigurationError(f"{description} root must be a table: {path}")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ConfigurationError(f"{label}: {'; '.join(details)}")


def _require_required_and_allowed_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    allowed: set[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise ConfigurationError(f"{label}: {'; '.join(details)}")


def _table(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ConfigurationError(f"[{key}] must be a TOML table")
    return result


def _string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ConfigurationError(f"{label}.{key} must be a non-empty string")
    return result.strip()


def _string_list(
    value: Mapping[str, Any],
    key: str,
    label: str,
) -> tuple[str, ...]:
    result = value.get(key)
    if not isinstance(result, list) or not result:
        raise ConfigurationError(f"{label}.{key} must be a non-empty string list")
    normalized: list[str] = []
    for item in result:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                f"{label}.{key} must contain only non-empty strings"
            )
        name = item.strip()
        if name in normalized:
            raise ConfigurationError(f"{label}.{key} contains duplicate {name!r}")
        normalized.append(name)
    return tuple(normalized)


def _boolean(value: Mapping[str, Any], key: str, label: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise ConfigurationError(f"{label}.{key} must be true or false")
    return result


def _integer(
    value: Mapping[str, Any],
    key: str,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ConfigurationError(f"{label}.{key} must be an integer")
    if not minimum <= result <= maximum:
        raise ConfigurationError(
            f"{label}.{key} must be between {minimum} and {maximum}"
        )
    return result


def _number(
    value: Mapping[str, Any],
    key: str,
    label: str,
    *,
    minimum: float,
) -> float:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ConfigurationError(f"{label}.{key} must be a number")
    converted = float(result)
    if converted < minimum:
        raise ConfigurationError(f"{label}.{key} must be at least {minimum:g}")
    return converted


def _absolute_directory_value(
    value: Mapping[str, Any],
    key: str,
    label: str,
    environment_name: str,
) -> Path:
    raw = _string(value, key, label)
    path = Path(raw)
    if not path.is_absolute():
        raise ConfigurationError(f"{label}.{key} must be an absolute path")
    resolved = path.resolve()
    if environment_name.casefold() not in {
        part.casefold() for part in resolved.parts
    }:
        raise ConfigurationError(
            f"{label}.{key} must include a dedicated '{environment_name}' directory"
        )
    return resolved
