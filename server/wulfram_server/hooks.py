from __future__ import annotations

from collections.abc import Mapping
import hmac
import ipaddress
import os
import time
from typing import Any

from wulfram_server import operations


class NullTrace:
    """Production-safe trace sink; structured test capture is injected by the harness."""

    def packet(self, *args: Any, **kwargs: Any) -> None:
        pass

    def udp_datagram(self, *args: Any, **kwargs: Any) -> None:
        pass

    def state(self, *args: Any, **kwargs: Any) -> None:
        pass

    def close(self) -> None:
        pass


class ServerHooks:
    """Narrow seam through which the local integration harness observes a session."""

    mode_name = "server_simulation"
    authoritative_physics_enabled = True
    ground_docking_enabled = True

    def create_trace(self) -> NullTrace:
        return NullTrace()

    def initialize_server(self, server: Any) -> None:
        pass

    def initialize_session(self, session: Any) -> None:
        pass

    def cleanup_session(self, session: Any) -> None:
        pass

    def start(self, server: Any) -> None:
        pass

    def stop(self, server: Any) -> None:
        pass

    def shutdown_requested(self, server: Any) -> bool:
        return False

    def server_stopped(self, server: Any) -> None:
        pass

    def before_game_loop_iteration(self, server: Any) -> None:
        pass

    def enqueue_client_state(self, server: Any, session: Any, state: Any) -> None:
        raise RuntimeError("this server policy does not accept external client state")

    def owner_mutation_prohibited(
        self,
        server: Any,
        session: Any,
        category: str,
        detail: str,
    ) -> bool:
        return False

    def suppress_owner_view_update(self, server: Any, session: Any, entity: Any) -> bool:
        return False

    def suppress_owner_state_echo(self, server: Any, session: Any, entity: Any) -> bool:
        return False

    def owner_view_update_mask(
        self, server: Any, session: Any, entity: Any, mask: Any
    ) -> Any:
        return mask

    def after_view_broadcast(self, server: Any) -> None:
        pass

    def entity_spawned(self, session: Any, entity: Any, source: str) -> None:
        pass

    def entity_removed(self, session: Any, reason: str) -> None:
        pass

    def world_ready(self, context: Any) -> None:
        pass

    def team_joined(self, context: Any, previous_team: int, requested_team: int) -> None:
        pass

    def tank_resend_requested(self, context: Any, sequence_num: int) -> None:
        pass

    def action_packet(
        self,
        context: Any,
        packet_name: str,
        opcode: int,
        decoded_actions: list[tuple[int, float | None, float]],
    ) -> None:
        pass

    def process_system_command(self, context: Any, message: str) -> bool:
        return False

    def authenticate(self, session: Any) -> bool:
        raise NotImplementedError

    def server_ready(self, server: Any) -> None:
        pass

    def client_connected(self, server: Any, address: tuple[str, int]) -> None:
        pass

    def login_accepted(self, server: Any, session: Any) -> None:
        pass


class ProductionHooks(ServerHooks):
    """The only hook policy constructed by the production entry point."""

    def __init__(self, config: Any, environment: Mapping[str, str] | None = None):
        self._next_public_status_at = 0.0
        values = os.environ if environment is None else environment
        self._player_password = values[config.authentication.password_environment]
        self._admin_password = values[
            config.authentication.admin_password_environment
        ]

    def authenticate(self, session: Any) -> bool:
        supplied = str(getattr(session, "supplied_password", ""))
        supplied_bytes = supplied.encode("utf-8")
        player_match = hmac.compare_digest(
            supplied_bytes,
            self._player_password.encode("utf-8"),
        )
        admin_match = hmac.compare_digest(
            supplied_bytes,
            self._admin_password.encode("utf-8"),
        )
        # The retail transport is not encrypted. Remote players use a public
        # join code; administration is restricted to loopback/private LAN peers.
        peer = ipaddress.ip_address(session.address[0])
        admin_match = admin_match and (peer.is_loopback or any(peer in network for network in (
            ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"))))
        session.is_admin = admin_match
        session.supplied_password = ""
        return player_match or admin_match

    def initialize_server(self, server: Any) -> None:
        from wulfram_server import admin_commands

        admin_commands.initialize(server)

    def before_game_loop_iteration(self, server: Any) -> None:
        from wulfram_server import admin_commands

        admin_commands.apply_pending(server)

    def process_system_command(self, context: Any, message: str) -> bool:
        from wulfram_server import admin_commands

        return admin_commands.process(context, message)

    def login_accepted(self, server: Any, session: Any) -> None:
        if bool(getattr(session, "is_admin", False)):
            print(
                f"[admin] login accepted player={session.player_id} "
                f"name={session.name!r}"
            )

    def start(self, server: Any) -> None:
        operations.prepare_operational_directories(server)
        if server.cfg.game.bots_per_team:
            from wulfram_server import application as app

            if not app.load_map_state(server, server.current_map_name):
                raise ValueError("could not load the initial bot map")
            server.land.load(app.map_land_path(server, server.current_map_name))
            if not server.land.loaded:
                raise ValueError("could not load the initial bot terrain")
            if not all(server.bots.can_spawn(team) for team in (1, 2)):
                raise ValueError("startup bots require a living repair pad for each team")
            server.first_map_load = True
            for _ in range(server.cfg.game.bots_per_team):
                for team in (1, 2):
                    server.bots.add(team=team)
            server.bots.prepare_navigation()

    def server_ready(self, server: Any) -> None:
        operations.write_runtime_status(server, "ready")
        operations.notify_supervisor("READY=1")
        if server.cfg.directory is not None:
            from wulfram_server.directory_client import DirectoryClient

            server.directory_client = DirectoryClient(server)
            server.directory_client.start()

    def after_view_broadcast(self, server: Any) -> None:
        now = time.monotonic()
        if now < self._next_public_status_at:
            return
        self._next_public_status_at = now + 5.0
        try:
            operations.write_public_match_status(server)
            # Only a completed simulation/broadcast iteration refreshes the
            # watchdog. A hung main loop cannot claim the game is healthy.
            operations.notify_supervisor("WATCHDOG=1")
        except OSError as error:
            # A failed exporter must not interrupt the simulation. The public
            # page treats a stale timestamp as unavailable rather than online.
            self._next_public_status_at = now + 60.0
            print(f"[status] public snapshot could not be written: {error}")

    def shutdown_requested(self, server: Any) -> bool:
        return operations.consume_shutdown_request(server)

    def stop(self, server: Any) -> None:
        directory_client = getattr(server, "directory_client", None)
        if directory_client is not None:
            directory_client.stop()
        operations.write_runtime_status(server, "stopping")
        operations.notify_supervisor("STOPPING=1")

    def server_stopped(self, server: Any) -> None:
        operations.write_runtime_status(server, "stopped")
