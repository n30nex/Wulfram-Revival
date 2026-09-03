from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sys


SERVER_ROOT = Path(__file__).resolve().parent
RELEASE_ROOT = SERVER_ROOT.parent
PACKAGED_BINARY_ROOT = RELEASE_ROOT / "bin"
if PACKAGED_BINARY_ROOT.is_dir():
    sys.path.insert(0, str(PACKAGED_BINARY_ROOT))

from wulfram_server.application import WulframServerContext
from wulfram_server.core.config import Config, ConfigurationError
from wulfram_server.core.native_physics import NativePhysicsUnavailable
from wulfram_server.hooks import ProductionHooks
from wulfram_server.network.packets.packet_config import PacketConfig
from wulfram_server.release import (
    ReleaseIdentity,
    ReleaseValidationError,
    load_release_identity,
)


DEFAULT_CONTENT_ROOT = SERVER_ROOT / "wulfram_server" / "content"


def build_server(
    config_path: Path,
    *,
    content_root: Path = DEFAULT_CONTENT_ROOT,
    release_identity: ReleaseIdentity | None = None,
) -> WulframServerContext:
    content_root = content_root.resolve()
    config = Config.load_strict(
        config_path,
        gameplay_filename=content_root / "gameplay.toml",
    )
    packet_config = PacketConfig.load(
        str(content_root / "packets.toml"),
        strict=True,
    )
    hooks = ProductionHooks(config)
    return WulframServerContext(
        config,
        packet_config,
        content_root=content_root,
        hooks=hooks,
        release_identity=release_identity or load_release_identity(RELEASE_ROOT),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="authoritative Wulfram server")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--content-root",
        type=Path,
        default=DEFAULT_CONTENT_ROOT,
        help="content directory containing gameplay.toml, packets.toml, maps, and collision assets",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration and content without opening sockets",
    )
    args = parser.parse_args(argv)

    try:
        release_identity = load_release_identity(RELEASE_ROOT)
        content_root = args.content_root.resolve()
        if args.check_config:
            config = Config.load_strict(
                args.config,
                gameplay_filename=content_root / "gameplay.toml",
            )
            PacketConfig.load(str(content_root / "packets.toml"), strict=True)
            ProductionHooks(config)
            print(
                "WULFRAM_PRODUCTION_POLICY_VALID "
                f"environment={config.runtime.environment} "
                f"name={config.game.display_name!r} map={config.game.map_name} "
                f"release={release_identity.version} "
                f"content={release_identity.content_identity}"
            )
            return 0

        server = build_server(
            args.config,
            content_root=content_root,
            release_identity=release_identity,
        )
        print(
            "WULFRAM_PRODUCTION_POLICY_VALID "
            f"environment={server.cfg.runtime.environment} "
            f"name={server.cfg.game.display_name!r} map={server.cfg.game.map_name}"
        )
        # Translate supervisor-friendly stop signals into the same
        # KeyboardInterrupt path used by CTRL+C so sockets and physics state
        # close cleanly on both Windows and Linux.
        previous_handlers: dict[signal.Signals, signal.Handlers] = {}
        for signal_name in ("SIGBREAK", "SIGTERM"):
            stop_signal = getattr(signal, signal_name, None)
            if stop_signal is not None:
                previous_handlers[stop_signal] = signal.signal(
                    stop_signal,
                    signal.default_int_handler,
                )
        try:
            server.run()
        finally:
            for stop_signal, previous_handler in previous_handlers.items():
                signal.signal(stop_signal, previous_handler)
        return 0
    except (
        ConfigurationError,
        FileNotFoundError,
        NativePhysicsUnavailable,
        OSError,
        ReleaseValidationError,
        ValueError,
    ) as error:
        print(f"server startup rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
