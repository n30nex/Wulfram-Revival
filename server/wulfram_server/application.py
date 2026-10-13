"""Shared authoritative server application used by production and tests."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import secrets
import select
import socket
import struct
import threading
import time
import traceback
import uuid
from typing import Dict, Tuple, Optional


GROUND_DOCK_JET_OFF_THRESHOLD = 0.0
# ProcessBodySettlingAndSleep waits for roughly twelve ordinary physics
# frames. Use elapsed time here so changing the server tick rate does not turn
# the gameplay latch into a different-duration rule.
GROUND_DOCK_SETTLE_SECONDS = 0.5
# Recovered zero-contact baselines. The collision solver's current
# settling_contact_threshold is added to these below.
GROUND_DOCK_BASE_POSITION_DRIFT = 0.03
GROUND_DOCK_BASE_ORIENTATION_DRIFT = 0.006
GROUND_DOCK_BASE_MOTION = 1.3
GROUND_DOCK_TARGET_ENTITY_ID = 0xFFFFFFFF
# FUN_00449490 dispatches transient type 0x0F to the Tank power-down sound
# (catalogue entry 0x45 for the ordinary Tank). This case dereferences the
# referenced object, so it must use entity mode rather than an explicit point.
TANK_POWERDOWN_TRANSIENT_TYPE = 0x0F
PLAYER_VEHICLE_UNIT_TYPES = frozenset({0, 1})  # Tank, Scout
CARGO_UNIT_TYPE = 19
CARGO_LOCKED_ITEM_ID = 13
CARGO_ITEM_ID_MIN = 0
CARGO_ITEM_ID_MAX = 11
CARGO_DEPLOY_UNIT_TYPE_BASE = 25
CARGO_DROP_OFFSET = 12.0
# Retain enough accepted wire sequence IDs to reject ordinary UDP retries
# without confusing a later 16-bit sequence wrap for a duplicate.
RELIABLE_REPLAY_HISTORY = 256
SPAWN_DELIVERY_RETRY_SECONDS = 0.5
SPAWN_DELIVERY_TIMEOUT_SECONDS = 8.0

from wulfram_server.network.transport.tcp_transport import TcpTransport
from wulfram_server.network.transport.udp_transport import UdpTransport
from wulfram_server.network.transport.envelope import UdpEnvelope
from wulfram_server.network.limits import RateLimit

from wulfram_server.network.dispatcher import PacketDispatcher
from wulfram_server.network.streams import PacketDecodeError, PacketWriter, PacketReader

from wulfram_server.core.config import Config, get_ticks
from wulfram_server.hooks import ServerHooks
from wulfram_server.network.packets.packet_config import PacketConfig
from wulfram_server.network.packets import (
    Packet, MotdPacket, IdentifiedUdpPacket, LoginStatusPacket, PlayerInfoPacket,
    BpsReplyPacket, PingRequestPacket, AddToRosterPacket, RemoveFromRosterPacket,
    WorldStatsPacket, DeleteObjectPacket,
    DeathNoticePacket, BirthNoticePacket, DockingPacket, CarryingInfoPacket,
    EntityTransient, ExplosionTransient, PositionalTransient, TransientArrayPacket,
    GameClockPacket, HelloPacket, TeamInfoPacket, ReincarnatePacket,
    TankPacket, BehaviorPacket, TranslationPacket,
    CommMessagePacket,
)
from wulfram_server.network.packets.packet_logger import PacketLogger

from wulfram_server.core.entity import (
    GameEntity,
    SPAWN_PROTECTION_SECONDS,
    PendingTransientEvent,
    TEAM_SIDE_BY_ID,
    UpdateMask,
)
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.core.map_loader import MapLoader
from wulfram_server.network.translation_config import get_config_by_index

from wulfram_server.core.land import LandMap
from wulfram_server.core.native_physics import PhysicsWorldHost
from wulfram_server.core.combat import (
    CombatSystem,
    Destruction,
    FLAK_SHELL_UNIT_TYPE,
    PULSE_UNIT_TYPE,
)
from wulfram_server.release import ReleaseIdentity
from wulfram_server.directory_query import try_tcp_query, try_udp_query

# -------------------------------------------------------------------------
# CONTEXTS
# -------------------------------------------------------------------------

@dataclass
class PendingSpawnDelivery:
    entity: GameEntity
    input_sequence: int
    team: int
    deadline: float
    retry_at: float


class ClientSession:
    """
    Encapsulates the state for a single connected player.
    Replaces the global 'player' and 'my_entity' from the server context.
    """
    def __init__(self, server: WulframServerContext, tcp_sock: socket.socket, addr: Tuple[str, int]):
        self.server = server
        self.tcp_sock = tcp_sock
        self.address = addr  # (IP, Port) from TCP connection
        
        # Identity
        self.player_id: int = 0
        self.name: str = "Unknown"
        self.vehicle_loadout: str = "auto"
        from wulfram_server.matches import PlayerScore
        self.score = PlayerScore()
        self.team: int = 0

        # --- SESSION KEY LOGIC ---
        # Generate a random 10-char key (Wulfram seems to like strings)
        self.session_key = "Key" + secrets.token_hex(12)
        
        # Placeholder: We don't know the real algo yet, so we will 
        # temporarily TRUST the client's TCP echo to link this.
        self.expected_udp_id = 0
        
        # Game Object associated with this client
        self.entity: Optional[GameEntity] = None
        
        # Connection State
        self.is_logged_in: bool = False
        self.is_admin: bool = False
        self.login_subcommand: int = 0
        self.supplied_password: str = ""
        self.last_received_at = time.monotonic()
        self.udp_rate = RateLimit(240, 1.0, keys=1)
        self.tcp_rate = RateLimit(60, 1.0, keys=1)
        self.request_rate = RateLimit(5, 1.0, keys=16)
        self.tcp_transport = None
        self._cleaned_up = False

        # Server-owned, per-client physics input sequence. It intentionally
        # survives Tank death and reincarnation within this connection.
        self.physics_input_sequence: int = 0
        self.construction_ready_at: float = 0.0
        self.spawn_request_until: float = 0.0
        self.spawn_delivery: PendingSpawnDelivery | None = None
        # A lethal hit first leaves the zero-health vehicle visible for the
        # stock client's death fade. DELETE_OBJECT is sent only when this
        # deadline expires; construction uses the same recovered timeout.
        self.death_cleanup_at: float = 0.0
        self.death_delete_explosion: bool = False
        self.carried_cargo_item_id: int | None = None
        self.carried_cargo_team_id: int = 0

        # Gate flag for the global loop
        self.is_ready_for_updates: bool = False
        self.world_announced: bool = False
        # Keep a complete old-world snapshot ahead of a replacement map's
        # announcement on this connection's reliable control channel.
        self.world_lock = threading.RLock()
        self.world_change_event = threading.Event()
        
        # UDP Linkage
        self.udp_addr: Optional[Tuple[str, int]] = None
        self.udp_context: Optional[UdpContext] = None

        # Zero jets arm a body-settling transition. Requiring a later nonzero
        # jet sample after undocking prevents the same held input from
        # immediately docking the Tank again.
        self.ground_dock_armed: bool = True
        self.ground_dock_settle_started_at: float | None = None
        self.ground_dock_reference_pos: tuple[float, float, float] | None = None
        self.ground_dock_reference_rot: tuple[float, float, float] | None = None
        self.ground_dock_last_physics_tick: int = 0
        
        # Synchronization Events (Specific to this client now)
        self.stop_ping_event = threading.Event()
        # Wait for client to echo our key back
        self.key_echoed_event = threading.Event()
        self.login_received = threading.Event()
        # Cross-transport bootstrap barrier. The TCP bootstrap must not race
        # ahead of the UDP D_HANDSHAKE exchange.
        self.d_handshake_sent_event = threading.Event()
        self.d_handshake_ack_event = threading.Event()
        self.udp_handshake_replies: tuple[bytes, ...] = ()
        self.server.hooks.initialize_session(self)

    def cleanup(self):
        """Helper to close sockets and events when client disconnects."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self.stop_ping_event.set()
        self.world_change_event.set()
        self.spawn_delivery = None
        was_logged_in = self.is_logged_in
        self.is_logged_in = False
        self.is_ready_for_updates = False
        context = self.udp_context
        if context is not None:
            if self.server.udp_sessions.get(context.addr) is context:
                self.server.udp_sessions.pop(context.addr, None)
        # Remove the peer from lookup immediately, but keep this closed
        # object's references stable for an in-flight broadcast/action. Those
        # workers may already hold this session while serializing a snapshot.
        # stop_ping_event revokes dispatch and send; the cycle is then GC'd.
        if self.carried_cargo_item_id is not None:
            self.carried_cargo_item_id = None
            self.carried_cargo_team_id = 0
            _send_carrying_info(self.server, self, has_cargo=False)
        self.server.hooks.cleanup_session(self)
        try:
            self.tcp_sock.close()
        except OSError:
            pass
        
        if was_logged_in:
            broadcast(self.server, RemoveFromRosterPacket(self.player_id))

        if self.entity:
            self.server.hooks.entity_removed(self, "disconnect")
            del_pkt = self.server.entities.remove_entity(net_id=self.entity.net_id)
            if (del_pkt is not None): broadcast(self.server, del_pkt)
        self.supplied_password = ""
        self.session_key = ""

    def disconnect(self):
        """Wake the owning TCP worker; it performs cleanup exactly once."""
        self.stop_ping_event.set()
        self.world_change_event.set()
        self.spawn_delivery = None
        for event in (self.key_echoed_event, self.login_received, self.d_handshake_ack_event):
            event.set()
        try:
            self.tcp_sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

class WulframServerContext:
    """
    Holds configuration, the logger, shared state, and controls the sockets.
    """
    def __init__(
        self,
        cfg: Config,
        packet_cfg: PacketConfig,
        *,
        content_root: str | Path,
        hooks: ServerHooks,
        release_identity: ReleaseIdentity | None = None,
    ):
        self.cfg = cfg
        self.packet_cfg = packet_cfg
        # Retail Team_IsFull (0x00474eb0) counts every roster member, including
        # bots. Its Behavior limit must match the configured match capacity.
        self.packet_cfg.behavior.header.total_team_size = (cfg.game.player_limit + 1) // 2
        self.content_root = Path(content_root).resolve()
        self.hooks = hooks
        self.release_identity = release_identity or ReleaseIdentity.source_checkout()
        # One UUID identifies this process boot across registration and both
        # transport probes. It is never reused as the persistent server ID.
        self.instance_id = str(uuid.uuid4())
        self.started_monotonic = time.monotonic()
        self.logger = PacketLogger(enabled=cfg.debug.debug_packets)
        self.trace = hooks.create_trace()
        self.entities = EntityManager()
        self.first_map_load = False
        self.current_map_name = self.cfg.game.map_name
        self.land = LandMap()

        self.hooks.initialize_server(self)
        self.physics: PhysicsWorldHost | None = None
        if should_run_server_simulation(self):
            self.physics = PhysicsWorldHost(
                self.entities,
                self.cfg.physics,
                self.packet_cfg,
                collision_root=self.content_root / "collision",
                expected_physics_version=(
                    self.release_identity.physics_version
                    if self.release_identity.packaged
                    else None
                ),
            )
        self.combat: CombatSystem | None = (
            CombatSystem(self) if self.physics is not None else None
        )

        # Session Management
        self.sessions: list[ClientSession] = []
        self._last_hard_sync_log = 0.0

        from wulfram_server.bots import BotManager
        self.bots = BotManager(self)

        # ID Counters
        self._next_player_id = 1
        self._player_id_lock = threading.Lock()
        
        # Shared State
        self.stop_event = threading.Event()
        self.stop_update_event = threading.Event()
        self.ready_event = threading.Event()
        
        # Sockets
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Transports
        self.udp_transport: Optional[UdpTransport] = None
        
        # UDP Session Cache (Addr -> UdpContext)
        self.udp_sessions: Dict[Tuple[str, int], UdpContext] = {}
        self._game_thread: threading.Thread | None = None
        self._udp_thread: threading.Thread | None = None
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._query_rate = RateLimit(10, 1.0)
        self._udp_preauth_rate = RateLimit(30, 1.0)
        self._udp_global_rate = RateLimit(4096, 1.0, keys=1)
        self._connection_rate = RateLimit(32, 10.0)
        self._login_lock = threading.Lock()
        self.fatal_error = None
        self.last_game_loop_at = time.monotonic()

    def allow_packet(self, context, opcode: int) -> bool:
        session = context.session
        if session is None:
            return context.transport_name == "UDP" and opcode in (0x08, 0x13)
        if session.stop_ping_event.is_set():
            return False
        if not session.is_logged_in:
            return opcode in ((0x08, 0x13) if context.transport_name == "UDP" else (0x13, 0x21, 0x4E))
        if opcode == 0x21:  # A second LOGIN cannot rename an authenticated player.
            return False
        if opcode in (0x03, 0x13, 0x36, 0x4E, 0x4F) and not session.request_rate.allow(opcode):
            return False
        if opcode in (0x09, 0x0A, 0x19, 0x20, 0x25, 0x2B, 0x3A) and not session.is_ready_for_updates:
            return False
        return True

    def _run_game_loop(self):
        try:
            global_game_loop(self)
        except Exception as error:
            self.fatal_error = f"game loop failed: {type(error).__name__}: {error}"
            print(f"[server] {self.fatal_error}")
            traceback.print_exc()
        finally:
            self.stop_event.set()
            self.stop_update_event.set()

    def _receive_datagram(self, data, addr):
        if not self._udp_global_rate.allow() or not data or len(data) > 2048:
            return
        query_reply = try_udp_query(data, self.instance_id)
        if query_reply is not None:
            if self.allow_directory_query(addr[0]):
                self.udp_transport.send(query_reply, addr)
            return
        ctx = self.udp_sessions.get(addr)
        if ctx is None:
            if not self._udp_preauth_rate.allow(addr[0]):
                return
            # Unverified addresses are never retained. Only a verified key may
            # install a context, bounded by the accepted TCP player capacity.
            ctx = UdpContext(self.udp_transport, addr, self)
        elif ctx.session is None or not ctx.session.udp_rate.allow():
            return
        stripped = UdpEnvelope.try_strip_length(data)
        packet_payloads = dispatcher.dispatch_datagram(ctx, stripped)
        if ctx.session is not None:
            ctx.session.last_received_at = time.monotonic()
        self.trace.udp_datagram("client_to_server", data, addr=addr,
                                payload_size=len(stripped), logical_packet_count=len(packet_payloads),
                                length_header_stripped=len(stripped) != len(data))
        for packet_payload in packet_payloads:
            self.trace.packet("client_to_server", "UDP", packet_payload, addr=addr)

    def allow_directory_query(self, address: str) -> bool:
        """Bound pre-auth query work per source without creating a game session."""

        return self._query_rate.allow(address)

    def get_next_player_id(self) -> int:
        """Generates a unique Player/Account ID."""
        with self._player_id_lock:
            pid = self._next_player_id
            self._next_player_id += 1
        return pid

    def enqueue_external_client_state(self, session: ClientSession, state: object) -> None:
        self.hooks.enqueue_client_state(self, session, state)

    def run(self):
        """Starts the UDP listener thread and the TCP accept loop."""
        self.hooks.start(self)
        self._game_thread = threading.Thread(
            target=self._run_game_loop,
            daemon=True,
            name="wulfram-game-loop",
        )
        self._game_thread.start()

        # 1. Setup UDP
        self.udp_sock.bind((self.cfg.network.host, self.cfg.network.udp_port))
        self.udp_sock.setblocking(False)
        self.udp_transport = UdpTransport(self.udp_sock)
        actual_udp_port = int(self.udp_sock.getsockname()[1])
        print(f"[UDP] Listening on port {actual_udp_port}")
        
        # Start UDP Thread
        self._udp_thread = threading.Thread(
            target=self._udp_loop,
            daemon=True,
            name="wulfram-udp-loop",
        )
        self._udp_thread.start()

        print(f"[sync] mode={get_sync_mode(self)}")

        # 2. Setup TCP
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((self.cfg.network.host, self.cfg.network.tcp_port))
        self.tcp_sock.listen(5)
        self.tcp_sock.settimeout(1.0)
        actual_tcp_port = int(self.tcp_sock.getsockname()[1])
        print(f"[TCP] Listening on {self.cfg.network.host}:{actual_tcp_port}")
        print(
            "WULFRAM_SERVER_READY "
            f"environment={self.cfg.runtime.environment} "
            f"name={self.cfg.game.display_name!r} "
            f"tcp={actual_tcp_port} udp={actual_udp_port} "
            f"release={self.release_identity.version} "
            f"commit={self.release_identity.git_commit} "
            f"content={self.release_identity.content_identity}"
        )
        self.trace.state(
            "SERVER_READY",
            tcp_port=actual_tcp_port,
            udp_port=actual_udp_port,
        )
        self.ready_event.set()
        self.hooks.server_ready(self)

        # 3. Main Loop (Accepts TCP Clients)
        self._tcp_accept_loop()
        if self.fatal_error is not None:
            raise RuntimeError(self.fatal_error)

    def _udp_loop(self):
        """The dedicated UDP listener loop."""
        transport = self.udp_transport
        if transport is None:
            print("[UDP-ERR] Transport not initialized, stopping UDP loop.")
            return
        
        while not self.stop_event.is_set():
            try:
                if not select.select([self.udp_sock], [], [], 0.5)[0]:
                    continue
                data, addr = self.udp_sock.recvfrom(2049)
                self._receive_datagram(data, addr)
            except (BlockingIOError, PacketDecodeError):
                # Invalid public traffic is discarded without log amplification.
                continue
            except OSError as error:
                if self.stop_event.is_set():
                    break
                print(f"[UDP-ERR] {error}")
            except Exception as error:
                if not self.stop_event.is_set():
                    self.fatal_error = f"UDP worker failed: {type(error).__name__}"
                    self.stop_event.set()
                    print(f"[server] {self.fatal_error}")

    def _tcp_accept_loop(self):
        """The main blocking loop that accepts TCP connections."""
        print("Server running. Press CTRL+C to stop.")
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                if now - self.last_game_loop_at > 30.0 or (self._udp_thread and not self._udp_thread.is_alive()):
                    self.fatal_error = "simulation or UDP worker stopped responding"
                    self.stop_event.set()
                    break
                for session in list(self.sessions):
                    if isinstance(session, ClientSession) and now - session.last_received_at > (60.0 if session.is_logged_in else 150.0):
                        session.disconnect()
                if self.hooks.shutdown_requested(self):
                    self.stop_event.set()
                    break
                try:
                    client_sock, addr = self.tcp_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not self._connection_rate.allow(addr[0]) or sum(
                    isinstance(s, ClientSession) and not s.is_logged_in and s.address[0] == addr[0]
                    for s in self.sessions
                ) >= 4:
                    client_sock.close()
                    continue
                
                print(f"\n[+] Client connected from {addr}")
                self.hooks.client_connected(self, addr)
                self.trace.state("CLIENT_CONNECTED", peer=f"{addr[0]}:{addr[1]}")

                if len(self.sessions) >= self.cfg.game.player_limit:
                    print(f"[-] Player limit reached; rejecting {addr}")
                    client_sock.close()
                    continue
                
                # --- STEP 2 LOGIC PREVIEW ---
                # Create the session
                new_session = ClientSession(self, client_sock, addr)
                self.sessions.append(new_session)

                # Handle in a thread (Non-blocking)
                t = threading.Thread(
                    target=self._handle_tcp_client, 
                    args=(new_session,), 
                    daemon=True
                )
                t.start()
                
        except KeyboardInterrupt:
            print("\n[!] Stopping server...")
            self.stop_event.set()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Request a graceful local shutdown; safe to call more than once."""
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True
            self.stop_event.set()
            self.stop_update_event.set()
            self.hooks.stop(self)
            for session in list(self.sessions):
                if isinstance(session, ClientSession):
                    session.disconnect()
            for sock in (self.tcp_sock, self.udp_sock):
                try:
                    sock.close()
                except OSError:
                    pass
            current = threading.current_thread()
            for worker in (self._game_thread, self._udp_thread):
                if worker is not None and worker is not current and worker.is_alive():
                    worker.join(timeout=self.cfg.runtime.shutdown_timeout_seconds)
            if self.physics is not None:
                self.physics.log_final_metrics()
            self.trace.close()
            self.hooks.server_stopped(self)
            print("WULFRAM_SERVER_STOPPED")

    def _handle_tcp_client(self, session: ClientSession):
        """
        Threaded handler for a single TCP client.
        """
        client_sock = session.tcp_sock
        
        try:
            # A slow directory query occupies only its bounded connection
            # worker, never the listener or the game simulation.
            if try_tcp_query(client_sock, self.instance_id,
                             allow_reply=lambda: self.allow_directory_query(session.address[0])):
                return
            tcp_transport = TcpTransport(client_sock)
            session.tcp_transport = tcp_transport
            ctx = TcpContext(tcp_transport, self, session)
            do_login_and_bootstrap(client_sock, ctx, dispatcher)
            
            # Connection Loop
            while not self.stop_event.is_set() and not session.stop_ping_event.is_set():
                payload = tcp_transport.recv_payload()
                if not payload: break
                if not session.tcp_rate.allow():
                    raise ConnectionError("TCP request rate exceeded")
                session.last_received_at = time.monotonic()
                dispatcher.dispatch_payload(ctx, payload)
                
        except Exception as e:
            print(f"[-] Client {session.address} Disconnected: {e}")
        finally:
            try:
                session.cleanup()
            finally:
                if session in self.sessions:
                    self.sessions.remove(session)

class TcpContext:
    """
    Context for a specific TCP Client connection.
    Reference `server` to access global config/state.
    Reference `session` to access specific player state.
    """
    def __init__(self, transport: TcpTransport, server: WulframServerContext, session: ClientSession):
        self.transport_name = "TCP"
        self.transport = transport
        self.server = server # <--- Access to Config, Logger, etc.
        self.session = session # <--- Added this linkage
        
        # This is now redundant since it's in session, but we can keep it for compatibility 
        # or map it to session.stop_ping_event
        self.stop_ping_event = session.stop_ping_event

    def send(self, packet_data: bytes | Packet):
        """
        Sends data. Can accept raw bytes OR a Packet object
        """
        # Type guarding: explicitly separate bytes from Packets
        if isinstance(packet_data, Packet):
            payload = packet_data.serialize()
        else:
            payload = packet_data

        try:
            self.transport.send_payload(payload)
            self.server.trace.packet(
                "server_to_client",
                self.transport_name,
                payload,
                addr=self.session.address,
            )
            self.server.logger.log_packet(
                "TCP-SEND", 
                payload, 
                show_ascii=self.server.cfg.debug.show_ascii, 
                include_tcp_len_prefix=True
            )
        except OSError as e:
            self.session.disconnect()
            raise ConnectionError("TCP send failed") from e

class UdpContext:
    """Context for a UDP Endpoint (Sessionless or Session-bound)"""
    def __init__(self, transport: UdpTransport, addr: Tuple[str, int], server: WulframServerContext, session: Optional[ClientSession] = None):
        self.transport_name = "UDP"
        self.transport = transport
        self.addr = addr
        self.server = server # <--- Access to Config, Logger, etc.
        self.session = session # <--- The specific player this packet came from
        self.outgoing_seq = 0
        self.reliable_delivery_order: dict[int, deque[int]] = {}
        self.reliable_delivery_seen: dict[int, set[int]] = {}

    def send(self, payload: bytes | Packet):
        if self.session is not None and self.session.stop_ping_event.is_set():
            return
        # Type guarding: explicitly separate bytes from Packets
        if isinstance(payload, Packet):
            payload = payload.serialize()
        else:
            payload = payload


        self.transport.send(payload, self.addr)
        self.server.trace.packet(
            "server_to_client",
            self.transport_name,
            payload,
            addr=self.addr,
        )
        self.server.logger.log_packet("UDP-SEND", 
                                      payload, addr=self.addr, 
                                      show_ascii=self.server.cfg.debug.show_ascii, 
                                      include_tcp_len_prefix=False)

    def send_ack(self, packet_id: int, seq_num: int, subcmd: int = 1):
        """Sends a standard UDP ACK (0x02)"""
        # Our D_HANDSHAKE advertises opcode 0x02 on reliable stream mode 1.
        # The client therefore unwraps [sequence][total length] before passing
        # the D_ACK body to its handler. This is intentionally asymmetric with
        # the raw five-byte D_ACK records the client sends to the server.
        self.outgoing_seq = (self.outgoing_seq + 1) & 0xFFFF
        pkt = PacketWriter()
        pkt.write_int16(self.outgoing_seq)
        pkt.write_int16(9)
        pkt.write_byte(subcmd)
        pkt.write_byte(packet_id)
        pkt.write_int16(seq_num)

        self.send(b'\x02' + pkt.get_bytes())

    def accept_reliable_delivery(self, packet_id: int, seq_num: int) -> bool:
        """ACK one delivery and return whether its side effects are new."""
        self.send_ack(packet_id=packet_id, seq_num=seq_num)
        sequence = seq_num & 0xFFFF
        seen = self.reliable_delivery_seen.setdefault(packet_id, set())
        if sequence in seen:
            return False

        order = self.reliable_delivery_order.setdefault(packet_id, deque())
        order.append(sequence)
        seen.add(sequence)
        if len(order) > RELIABLE_REPLAY_HISTORY:
            seen.remove(order.popleft())
        return True

# -------------------------------------------------------------------------
# DISPATCHER & HANDLERS
# -------------------------------------------------------------------------

def get_sync_mode(server: WulframServerContext) -> str:
    return server.hooks.mode_name


def should_run_server_simulation(server: WulframServerContext) -> bool:
    return bool(server.hooks.authoritative_physics_enabled)


def _owner_mutation_prohibited(
    server: WulframServerContext,
    session: ClientSession | None,
    category: str,
    detail: str,
) -> bool:
    return server.hooks.owner_mutation_prohibited(
        server,
        session,
        category,
        detail,
    )


def _note_entity_spawn(
    session: ClientSession,
    entity: GameEntity,
    source: str,
) -> None:
    entity.score_owner_id = session.player_id
    entity.spawn_protection_remaining = SPAWN_PROTECTION_SECONDS
    entity.spawn_protection_notice_pending = not getattr(session, "is_bot", False)
    session.death_cleanup_at = 0.0
    session.death_delete_explosion = False
    entity.is_docked = False
    session.ground_dock_armed = True
    session.ground_dock_settle_started_at = None
    session.ground_dock_reference_pos = None
    session.ground_dock_reference_rot = None
    session.ground_dock_last_physics_tick = 0
    session.server.hooks.entity_spawned(session, entity, source)


def _update_spawn_protection_notices(server: WulframServerContext) -> None:
    for session in tuple(server.sessions):
        entity = session.entity
        if (entity is not None and entity.spawn_protection_notice_pending
                and entity.spawn_protection_remaining <= 0):
            entity.spawn_protection_notice_pending = False
            if session.is_logged_in and session.udp_context and entity.health_points > 0:
                send_system_message(session.udp_context, "Spawn shield ended. You can now take damage.")


def switch_session_team(context: TcpContext | UdpContext, team_id: int) -> bool:
    """Move an administrator and their current vehicle to a supported team."""
    if team_id not in TEAM_SIDE_BY_ID:
        raise ValueError(f"unsupported team id {team_id}")
    session = getattr(context, "session", None)
    if session is None:
        return False

    entity = getattr(session, "entity", None)
    if session.team == team_id and (
        entity is None or entity.team_id == team_id
    ):
        return False

    previous_team = session.team
    session.spawn_delivery = None
    session.team = team_id
    if entity is not None:
        entity.team_id = team_id
        # Team lives in the entity definition. Include the complete pose so
        # the stock client reselects its team-specific Tank presentation and
        # the native body is recreated at the same location.
        entity.mark_dirty(
            UpdateMask.DEFINITION
            | UpdateMask.POS
            | UpdateMask.VEL
            | UpdateMask.ROT
            | UpdateMask.SPIN
            | UpdateMask.HARD_SYNC
        )

    from wulfram_server.matches import stats_packet
    broadcast(context.server, stats_packet(session))
    trace_state = getattr(getattr(context.server, "trace", None), "state", None)
    if callable(trace_state):
        trace_state(
            "ADMIN_TEAM_CHANGED",
            player=session.player_id,
            previous_team=previous_team,
            requested_team=team_id,
            effective_team=session.team,
        )
    return True


def send_existing_player_entity_definitions(ctx: TcpContext | UdpContext, reason: str) -> bool:
    """Replay existing player entity definitions to a newly spawned client.

    This is a join-in-progress catch-up path. It does not depend on dirty flags,
    because already-spawned player entities may have cleared their DEFINITION bit
    before this client entered the world.
    """
    session = getattr(ctx, "session", None)
    if session is None or session.entity is None:
        return False

    entities_by_id: dict[int, GameEntity] = {}
    for other_session in ctx.server.sessions:
        if other_session is session or not other_session.is_logged_in:
            continue

        entity = getattr(other_session, "entity", None)
        if entity is None or not getattr(entity, "is_manned", False):
            continue

        entities_by_id[entity.net_id] = entity

    if not entities_by_id:
        return False

    target_ctx = session.udp_context or ctx
    entities = sorted(entities_by_id.values(), key=lambda entity: entity.net_id)

    # Replay birth notices because late joiners missed the original spawn-time
    # broadcast. The original spawn path uses entity net_id here.
    player_id_by_entity = {
        other_session.entity.net_id: other_session.player_id
        for other_session in ctx.server.sessions
        if other_session.entity is not None
    }
    for entity in entities:
        target_ctx.send(BirthNoticePacket(
            player_id=player_id_by_entity[entity.net_id],
            entity_id=entity.net_id,
        ))

    forced_mask = (
        UpdateMask.DEFINITION
        | UpdateMask.POS
        | UpdateMask.VEL
        | UpdateMask.ROT
        | UpdateMask.HEALTH
        | UpdateMask.WEAPON
        | UpdateMask.OWNER
    )
    local_stats = _local_stats(session.entity)
    payloads = ctx.server.entities.build_forced_update_packets(
        entities,
        sequence_num=get_ticks(),
        is_view_update=False,
        forced_mask=forced_mask,
        local_stats=local_stats,
        force_spawn=True,
        viewer_team=session.team,
    )
    for payload in payloads:
        target_ctx.send(b"\x0E" + payload)
    for other_session in ctx.server.sessions:
        if getattr(other_session, "carried_cargo_item_id", None) is None:
            continue
        target_ctx.send(CarryingInfoPacket(
            player_id=other_session.player_id,
            has_cargo=True,
            unk_v2=other_session.team,
            item_id=(
                other_session.carried_cargo_item_id
                if getattr(session, "team", 0)
                == getattr(other_session, "carried_cargo_team_id", 0)
                else CARGO_LOCKED_ITEM_ID
            ),
        ))
    ids = ",".join(str(entity.net_id) for entity in entities)
    print(
        "[sync] sent late-join entity definitions "
        f"reason={reason} to_player={session.player_id} entities={ids}"
    )
    return True


def _reset_ground_dock_settling(session: ClientSession) -> None:
    session.ground_dock_settle_started_at = None
    session.ground_dock_reference_pos = None
    session.ground_dock_reference_rot = None
    session.ground_dock_last_physics_tick = 0


def _rotated_x_axis(euler: tuple[float, float, float]) -> tuple[float, float, float]:
    """Match the X-axis alignment proxy used by the recovered sleep test."""
    _, angle_y, angle_z = euler
    cos_y = math.cos(angle_y)
    return (
        cos_y * math.cos(angle_z),
        cos_y * math.sin(angle_z),
        -math.sin(angle_y),
    )


def _ground_dock_body_is_settled(
    session: ClientSession,
    entity: GameEntity,
    now: float,
    *,
    require_native_contact: bool,
) -> bool:
    """Track generic body settling without assuming what supports the Tank."""
    if require_native_contact:
        physics_step_tick = int(getattr(entity, "physics_step_tick", 0) or 0)
        last_physics_tick = int(
            getattr(session, "ground_dock_last_physics_tick", 0) or 0
        )
        if physics_step_tick <= last_physics_tick:
            return False
        session.ground_dock_last_physics_tick = physics_step_tick

        # The original runs ProcessBodySettlingAndSleep from the generic
        # contact-constraint path. A step without a constraint neither docks
        # the body nor destroys the quiet history; the next contact evaluates
        # displacement from the last contact pose. This works for terrain and
        # for any future body/body or static-object constraints alike.
        if int(getattr(entity, "physics_contact_tick", 0) or 0) != physics_step_tick:
            return False

    reference_pos = getattr(session, "ground_dock_reference_pos", None)
    reference_rot = getattr(session, "ground_dock_reference_rot", None)
    if reference_pos is None or reference_rot is None:
        session.ground_dock_reference_pos = entity.pos
        session.ground_dock_reference_rot = entity.rot
        session.ground_dock_settle_started_at = now
        return False

    position_drift = sum(abs(a - b) for a, b in zip(reference_pos, entity.pos))
    reference_axis = _rotated_x_axis(reference_rot)
    current_axis = _rotated_x_axis(entity.rot)
    orientation_drift = abs(
        1.0 - sum(a * b for a, b in zip(reference_axis, current_axis))
    )
    linear_speed = math.sqrt(sum(component * component for component in entity.vel))
    angular_speed = math.sqrt(sum(component * component for component in entity.spin))

    # The original contact solver stores a geometry/contact-derived settling
    # threshold on the body. The portable core exposes that value when it is
    # authoritative; relay mode falls back to the recovered zero-threshold
    # constants because relay packets do not carry collision events. No
    # terrain height, jet-probe depth, or support object is assumed.
    contact_threshold = max(
        0.0,
        float(getattr(entity, "settling_contact_threshold", 0.0) or 0.0),
    )
    position_limit = contact_threshold + GROUND_DOCK_BASE_POSITION_DRIFT
    orientation_limit = (
        contact_threshold / 100.0 + GROUND_DOCK_BASE_ORIENTATION_DRIFT
    )
    motion_limit = contact_threshold * 1.4 + GROUND_DOCK_BASE_MOTION
    is_quiet = (
        position_drift < position_limit
        and orientation_drift < orientation_limit
        and linear_speed < motion_limit
        and angular_speed < motion_limit
    )

    # ProcessBodySettlingAndSleep refreshes its reference pose after each test,
    # so this measures continued small per-step drift rather than distance from
    # the pose at which the jets first reached zero.
    session.ground_dock_reference_pos = entity.pos
    session.ground_dock_reference_rot = entity.rot
    if not is_quiet:
        session.ground_dock_settle_started_at = now
        return False

    settle_started_at = getattr(session, "ground_dock_settle_started_at", None)
    if settle_started_at is None:
        session.ground_dock_settle_started_at = now
        return False
    return now - settle_started_at >= GROUND_DOCK_SETTLE_SECONDS


def _send_owner_pose_update(
    server: WulframServerContext,
    session: ClientSession,
    *,
    sequence_id: int,
    hard_sync: bool,
) -> None:
    """Send the local client the pose half of a docking transition."""
    entity = session.entity
    if entity is None or session.udp_context is None:
        return

    # UPDATE_ARRAY bit 9 is the client's hard-authoritative path. Supplying
    # both position and rotation with it calls PutBodyToSleep; a later update
    # without bit 9 takes the wake path. Velocity and spin are included so the
    # transition also communicates the server's zeroed motion explicitly.
    mask = UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT | UpdateMask.SPIN
    if hard_sync:
        mask |= UpdateMask.HARD_SYNC
    payload = server.entities.build_forced_update_packet(
        [entity],
        sequence_num=sequence_id,
        is_view_update=True,
        forced_mask=mask,
        local_stats=_local_stats(entity),
        force_spawn=False,
    )
    if payload:
        session.udp_context.send(b"\x0F" + payload)


def _set_ground_docked(
    server: WulframServerContext,
    session: ClientSession,
) -> None:
    """Enter the authoritative and client-side ground-docked states once."""
    entity = session.entity
    if entity is None or session.udp_context is None or entity.is_docked:
        return

    entity.vel = (0.0, 0.0, 0.0)
    entity.spin = (0.0, 0.0, 0.0)
    entity.is_docked = True
    entity.pending_inputs.clear()
    entity.mark_dirty(
        UpdateMask.POS
        | UpdateMask.VEL
        | UpdateMask.ROT
        | UpdateMask.SPIN
        | UpdateMask.HARD_SYNC
    )
    session.ground_dock_armed = False
    _reset_ground_dock_settling(session)

    sequence_id = get_ticks()
    _send_owner_pose_update(
        server,
        session,
        sequence_id=sequence_id,
        hard_sync=True,
    )
    # Packet 0x38 stores this sequence as an undock barrier. Reusing the hard
    # pose sequence means an equal update is safe, while any later *soft*
    # owner update intentionally releases a stale docking latch. The packet is
    # transition-only: repeating dock=true would push nested client input
    # contexts that one undock packet cannot completely restore.
    session.udp_context.send(DockingPacket(
        entity_id=GROUND_DOCK_TARGET_ENTITY_ID,
        is_docked=True,
        sequence_id=sequence_id,
    ))
    entity.pending_transient_events.append(PendingTransientEvent(
        event_type=TANK_POWERDOWN_TRANSIENT_TYPE,
        entity_id=entity.net_id,
    ))


def _clear_ground_docked(
    server: WulframServerContext,
    session: ClientSession,
    *,
    rearm_for_jump: bool = False,
) -> None:
    """Leave ground docking and wake the local client's physics body once."""
    entity = session.entity
    if entity is None or session.udp_context is None or not entity.is_docked:
        return

    entity.is_docked = False
    entity.pending_mask &= ~UpdateMask.HARD_SYNC
    entity.pending_view_mask &= ~UpdateMask.HARD_SYNC
    entity.mark_dirty(UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT | UpdateMask.SPIN)
    # Raising the hover jets deliberately waits for a later neutral sample
    # before another dock. A jump is a complete takeoff/landing cycle, so it
    # may begin a fresh settling attempt after the body comes back down.
    session.ground_dock_armed = rearm_for_jump
    _reset_ground_dock_settling(session)

    # Inputs received while docked are not queued into authoritative physics.
    # Preserve only the current wake sample (raised jets or jump edge) so the
    # newly recreated native Tank sees the transition exactly once.
    if session.physics_input_sequence > entity.input_sequence:
        entity.record_input_sample(sequence=session.physics_input_sequence)

    sequence_id = get_ticks()
    session.udp_context.send(DockingPacket(
        entity_id=GROUND_DOCK_TARGET_ENTITY_ID,
        is_docked=False,
        sequence_id=sequence_id,
    ))
    _send_owner_pose_update(
        server,
        session,
        sequence_id=sequence_id,
        hard_sync=False,
    )


def _update_ground_docking(server: WulframServerContext) -> None:
    """Latch a settled zero-jet body and release it when the jets are raised."""
    if not server.hooks.ground_docking_enabled:
        return
    for session in server.sessions:
        entity = session.entity
        if (
            not session.is_logged_in
            or session.udp_context is None
            or entity is None
            or not entity.is_manned
        ):
            continue

        jet_input = float(entity.actions.get(5, 0.0) or 0.0)
        if entity.is_docked:
            if jet_input > GROUND_DOCK_JET_OFF_THRESHOLD:
                _clear_ground_docked(server, session)
                print(
                    "[ground-dock] released "
                    f"player={session.player_id} entity={entity.net_id}"
                )
            continue

        if jet_input > GROUND_DOCK_JET_OFF_THRESHOLD:
            session.ground_dock_armed = True
            _reset_ground_dock_settling(session)
            continue

        if not session.ground_dock_armed:
            continue

        if not _ground_dock_body_is_settled(
            session,
            entity,
            time.monotonic(),
            require_native_contact=should_run_server_simulation(server),
        ):
            continue

        if _owner_mutation_prohibited(
            server,
            session,
            "ground_docks",
            f"zero-jet body settled for entity {entity.net_id}",
        ):
            session.ground_dock_armed = False
            continue

        px, py, pz = entity.pos
        _set_ground_docked(server, session)
        print(
            "[ground-dock] latched "
            f"player={session.player_id} entity={entity.net_id} "
            f"pos=({px:.2f}, {py:.2f}, {pz:.2f}) "
            f"contact_threshold={entity.settling_contact_threshold:.4f}"
        )


def _local_stats(entity: GameEntity) -> tuple[float, float, int, int, float, float]:
    return (
        entity.health,
        entity.energy,
        entity.weapon_table_id,
        entity.weapon_ready_mask,
        entity.pulse_charge,
        entity.repair_charge,
    )


def _destroy_authoritative_entity(
    server: WulframServerContext,
    entity: GameEntity,
    *,
    explosion: bool,
    defer_player_removal: bool = True,
    killer_player_id: int | None = None,
) -> bool:
    """Perform the one terminal transition shared by every lethal source."""
    if server.entities.get_entity(entity.net_id) is not entity:
        return False

    delete_explosion = explosion
    if entity.unit_type in (PULSE_UNIT_TYPE, FLAK_SHELL_UNIT_TYPE):
        if explosion:
            # DELETE_OBJECT's nonzero mode couples projectile particles and
            # sound to a red dynamic light. In the stock first-person
            # software renderer that light can leave the entire view tinted
            # until the presentation system is reset. Transient 0x27 is the
            # client's dedicated positional explosion path; its entity type
            # selects the matching shell presentation without that light.
            broadcast(server, TransientArrayPacket([
                ExplosionTransient(
                    position=tuple(entity.pos),
                    entity_type=entity.unit_type,
                ),
            ]))
            delete_explosion = False

    owner_session = next(
        (session for session in server.sessions if session.entity is entity),
        None,
    )
    if owner_session is not None and getattr(owner_session, "death_cleanup_at", 0.0) > 0.0:
        return False
    if killer_player_id is not None:
        from wulfram_server.matches import record_destruction
        record_destruction(server, entity, killer_player_id)
    if owner_session is not None:
        owner_session.spawn_delivery = None
        if getattr(owner_session, "carried_cargo_item_id", None) is not None:
            owner_session.carried_cargo_item_id = None
            owner_session.carried_cargo_team_id = 0
            _send_carrying_info(server, owner_session, has_cargo=False)
        broadcast(server, DeathNoticePacket(owner_session.player_id))
        death_deadline = (
            time.monotonic() + server.packet_cfg.combat.construction_timeout_seconds
        )
        owner_session.construction_ready_at = death_deadline
        if defer_player_removal:
            # Keep the authoritative registry entry long enough for both the
            # owner VIEW_UPDATE and remote UPDATE_ARRAY streams to publish its
            # zero health. Removing it from native authority also prevents a
            # dead Tank from moving, colliding, or firing during the fade.
            entity.is_manned = False
            entity.actions.clear()
            entity.pending_inputs.clear()
            entity.pending_transient_events.clear()
            entity.previous_weapon_actions = 0
            entity.weapon_ready_mask = 0
            entity.mark_dirty(UpdateMask.HEALTH | UpdateMask.WEAPON)
            owner_session.death_cleanup_at = death_deadline
            owner_session.death_delete_explosion = delete_explosion
            return True

        owner_session.entity = None
        owner_session.death_cleanup_at = 0.0
        owner_session.death_delete_explosion = False
        server.hooks.entity_removed(owner_session, "death")

    server.entities.remove_entity(entity.net_id)
    broadcast(server, DeleteObjectPacket(entity.net_id, explosion=delete_explosion))
    return True


def _finalize_expired_player_deaths(
    server: WulframServerContext,
    now: float,
) -> None:
    """Delete player wrecks after the client-visible death interval."""
    # A staged administrative map change owns wreck cleanup so it can preserve
    # its one-entity-per-interval contract instead of racing this bulk scan.
    if getattr(server, "map_change_transition", None) is not None:
        return
    for session in tuple(server.sessions):
        deadline = float(getattr(session, "death_cleanup_at", 0.0) or 0.0)
        if deadline <= 0.0 or now < deadline:
            continue

        _finalize_player_death(server, session)


def _finalize_player_death(
    server: WulframServerContext,
    session: ClientSession,
) -> bool:
    """Finalize one player wreck after its visible-death interval."""
    entity = getattr(session, "entity", None)
    explosion = bool(getattr(session, "death_delete_explosion", False))
    session.death_cleanup_at = 0.0
    session.death_delete_explosion = False
    session.entity = None
    if entity is None:
        return False

    server.hooks.entity_removed(session, "death")
    packet = server.entities.remove_entity(entity.net_id)
    if packet is None:
        return False
    broadcast(
        server,
        DeleteObjectPacket(entity.net_id, explosion=explosion),
    )
    return True


def _send_carrying_info(
    server: WulframServerContext,
    carrier: ClientSession,
    *,
    has_cargo: bool,
) -> None:
    """Send the stock carrying state with team-scoped cargo disclosure."""
    actual_item_id = carrier.carried_cargo_item_id
    cargo_team_id = carrier.carried_cargo_team_id
    for recipient in server.sessions:
        if not recipient.is_logged_in or not recipient.is_ready_for_updates:
            continue
        target = recipient.udp_context
        if target is None:
            continue
        visible_item_id = 0
        if has_cargo and actual_item_id is not None:
            visible_item_id = (
                actual_item_id
                if recipient.team == cargo_team_id
                else CARGO_LOCKED_ITEM_ID
            )
        target.send(CarryingInfoPacket(
            player_id=carrier.player_id,
            has_cargo=has_cargo,
            unk_v2=carrier.team,
            item_id=visible_item_id,
        ))


def _pickup_cargo(
    server: WulframServerContext,
    carrier: ClientSession,
    cargo: GameEntity,
) -> bool:
    if carrier.entity is None or carrier.carried_cargo_item_id is not None:
        return False
    if carrier.entity.vehicle_loadout == "siege":
        return False
    if cargo.unit_type != CARGO_UNIT_TYPE:
        return False
    if not CARGO_ITEM_ID_MIN <= cargo.cargo_item_id <= CARGO_ITEM_ID_MAX:
        return False
    if server.entities.get_entity(cargo.net_id) is not cargo:
        return False

    carrier.carried_cargo_item_id = cargo.cargo_item_id
    carrier.carried_cargo_team_id = carrier.team if cargo.team_id == 0 else cargo.team_id
    server.entities.remove_entity(cargo.net_id)
    broadcast(server, DeleteObjectPacket(cargo.net_id, explosion=False))
    _send_carrying_info(server, carrier, has_cargo=True)
    print(
        "[cargo] pickup "
        f"player={carrier.player_id} tank={carrier.entity.net_id} "
        f"cargo={cargo.net_id} item={cargo.cargo_item_id} team={cargo.team_id}"
    )
    return True


def _process_cargo_contacts(server: WulframServerContext) -> None:
    if server.physics is None:
        return
    sessions_by_entity = {
        session.entity.net_id: session
        for session in server.sessions
        if session.entity is not None
    }
    for contact in server.physics.take_tank_contacts():
        carrier = sessions_by_entity.get(int(contact.get("entity_id", 0) or 0))
        cargo = server.entities.get_entity(
            int(contact.get("other_entity_id", 0) or 0)
        )
        if carrier is not None and cargo is not None:
            _pickup_cargo(server, carrier, cargo)


def _cargo_drop_position(entity: GameEntity) -> tuple[float, float, float]:
    yaw = float(entity.rot[2])
    return (
        float(entity.pos[0]) - math.cos(yaw) * CARGO_DROP_OFFSET,
        float(entity.pos[1]) - math.sin(yaw) * CARGO_DROP_OFFSET,
        float(entity.pos[2]),
    )


def _handle_cargo_request(
    server: WulframServerContext,
    carrier: ClientSession,
    *,
    deploy: bool,
) -> GameEntity | None:
    entity = carrier.entity
    item_id = carrier.carried_cargo_item_id
    cargo_team_id = carrier.carried_cargo_team_id
    if entity is None or item_id is None:
        return None
    if not CARGO_ITEM_ID_MIN <= item_id <= CARGO_ITEM_ID_MAX:
        return None

    carrier.carried_cargo_item_id = None
    carrier.carried_cargo_team_id = 0
    _send_carrying_info(server, carrier, has_cargo=False)

    spawned = server.entities.create_entity(
        unit_type=(
            CARGO_DEPLOY_UNIT_TYPE_BASE + item_id
            if deploy
            else CARGO_UNIT_TYPE
        ),
        team_id=carrier.team if deploy else cargo_team_id,
        pos=tuple(entity.pos) if deploy else _cargo_drop_position(entity),
    )
    spawned.rot = tuple(entity.rot)
    spawned.score_owner_id = carrier.player_id
    spawned.mark_dirty(UpdateMask.ROT | UpdateMask.HARD_SYNC)
    if not deploy:
        spawned.cargo_item_id = item_id
    print(
        f"[cargo] {'deploy' if deploy else 'drop'} "
        f"player={carrier.player_id} item={item_id} spawned={spawned.net_id} "
        f"unit={spawned.unit_type} team={spawned.team_id}"
    )
    return spawned


def _finalize_combat_destructions(
    server: WulframServerContext,
    destructions: list[Destruction],
) -> None:
    for destruction in destructions:
        entity = server.entities.get_entity(destruction.entity_id)
        if entity is not None:
            _destroy_authoritative_entity(
                server,
                entity,
                explosion=destruction.explosion,
                killer_player_id=destruction.killer_player_id,
            )

def _broadcast_dirty_state(
    server: WulframServerContext,
    *,
    send_update_arrays: bool = True,
    send_view_updates: bool = True,
) -> None:
    dirty_entities = server.entities.get_dirty_entities()
    view_dirty_entities = server.entities.get_view_dirty_entities()
    update_versions = [(entity, entity.dirty_generation) for entity in dirty_entities]
    view_versions = [(entity, entity.dirty_generation) for entity in view_dirty_entities]
    current_tick = get_ticks()
    # The retail client zero-initializes missing vitals (0x004e5db0) and
    # unconditionally applies them after every array (0x0047de72). Each
    # datagram must carry this recipient's stats, including split chunks.
    entity_cache = {}

    if (send_update_arrays and dirty_entities) or (send_view_updates and view_dirty_entities):
        for session in server.sessions:
            if not session.is_logged_in or not session.is_ready_for_updates:
                continue
            if not session.udp_context or not session.entity:
                continue

            my_entity = session.entity
            my_stats = _local_stats(my_entity)
            others = [e for e in dirty_entities if e.net_id != my_entity.net_id]
            if send_update_arrays and dirty_entities:
                payloads = server.entities.build_update_packets(
                    others,
                    sequence_num=current_tick,
                    is_view_update=False,
                    local_stats=my_stats,
                    viewer_team=getattr(session, "team", None),
                    entity_cache=entity_cache,
                )
                for payload in payloads:
                    session.udp_context.send(b'\x0E' + payload)
                    if any(e.pending_mask & UpdateMask.HARD_SYNC for e in others):
                        now = time.monotonic()
                        if now - server._last_hard_sync_log >= 2.0:
                            server._last_hard_sync_log = now
                            ids = ",".join(
                                str(e.net_id)
                                for e in others
                                if e.pending_mask & UpdateMask.HARD_SYNC
                            )
                            print(
                                "[snapshot] broadcast 0x0E hard-sync "
                                f"to_player={session.player_id} entities={ids}"
                            )

            if send_view_updates and my_entity in view_dirty_entities:
                if server.hooks.suppress_owner_view_update(server, session, my_entity):
                    continue
                if my_entity.is_docked:
                    # A newer soft owner update clears packet 0x38's docking
                    # latch. Force every docked owner update through bit 9 and
                    # include both pose vectors, keeping the client asleep
                    # without repeating the docking packet/input-context push.
                    docked_mask = (
                        UpdateMask(my_entity.pending_view_mask)
                        | UpdateMask.POS
                        | UpdateMask.ROT
                        | UpdateMask.HARD_SYNC
                    )
                    payload = server.entities.build_forced_update_packet(
                        [my_entity],
                        sequence_num=current_tick,
                        is_view_update=True,
                        forced_mask=docked_mask,
                        local_stats=my_stats,
                        force_spawn=bool(docked_mask & UpdateMask.DEFINITION),
                        viewer_team=getattr(session, "team", None),
                    )
                    if payload:
                        session.udp_context.send(b'\x0F' + payload)
                    continue
                if server.hooks.suppress_owner_state_echo(server, session, my_entity):
                    continue
                view_mask = UpdateMask(my_entity.pending_view_mask)
                mask_transform = getattr(server.hooks, "owner_view_update_mask", None)
                if mask_transform is not None:
                    view_mask = mask_transform(server, session, my_entity, view_mask)
                payload = server.entities.build_forced_update_packet(
                    [my_entity],
                    sequence_num=current_tick,
                    is_view_update=True,
                    forced_mask=view_mask,
                    local_stats=my_stats,
                    force_spawn=bool(view_mask & UpdateMask.DEFINITION),
                    viewer_team=getattr(session, "team", None),
                    reconciliation_tick=my_entity.physics_step_tick,
                    acknowledged_input_marker=my_entity.last_processed_client_marker,
                    acknowledged_input_tick=my_entity.last_processed_client_tick,
                )
                if payload:
                    session.udp_context.send(b'\x0F' + payload)

    if send_update_arrays:
        server.entities.clear_update_dirty_flags(update_versions)
    if send_view_updates:
        server.entities.clear_view_dirty_flags(view_versions)
        server.hooks.after_view_broadcast(server)


def _broadcast_pending_transients(server: WulframServerContext) -> None:
    """Send queued one-shot events, with any required owner correction first."""
    sources = [
        entity
        for entity in server.entities.get_all()
        if entity.pending_transient_events
    ]
    if not sources:
        return

    sequence_id = get_ticks()
    motion_source_ids = {
        entity.net_id
        for entity in sources
        if any(
            event.requires_owner_motion_update
            for event in entity.pending_transient_events
        )
    }
    for session in server.sessions:
        if (
            not session.is_logged_in
            or not session.is_ready_for_updates
            or session.udp_context is None
            or session.entity is None
        ):
            continue
        owner = session.entity
        if owner.net_id not in motion_source_ids:
            continue
        # The stock Tank controller does not consume action channel 4. Give
        # the owner the accepted linear/angular impulse immediately through a
        # normal soft VIEW_UPDATE; later scheduled snapshots carry position.
        jump_motion_mask = UpdateMask.VEL | UpdateMask.SPIN
        payload = server.entities.build_forced_update_packet(
            [owner],
            sequence_num=sequence_id,
            is_view_update=True,
            forced_mask=jump_motion_mask,
            local_stats=_local_stats(owner),
            force_spawn=False,
        )
        if payload:
            session.udp_context.send(b'\x0F' + payload)
            owner.pending_view_mask &= ~jump_motion_mask

    events = []
    for entity in sources:
        for pending in entity.pending_transient_events:
            if pending.position is not None:
                events.append(PositionalTransient(
                    event_type=pending.event_type,
                    position=pending.position,
                ))
            elif pending.entity_id is not None:
                events.append(EntityTransient(
                    event_type=pending.event_type,
                    entity_id=pending.entity_id,
                ))
    for start in range(0, len(events), 0xFF):
        packet = TransientArrayPacket(tuple(events[start:start + 0xFF]))
        for session in server.sessions:
            if (
                session.is_logged_in
                and session.is_ready_for_updates
                and session.udp_context is not None
            ):
                session.udp_context.send(packet)

    for entity in sources:
        entity.pending_transient_events.clear()


def global_game_loop(server: WulframServerContext):
    """Advance physics, remote snapshots, and owner corrections separately."""
    physics_interval = server.cfg.physics.tick_milliseconds / 1000.0
    network_interval = 1.0 / server.cfg.physics.network_hz
    view_update_interval = 1.0 / server.cfg.physics.view_update_hz
    next_physics = time.monotonic()
    next_broadcast = next_physics
    next_view_update = next_physics
    print(
        "[Server] Starting Global Game Loop "
        f"(physics={server.cfg.physics.tick_milliseconds}ms, "
        f"network={server.cfg.physics.network_hz:g}Hz, "
        f"view={server.cfg.physics.view_update_hz:g}Hz)..."
    )

    while not server.stop_update_event.is_set():
        server.last_game_loop_at = time.monotonic()
        server.hooks.before_game_loop_iteration(server)

        now = time.monotonic()
        _finalize_expired_player_deaths(server, now)
        server.bots.step(now)
        if should_run_server_simulation(server):
            if server.physics is None:
                raise RuntimeError("server_simulation selected without a native physics host")
            catch_up_steps = 0
            while now >= next_physics and catch_up_steps < server.physics.max_catch_up_steps:
                try:
                    server.physics.step(server.land)
                    _process_cargo_contacts(server)
                    if server.combat is not None:
                        destructions = server.combat.step(physics_interval)
                        _finalize_combat_destructions(server, destructions)
                except Exception as error:
                    print(f"[physics] FATAL authoritative step failed: {error}")
                    server.fatal_error = f"authoritative physics failed: {type(error).__name__}"
                    server.stop_update_event.set()
                    server.stop_event.set()
                    return
                next_physics += physics_interval
                catch_up_steps += 1

            if now >= next_physics:
                dropped = int((now - next_physics) // physics_interval) + 1
                server.physics.note_dropped_catch_up_ticks(dropped)
                next_physics += dropped * physics_interval
        else:
            next_physics = now + network_interval

        # Evaluate elimination after combat and entity cleanup so destroying
        # either the last live vehicle or the final repair pad can end a match.
        from wulfram_server import admin_commands

        admin_commands.check_win_condition(server)

        _update_spawn_protection_notices(server)
        _update_spawn_deliveries(server, now)
        _update_ground_docking(server)

        # Accepted jump traces are gameplay events rather than periodic state.
        # Drain them every loop so the owner does not wait for the slower
        # VIEW_UPDATE cadence before receiving the authoritative impulse.
        _broadcast_pending_transients(server)

        now = time.monotonic()
        send_update_arrays = now >= next_broadcast
        send_view_updates = now >= next_view_update
        if send_update_arrays or send_view_updates:
            _broadcast_dirty_state(
                server,
                send_update_arrays=send_update_arrays,
                send_view_updates=send_view_updates,
            )
        if send_update_arrays:
            while next_broadcast <= now:
                next_broadcast += network_interval
        if send_view_updates:
            while next_view_update <= now:
                next_view_update += view_update_interval

        deadline = min(next_physics, next_broadcast, next_view_update)
        server.stop_update_event.wait(max(0.0, deadline - time.monotonic()))

def start_ping_loop(ctx: TcpContext):
    def run():
        next_ping = 0.0
        while not ctx.stop_ping_event.is_set():
            try:
                if ctx.session.world_change_event.is_set():
                    announce_world(ctx)
                if time.monotonic() >= next_ping:
                    ctx.send(PingRequestPacket())
                    next_ping = time.monotonic()+10.0
                ctx.session.world_change_event.wait(max(0.0, next_ping-time.monotonic()))
            except Exception:
                ctx.session.disconnect()
                break
    threading.Thread(target=run, daemon=True).start()

def unknown_packet(ctx, payload: bytes):
    opcode = payload[0]
    
    if opcode in [0x09, 0x0A, 0x0B, 0x0C, 0x10, 0x40, 0x49]:
            return
    
    if ctx.server.cfg.debug.debug_packets:
        print(f"[?] Unknown opcode 0x{opcode:02X} (len={len(payload)})")

# Create dispatcher early here
dispatcher = PacketDispatcher(on_unknown=unknown_packet)

# --- TCP Routes ---

@dispatcher.datagram_route(0x13)
@dispatcher.route(0x13)
def on_hello(
    ctx: TcpContext | UdpContext,
    payload_or_reader: bytes | PacketReader,
):
    if isinstance(payload_or_reader, bytes):
        payload = payload_or_reader
        if len(payload) < 2:
            return
        ctx.server.logger.log_packet("TCP-RECV", payload)
        reader = PacketReader(payload)
        reader.read_byte() # Op
    else:
        # UDP uses the datagram's shared cursor; the dispatcher consumed Op.
        reader = payload_or_reader

    subcmd = reader.read_byte()

    if subcmd == 0x00:
        # Client sent Version (Sub 0) - This comes from start_udp_send_hello_root
        # payload usually contains the version int (20105)
        version = reader.read_int32()
        #ctx.send(HelloPacket.create_version())

    # HELLO subcmd 1: UDP config request/ack
    elif subcmd == 0x01:
        # Client Echoed Key (Sub 1) - This comes from send_hello2
        client_key = reader.read_string()
        
        # CASE A: We already have a session (TCP or already linked UDP)
        if ctx.session:
            if (isinstance(ctx, UdpContext) and not ctx.session.stop_ping_event.is_set()
                    and client_key == ctx.session.session_key):
                print(f">>> [{type(ctx).__name__}] Session key verified")
                ctx.session.key_echoed_event.set()
                ctx.send(IdentifiedUdpPacket())

        # CASE B: Sessionless UDP Context (This is the new logic)
        elif isinstance(ctx, UdpContext) and ctx.session is None:
            # Find the TCP session that generated this key
            found_session = None
            for s in ctx.server.sessions:
                # CPU players share the roster but never own network keys or
                # handshake events. Only a TCP client can claim this UDP peer.
                if not isinstance(s, ClientSession):
                    continue
                if (s.session_key == client_key and not s.stop_ping_event.is_set()
                        and s.address[0] == ctx.addr[0]
                        and s.udp_addr in (None, ctx.addr)):
                    found_session = s
                    break
            
            if found_session:
                print(f">>> [UDP] LINKED! {ctx.addr} belongs to {found_session.address}")
                
                # Link everything up
                ctx.session = found_session
                found_session.udp_addr = ctx.addr
                found_session.udp_context = ctx
                ctx.server.udp_sessions[ctx.addr] = ctx
                ctx.server.trace.state(
                    "UDP_LINKED",
                    player=found_session.player_id,
                    peer=f"{ctx.addr[0]}:{ctx.addr[1]}",
                )
                
                # Signal Main Thread
                found_session.key_echoed_event.set()
                
                # 3. Reply immediately on UDP
                ctx.send(IdentifiedUdpPacket())

    # HELLO subcmd 2: Not quite sure what this means
    # possibly just confirming the UDP link was verified?
    elif subcmd == 0x02:
        # This comes from send_hello3
        pass

    else:
        raise PacketDecodeError("unknown HELLO subcommand")


@dispatcher.route(0x21)
def on_login_request(ctx: TcpContext, payload: bytes):
    if ctx.session.is_logged_in:
        return
    reader = PacketReader(payload)
    reader.read_byte() # Op
    ctx.session.login_subcommand = reader.read_byte()
    name = reader.read_string().strip()
    password = reader.read_string()
    if (not 1 <= len(name) <= 24 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-." for ch in name)
            or len(password) > 128 or ctx.session.login_subcommand not in (0, 1, 2, 3)):
        raise PacketDecodeError("invalid callsign or login fields")
    ctx.session.name = name
    ctx.session.supplied_password = password
    
    print(
        ">>> Login received via Dispatcher: "
        f"subcommand={ctx.session.login_subcommand} name={ctx.session.name}"
    )
    # Signal the main thread that we have the data
    ctx.session.login_received.set()

@dispatcher.route(0x4E)
def on_bps_request(ctx: TcpContext, payload: bytes):
    ctx.server.logger.log_packet("TCP-RECV", payload)
    if len(payload) >= 5:
        (requested_rate,) = struct.unpack(">I", payload[1:5])
        ctx.send(BpsReplyPacket(requested_rate))
    else:
        print("[WARN] Malformed BPS Request")

@dispatcher.route(0x39)
def on_want_updates(ctx: TcpContext, payload: bytes):
    ctx.server.logger.log_packet("TCP-RECV", payload)
    with ctx.session.world_lock:
        if (not ctx.session.is_logged_in or not ctx.session.world_announced
                or ctx.session.is_ready_for_updates or ctx.session.stop_ping_event.is_set()
                or ctx.session.world_change_event.is_set()
                or getattr(ctx.server, 'map_change_transition', None) is not None):
            return
        land = ctx.server.land
        print(">>> Client is ready for updates (0x39)")
        ctx.server.trace.state("WANT_UPDATES", player=ctx.session.player_id)
        ctx.send(CommMessagePacket(
            message_type=0, source_player_id=ctx.session.player_id, chat_scope_id=0, recepient_id=0,
            message=f"Welcome to {ctx.server.cfg.game.display_name}. {ctx.server.cfg.game.motd}"
        ))
        ctx.send(CommMessagePacket(
            message_type=0, source_player_id=ctx.session.player_id, chat_scope_id=0, recepient_id=0,
            message="Choose a team and click a friendly repair pad to deploy. /s help and /s score are available."
        ))
        snapshots = ctx.server.entities.get_snapshot_packets(
            sequence_num=get_ticks(), health=1.0, energy=1.0, viewer_team=ctx.session.team,
        )
        for snapshot in snapshots:
            ctx.send(snapshot)
        # Teardown can begin while this TCP worker sends its snapshot. The
        # replacement announcement waits for world_lock and rearms readiness.
        if (ctx.server.land is not land or getattr(ctx.server, 'map_change_transition', None) is not None
                or ctx.session.stop_ping_event.is_set()):
            return
        ctx.session.is_ready_for_updates = True
        ctx.server.trace.state("WORLD_SYNCED", player=ctx.session.player_id)
        ctx.server.hooks.world_ready(ctx)
        print(f">>> Snapshot sent. Client {ctx.session.name} is now SYNCED.")


def announce_world(ctx: TcpContext, *, initial: bool = False) -> None:
    """Use the same reliable map announcement for login and round changes."""
    with ctx.session.world_lock:
        ctx.session.world_change_event.clear()
        if (not ctx.session.is_logged_in or ctx.session.stop_ping_event.is_set()
                or (not initial and not ctx.session.world_announced)):
            return  # An unfinished login announces the current map itself.
        ctx.session.is_ready_for_updates = False
        ctx.session.world_announced = False
        ctx.send(WorldStatsPacket(map_name=ctx.server.current_map_name))
        if not ctx.session.stop_ping_event.is_set():
            ctx.session.world_announced = True

@dispatcher.route(0x4F)
def on_kudos(ctx: TcpContext, payload: bytes):
    ctx.server.logger.log_packet("TCP-RECV", payload)
    print(">>> !kudos (0x4F)")


@dispatcher.datagram_route(0x36)
@dispatcher.route(0x36)
def on_string_value(ctx: TcpContext | UdpContext, payload_or_reader: bytes | PacketReader):
    reader=PacketReader(payload_or_reader) if isinstance(payload_or_reader,bytes) else payload_or_reader
    if isinstance(payload_or_reader,bytes): reader.read_byte()
    kind=reader.read_int32()
    size=reader.read_int32()
    if not 0<=size<=4096: raise PacketDecodeError('Invalid STRING_VALUE size')
    raw=reader.read_bytes(size)
    if kind!=4 or not ctx.session or not ctx.session.is_logged_in:
        return
    if isinstance(ctx.session, ClientSession) and not ctx.session.request_rate.allow("stats"):
        return
    from wulfram_server.matches import player_stats_reply
    reply=player_stats_reply(ctx.server,raw)
    if reply is not None:
        ctx.send(reply)


# --- UDP Routes ---

def _read_bounded_count(
    reader: PacketReader,
    field_name: str,
    *,
    maximum: int = 256,
) -> int:
    count = reader.read_int32()
    if count < 0 or count > maximum:
        raise PacketDecodeError(f"invalid {field_name} {count}")
    return count


def _read_reliable_ordered_body(
    reader: PacketReader,
) -> tuple[int, int, PacketReader]:
    """Read the stream-3 [sequence][total length][body] wrapper."""
    sequence = reader.read_int16()
    packet_length = reader.read_int16()
    if packet_length < 5:
        raise PacketDecodeError(
            f"reliable packet length {packet_length} is smaller than its header"
        )
    body = PacketReader(reader.read_bytes(packet_length - 5))
    return sequence, packet_length, body


@dispatcher.datagram_route(0x00)
def on_debug_string(ctx: UdpContext, reader: PacketReader):
    string_length = reader.read_byte()
    raw_message = reader.read_bytes(string_length)
    msg = raw_message.decode('ascii', errors='ignore').strip('\x00')
    if ctx.server.cfg.debug.debug_packets:
        print(f"    > UDP DEBUG MSG: {msg!r}")


@dispatcher.datagram_route(0x02)
def on_ack(ctx: UdpContext, reader: PacketReader):
    subcommand = reader.read_byte()
    if subcommand == 0:
        reader.read_int32()  # Sender timestamp.
    elif subcommand == 1:
        reader.read_byte()   # Acknowledged opcode.
        reader.read_int16()  # Acknowledged sequence.
    elif subcommand == 2:
        reader.read_int32()  # Sender timestamp.
        reader.read_byte()   # Stream id.
        reader.read_int16()  # Stream sequence.
    else:
        raise PacketDecodeError(f"unknown D_ACK subcommand {subcommand}")

    if (
        ctx.session
        and subcommand == 0
        and ctx.session.d_handshake_sent_event.is_set()
    ):
        ctx.session.d_handshake_ack_event.set()
        ctx.server.trace.state(
            "D_HANDSHAKE_ACK_RECEIVED",
            player=ctx.session.player_id,
        )

@dispatcher.datagram_route(0x03)
def on_d_handshake(ctx: UdpContext, reader: PacketReader):
    """
    Handles the UDP Handshake.
    Payload: [0x03] [Time] [ConnID] [StreamCount] ...
    """
    packet_start = reader.position_bits - 8

    timestamp = reader.read_int32()
    conn_id = reader.read_int32()
    stream_count = _read_bounded_count(reader, "D_HANDSHAKE stream count")
    for _ in range(stream_count):
        reader.read_string()
        packet_id_count = _read_bounded_count(
            reader,
            "D_HANDSHAKE stream packet-id count",
        )
        for _ in range(packet_id_count):
            reader.read_int32()

    route_count = _read_bounded_count(reader, "D_HANDSHAKE route count", maximum=1024)
    for _ in range(route_count):
        reader.read_int32()  # Packet id.
        reader.read_int32()  # Stream id.

    ctx.server.logger.log_packet("RECV-UDP", reader.byte_slice(packet_start))

    if not ctx.session:
        print("[WARN] Ignored packet from unknown UDP source")
        return
    print(f"    > D_HANDSHAKE: Time={timestamp}, ID={conn_id}, Streams={stream_count}")
    ctx.server.trace.state(
        "D_HANDSHAKE_RECEIVED",
        player=ctx.session.player_id,
        connection_id=conn_id,
        stream_count=stream_count,
    )
    # 1. Send Handshake ACK (SubCmd 0)
    pkt = PacketWriter()
    pkt.write_byte(0) # SubCmd
    pkt.write_int32(get_ticks())
    acknowledgement = b'\x02' + pkt.get_bytes()
    if ctx.session.d_handshake_ack_event.is_set():
        # A delayed retry must not reset streams after the world is live.
        ctx.send(acknowledgement)
        return
    if ctx.session.udp_handshake_replies:
        for reply in ctx.session.udp_handshake_replies:
            ctx.send(reply)
        return
    replies = [acknowledgement]

    # 2. Send Our Handshake Definitions
    # (Simplified for brevity, full impl in original udp_handler)
    pkt_hs = PacketWriter()
    pkt_hs.write_int32(get_ticks()) # Server timestamp
    pkt_hs.write_int32(ctx.session.player_id) # Player ID?
    # --- STREAM DEFINITIONS ---
    # We define 4 streams to match the client's expectations
    pkt_hs.write_int32(4) # Def Count

    # Stream 0: Unreliable
    pkt_hs.write_string("Unreliable")
    pkt_hs.write_int32(1) # ID Count
    pkt_hs.write_int32(0) # ID

    # Stream 1: Reliable (Chat/Events)
    pkt_hs.write_string("Reliable")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(1)

    # Stream 2: Meta/Receipts
    pkt_hs.write_string("Stream 2")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(2)

    # Stream 3: Game Data (Movement)
    pkt_hs.write_string("Game Data")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(3)

    # --- STREAM CONFIGURATION ---
    # Set Priorities / Window Sizes
    pkt_hs.write_int32(4) # Config Count
    
    # [StreamID] [Priority]
    pkt_hs.write_int32(0); pkt_hs.write_int32(1)
    pkt_hs.write_int32(1); pkt_hs.write_int32(1)
    pkt_hs.write_int32(2); pkt_hs.write_int32(1)
    pkt_hs.write_int32(3); pkt_hs.write_int32(1)

    replies.append(b'\x03' + pkt_hs.get_bytes())
    # end handshake

    print("[UDP] Synchronizing Streams...")
    # 3. Unpause Streams (Critical for client to accept data)
    
    # Stream 1
    p1 = PacketWriter()
    p1.write_byte(1) # Stream Id
    p1.write_int16(1) # Sequence
    replies.append(b'\x04' + p1.get_bytes())

    # Stream 3
    p3 = PacketWriter()
    p3.write_byte(3) # Stream Id
    p3.write_int16(1) # Sequence
    replies.append(b'\x04' + p3.get_bytes())
    ctx.session.udp_handshake_replies = tuple(replies)
    # Publish the barrier before sending: an ACK can arrive as soon as the
    # peer sees the handshake, before the final stream record leaves us.
    ctx.session.d_handshake_sent_event.set()
    for reply in replies:
        ctx.send(reply)

@dispatcher.datagram_route(0x08)
def on_root_hello(ctx: UdpContext, reader: PacketReader):
    # Client confirms they heard our TCP "UDP Config" packet
    # This is just a UDP connectivity probe ("Hello There").
    # It contains no ID, so we cannot link it to a session yet.
    packet_start = reader.position_bits - 8
    reader.read_string()
    payload = reader.byte_slice(packet_start)
    ctx.server.logger.log_packet("UDP-RECV (ROOT-HELLO)", payload=payload, show_ascii=True)

@dispatcher.datagram_route(0x0B)
def on_client_ping_request(ctx: UdpContext, reader: PacketReader):
    """
    UDP Packet 0x0B: Client Pinging Server.
    The Client sends this to measure RTT. We must reply with 0x0C.
    """
    # 1. Read the timestamp the Client sent us
    client_ts = reader.read_int32()
    reader.read_int32()  # Input-feedback accumulator, cleared after send.
    
    # 2. Reply with 0x0C (Pong), echoing that timestamp exactly
    w = PacketWriter()
    w.write_int32(client_ts) # Doesn't seem to change the ping in the client no matter what this is set to?
    ctx.send(b'\x0C' + w.get_bytes())
    #print(f"    > Replying to Client Ping (Time: {client_ts})")

@dispatcher.datagram_route(0x0C)
def on_udp_ping(ctx: UdpContext, reader: PacketReader):
    """
    UDP Packet 0x0C: Client Replying to Server.
    This is the response to OUR 0x0B packet (sent via TCP/UDP).
    """
    # This is the timestamp WE sent originally (Server Time)
    server_ts = reader.read_int32()
    reader.read_int32()  # Input-feedback accumulator, cleared after send.

    # Calculate RTT for server logs
    rtt = get_ticks() - server_ts

    #print(f"    > Server Ping Confirmed. RTT: {rtt}ms")

    # Shouldn't have to echo it back here, since it's a PONG
    #w = PacketWriter()
    #w.write_int32(client_ts)
    #ctx.send(b'\x0C' + w.get_bytes())


@dispatcher.datagram_route(0x10)
def on_ack1(ctx: UdpContext, reader: PacketReader):
    """Consume the client's bit-packed ACK1 entity/sample table."""
    entity_count = reader.read_byte()
    for _ in range(entity_count):
        reader.read_int32()  # Entity net id.
        sample_count = reader.read_bits(3)
        for _ in range(sample_count):
            reader.read_int32()


@dispatcher.datagram_route(0x40)
def on_input_feedback(ctx: UdpContext, reader: PacketReader):
    """Consume the periodic input-feedback accumulator sent by the client."""
    reader.read_int32()


@dispatcher.datagram_route(0x33)
def on_ack2(ctx: UdpContext, reader: PacketReader):
    """ Packet 0x33: ACK2 (Response to Process Translation)
        Bytes: [StreamID:2] [SeqID:2] [Status:4]
        payload: [00 01] [00 09] [00 00 00 01]
        The client calls this "ACK2" in process_translation.
        It sends Int32(1) inside.
    """
    print("on_ack2")
    seq, length, body = _read_reliable_ordered_body(reader)
    status = body.read_int32() # Seems to always be 1

    print(f"    > RECV ACK2 (Seq {seq} | Len {length}) - Status: {status}")
    
    # Send ACK back to confirm receipt
    ctx.send_ack(packet_id=0x33, seq_num=seq)

@dispatcher.datagram_route(0x35)
def on_viewpoint(ctx: UdpContext, reader: PacketReader):
    """Viewpoint Info"""
    print("on_viewpoint")
    # Stream 1 is reliable-unordered: it carries a sequence but no length.
    seq = reader.read_int16()
    reader.read_int32()  # View entity net id, or -1.
    # Send ACK
    ctx.send_ack(packet_id=0x35, seq_num=seq)


@dispatcher.datagram_route(0x25)
def on_reincarnate(ctx: UdpContext, reader: PacketReader):
    """Spawn/Team Request"""
    seq, length, reader = _read_reliable_ordered_body(reader)
    mode = reader.read_byte()
    # Validate the complete retail body before acknowledging or remembering
    # its sequence. A malformed request must not consume a corrected retry.
    if mode not in (0, 1) or length != (14 if mode == 1 else 22):
        raise PacketDecodeError('invalid reincarnate mode or body length')
    is_team_switch = mode == 1
    # This is team_id if is_team_switch is 1 (true)
    # If is_team_switch is 0 (false) then it's the repair pad's net id
    team_id_or_repaid_pad = reader.read_int32()
    unit_id = reader.read_int32() # Tank or Scout
    
    # [Op] [Seq] [Len] [Data...]
    # Logic to spawn would go here
    
    if not ctx.accept_reliable_delivery(packet_id=0x25, seq_num=seq):
        return

    # Validate Session
    if not ctx.session:
        print("[WARN] Reincarnate request from sessionless UDP")
        return
    if not ctx.session.request_rate.allow("spawn"):
        ctx.send(ReincarnatePacket(code=4))
        return

    # Check if this is a team switch or spawn request
    if (not is_team_switch):
        unk_int3 = float(reader.read_int32()) # double/float, maybe x cord
        unk_int4 = float(reader.read_int32()) # double/float, maybe y cord

        if getattr(ctx.server, "map_change_transition", None) is not None:
            send_system_message(
                ctx,
                "Map change in progress; spawning is temporarily disabled.",
            )
            ctx.send(ReincarnatePacket(code=4))
            return

        if time.monotonic() < ctx.session.construction_ready_at:
            remaining = ctx.session.construction_ready_at - time.monotonic()
            send_system_message(ctx, f"Construction available in {remaining:.1f} seconds.")
            ctx.send(ReincarnatePacket(code=4))
            return

        current = ctx.session.entity
        if current is not None and current.is_manned and current.health_points > 0:
            # A retry or another pad click must not heal an active vehicle or
            # renew its spawn shield. Re-send its actual state instead.
            send_current_tank(ctx)
            ctx.send(ReincarnatePacket(code=11))
            return

        net_id = team_id_or_repaid_pad
        print(f"    > RECV REINCARNATE (SPAWN REQ): Unit ID: {unit_id} | net_id #{net_id}")
        print(f"    > Unknown values: {unk_int3} | {unk_int4}")

        if unit_id not in PLAYER_VEHICLE_UNIT_TYPES:
            send_system_message(ctx, "That vehicle cannot be selected.")
            ctx.send(ReincarnatePacket(code=4))
            return
        
        with ctx.server.bots.spawn_lock:
            # Find the selected entity (the repair pad they clicked on to spawn in)
            repair_pad = ctx.server.entities.get_entity(net_id)
            if (not repair_pad or repair_pad.unit_type != 27 or repair_pad.team_id != ctx.session.team
                    or ctx.session.team not in (1, 2) or repair_pad.health_points <= 0):
                send_system_message(ctx, "Can't find selected spawn point.")
                ctx.send(ReincarnatePacket(code=4)) # Can't enter yet. Game not ready.
                return

            selected_pad = repair_pad
            repair_pad = ctx.server.bots._spawn_pad(ctx.session.team, require_free=True, preferred_id=net_id)
            if repair_pad is None:
                # The bot loop checks pads every frame; a human retry arrives
                # much less often. Yield the next opening for a bounded window.
                ctx.session.spawn_request_until = time.monotonic()+2.5
                send_system_message(ctx, "Repair pads are busy. Try again; your deployment has priority.")
                ctx.send(ReincarnatePacket(code=4))
                return
            if repair_pad is not selected_pad:
                send_system_message(ctx, "Selected pad occupied; deploying at the nearest free friendly pad.")

            # 1. Create the Entity (Dynamic ID)
            # We DO NOT pass override_net_id, so EntityManager assigns a new unique ID.
            from wulfram_server.vehicles import LOADOUTS, chosen_loadout, apply_loadout
            loadout = chosen_loadout(ctx.session, unit_id)
            unit_id = LOADOUTS[loadout][0]
            new_entity = ctx.server.entities.create_entity(
                unit_type=unit_id,
                team_id=ctx.session.team,
                pos=repair_pad.pos,
                rot=repair_pad.rot,
                # Keep the entity out of the game-loop reconciliation until the
                # authoritative host can create and finalize its body under one
                # physics lock.
                is_manned=False,
                register=False,
            )

            apply_loadout(new_entity, loadout)
            # 2. Assign to Session
            # Remove old entity if exists
            if ctx.session.entity:
                ctx.server.hooks.entity_removed(ctx.session, "reincarnate")
                del_pkt = ctx.server.entities.remove_entity(ctx.session.entity.net_id)
                if del_pkt is not None: broadcast(ctx.server, del_pkt)

            ctx.session.entity = new_entity
            # The TankPacket's compact weapon-state tail is selected by this table
            # ID. Tank is table 0 and Scout is table 1; using table 0 for both only
            # appeared to work while the Tank table contained no enabled channels.
            ctx.session.entity.weapon_table_id = unit_id
            _note_entity_spawn(ctx.session, new_entity, "reincarnate")
            physics = getattr(ctx.server, "physics", None)
            if physics is not None:
                physics.finalize_spawn_pose(new_entity, ctx.server.land)
            else:
                new_entity.is_manned = True
            # Native authority registers under its physics lock. The idempotent
            # call also publishes non-native and unsupported vehicle spawns only
            # after their complete pose is ready.
            ctx.server.entities.register_entity(new_entity)
        ctx.session.construction_ready_at = 0.0
        ctx.session.spawn_request_until = 0.0

        # 3. Notify the Client
        send_system_message(
            ctx,
            f"{loadout.title()} deployed. Spawn shield: {SPAWN_PROTECTION_SECONDS:g} seconds; firing ends it.",
        )

        # 4. Send TankPacket with the NEW Dynamic ID
        # The client will receive this and now know "I am NetID X"
        _send_spawn_tank(ctx)
        # ProcessReincarnatePacket clears the client's pending-request flag on
        # every response; code 11 is the recovered "Request Granted" result.
        ctx.send(ReincarnatePacket(code=11))
        send_existing_player_entity_definitions(ctx, "reincarnate")
        
        # Associate the roster player with this newly spawned vehicle so
        # targeting and other player-facing HUD paths can show their identity.
        broadcast(ctx.server, BirthNoticePacket(
            player_id=ctx.session.player_id,
            entity_id=new_entity.net_id,
        ))

        return

    team_id = team_id_or_repaid_pad
    print(f"    > RECV REINCARNATE (TEAM SWITCH): Team : {team_id}")
    previous_team = ctx.session.team
    if team_id in (1, 2):
        if team_id != previous_team and sum(s.is_logged_in and s.team == team_id for s in ctx.server.sessions) >= ctx.server.packet_cfg.behavior.header.total_team_size:
            send_system_message(ctx, "That team is full. Choose the other team.")
            ctx.send(ReincarnatePacket(code=4))
            return
        # The original game treats an in-world team change as a death: remove
        # the old-team vehicle and return the player to the spawn lobby before
        # publishing their new roster team.
        if ctx.session.entity is not None:
            _destroy_authoritative_entity(
                ctx.server,
                ctx.session.entity,
                explosion=True,
                defer_player_removal=False,
            )
        ctx.session.team = team_id
        ctx.session.spawn_request_until = 0.0
        ctx.session.spawn_delivery = None
        from wulfram_server.matches import stats_packet
        broadcast(ctx.server, stats_packet(ctx.session))

    ctx.server.trace.state(
        "TEAM_JOINED",
        player=ctx.session.player_id,
        requested_team=team_id,
        effective_team=ctx.session.team,
    )
    
    # Sends message code about team switched successfully
    ctx.send(ReincarnatePacket(code=17))
    ctx.server.hooks.team_joined(ctx, previous_team, team_id)


@dispatcher.datagram_route(0x2B)
def on_drop_request(ctx: UdpContext, reader: PacketReader):
    """Handle the stock reliable DROP_REQUEST (0=drop, 1=deploy)."""
    # Live client packets are [opcode][sequence][total length][mode]. The
    # total length is 9 bytes: 1 opcode + 2 sequence + 2 length + 4 body.
    sequence, _length, body = _read_reliable_ordered_body(reader)
    mode = body.read_int32()
    if mode not in (0, 1):
        raise PacketDecodeError(f"invalid cargo drop mode {mode}")
    if not ctx.accept_reliable_delivery(packet_id=0x2B, seq_num=sequence):
        return
    if ctx.session is not None:
        _handle_cargo_request(ctx.server, ctx.session, deploy=mode == 1)


@dispatcher.datagram_route(0x19)
def on_tank_resend_request(ctx: UdpContext, reader: PacketReader):
    """Retry when retail received TANK but failed to create its local object."""
    # Stream 1 is reliable-unordered: this empty request carries only its
    # sequence number after the opcode. Losing the entire TANK does not trigger
    # this request, and receiving it does not prove successful deployment.
    sequence_num = reader.read_int16()
    ctx.send_ack(packet_id=0x19, seq_num=sequence_num)
    if ctx.session and ctx.session.request_rate.allow("tank_resend"):
        send_current_tank(ctx)
    ctx.server.hooks.tank_resend_requested(ctx, sequence_num)


def send_current_tank(ctx: UdpContext, *, expected_entity: GameEntity | None = None) -> None:
    """Send fresh native TANK state without recreating or restoring a vehicle."""
    entity = ctx.session.entity
    if (entity is None or not entity.is_manned or entity.health_points <= 0
            or (expected_entity is not None and entity is not expected_entity)):
        return
    # Preserve the retail TANK path and honor its native resend requests;
    # snapshots and lifecycle messages have separate delivery requirements.
    ctx.send(TankPacket(
        net_id=entity.net_id, sequence_id=get_ticks(), tank_cfg=ctx.server.packet_cfg.tank,
        team_id=entity.team_id, unit_type=entity.unit_type, pos=entity.pos, rot=entity.rot,
        weapon_table_id=entity.weapon_table_id, weapon_ready_mask=entity.weapon_ready_mask,
        pulse_charge=entity.pulse_charge, repair_charge=entity.repair_charge,
        health=entity.health, energy=entity.energy,
    ))


def _send_spawn_tank(ctx: UdpContext) -> None:
    """Arm bounded delivery before sending the first unacknowledged raw TANK."""
    now = time.monotonic()
    entity = ctx.session.entity
    ctx.session.spawn_delivery = PendingSpawnDelivery(
        entity=entity, input_sequence=ctx.session.physics_input_sequence,
        team=ctx.session.team, deadline=now+SPAWN_DELIVERY_TIMEOUT_SECONDS,
        retry_at=now+SPAWN_DELIVERY_RETRY_SECONDS,
    )
    send_current_tank(ctx, expected_entity=entity)


def _update_spawn_deliveries(server: WulframServerContext, now: float) -> None:
    """Repair whole-TANK loss without per-player workers or TCP gameplay."""
    for session in tuple(server.sessions):
        pending = getattr(session, "spawn_delivery", None)
        if pending is None:
            continue
        entity = pending.entity
        if (not session.is_logged_in or not session.is_ready_for_updates
                or session.udp_context is None or session.stop_ping_event.is_set()
                or getattr(server, "map_change_transition", None) is not None
                or session.entity is not entity or not entity.is_manned
                or entity.health_points <= 0 or session.team != pending.team
                or entity.team_id != pending.team
                or server.entities.get_entity(entity.net_id) is not entity
                or now >= pending.deadline):
            if session.spawn_delivery is pending:
                session.spawn_delivery = None
            continue
        if now >= pending.retry_at:
            pending.retry_at = now+SPAWN_DELIVERY_RETRY_SECONDS
            send_current_tank(session.udp_context, expected_entity=entity)


@dispatcher.datagram_route(0x20)
def on_chat_comm_req(ctx: UdpContext, reader: PacketReader):
    """
    Packet 0x20: CHAT / COMM REQUEST
    """
    sequence_num, payload_len, reader = _read_reliable_ordered_body(reader)
    if not ctx.session:
        print("[WARN] Ignored packet from unknown UDP source")
        return

    source_scope = reader.read_int16()
    unk_id = reader.read_int16()
    inc_message = reader.read_string()
    if not ctx.accept_reliable_delivery(packet_id=0x20, seq_num=sequence_num):
        return
    if (source_scope not in (0, 1, 4) or not 1 <= len(inc_message) <= 240
            or any(ord(ch) < 32 or ord(ch) > 126 for ch in inc_message)
            or not ctx.session.request_rate.allow("chat")):
        return

    if (source_scope == 1): # /s system message
        found = ctx.server.hooks.process_system_command(ctx, inc_message)
        
        if not found:
            send_system_message(ctx, "Unknown command.")
    else:
        broadcast_chat(
            server=ctx.server,
            message=inc_message,
            source_player_id=ctx.session.player_id,
            scope_id=source_scope
        )
        """ctx.send(CommMessagePacket(
            message_type=5,
            source_player_id=ctx.session.player_id, 
            chat_scope_id=source, 
            recepient_id=0, 
            message=inc_message
            ))"""
        
        #source = 5 # admin message
        #self.send_chat_message(addr, 5, ctx.server.cfg.player.player_id, source, 0, message)
        #testing spawn and such
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)
        #self.send_tank_packet(addr, net_id=ctx.server.cfg.player.player_id, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(0,0,0))
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)

@dispatcher.datagram_route(0x3A)
def on_beacon_request(ctx: UdpContext, reader: PacketReader):
    """
    Packet 0x3A: BEACON REQUEST
    """
    sequence_num, payload_len, reader = _read_reliable_ordered_body(reader)

    some_id = reader.read_int32()

# --- ACTION PARSING ---

ACTION_DUMP_IDS = range(1, 22)

ACTION_NAMES = {
    1: "Turn (raw; Tank negates)",
    2: "Forward",
    3: "Strafe (raw; Tank negates)",
    4: "Jump jets (server-authoritative binary edge)",
    5: "Jet strength",
    6: "Tilt",
    7: "Roll",
    8: "Autocannon",
    12: "Pulse shell",
}

def _read_action_value(reader: PacketReader, action_id: int) -> float:
    """
    Reads one action value using the independently recovered packet encoding.
    """
    if action_id not in ACTION_DUMP_IDS:
        raise PacketDecodeError("invalid action channel")
    if action_id >= 8 or action_id == 4:
        return 1.0 if reader.read_bits(1) else 0.0
    if action_id == 5:
        return reader.read_quantized_float(get_config_by_index(10))
    return reader.read_quantized_float(get_config_by_index(11))

def _client_id_for_action_log(ctx: UdpContext) -> int | str:
    if ctx.session:
        return ctx.session.player_id or "pending"
    return "unlinked"

def _debug_config_bool(ctx: UdpContext, name: str, default: bool = False) -> bool:
    server = getattr(ctx, "server", None)
    cfg = getattr(server, "cfg", None)
    debug = getattr(cfg, "debug", None)
    return bool(getattr(debug, name, default))

def _store_action_value(
    ctx: UdpContext,
    packet_type: str,
    action_id: int,
    value: float,
) -> tuple[float | None, float]:
    old_value = None
    if (
        ctx.session
        and ctx.session.entity
        and getattr(ctx.session.entity, "is_manned", True)
    ):
        old_value = ctx.session.entity.actions.get(action_id)
        # Zero is a real released/neutral state, not "ignore this action."
        ctx.session.entity.actions[action_id] = value

    if _debug_config_bool(ctx, "debug_actions"):
        print(
            "[ACTION] "
            f"client_id={_client_id_for_action_log(ctx)} "
            f"packet={packet_type} "
            f"action_id={action_id} "
            f"action_name=\"{ACTION_NAMES.get(action_id, f'Unknown_{action_id}')}\" "
            f"old_value={old_value} "
            f"new_value={value}"
        )
    return old_value, value

def parse_action_packet(ctx: UdpContext, reader: PacketReader, is_dump: bool):
    """
    Parses ACTION_DUMP (0x09) or ACTION_UPDATE (0x0A).

    ACTION_DUMP carries an implicit full table for action ids 1..21.
    ACTION_UPDATE carries a counted list of explicit action id/value pairs.
    See docs/ACTION_PACKET_SPEC.md.
    """
    opcode = 0x09 if is_dump else 0x0A
    packet_type = "ACTION_DUMP" if is_dump else "ACTION_UPDATE"
    action_values: list[tuple[int, float]] = []
    client_time_or_sequence = 0
    packet_time_or_flags = 0
    action_entity = ctx.session.entity if ctx.session else None
    pending_spawn = getattr(ctx.session, "spawn_delivery", None)

    if is_dump:
        dump_time_or_sequence = reader.read_int32()
        client_time_or_sequence = dump_time_or_sequence
        packet_time_or_flags = reader.read_int32()
        if _debug_config_bool(ctx, "debug_action_packets"):
            print(
                "[ACTION_PACKET] "
                f"client_id={_client_id_for_action_log(ctx)} "
                f"packet={packet_type} "
                f"opcode=0x{opcode:02X} "
                f"dump_time_or_sequence={dump_time_or_sequence} "
                f"packet_time_or_flags={packet_time_or_flags}"
            )
        action_ids = ACTION_DUMP_IDS
    else:
        count = reader.read_byte()
        first_action_time_or_sequence = reader.read_int32()
        client_time_or_sequence = first_action_time_or_sequence
        packet_time_or_flags = reader.read_int32()
        if _debug_config_bool(ctx, "debug_action_packets"):
            print(
                "[ACTION_PACKET] "
                f"client_id={_client_id_for_action_log(ctx)} "
                f"packet={packet_type} "
                f"opcode=0x{opcode:02X} "
                f"count={count} "
                f"first_action_time_or_sequence={first_action_time_or_sequence} "
                f"packet_time_or_flags={packet_time_or_flags}"
            )
        cfg_id_bits = get_config_by_index(15)
        action_ids = (
            reader.read_bits(cfg_id_bits.precision_header_bits)
            for _ in range(count)
        )

    for action_id in action_ids:
        value = _read_action_value(reader, action_id)
        action_values.append((action_id, value))
    reader.align_to_byte(require_zero_padding=True)

    # Do not partially change authoritative input state if a malformed packet
    # ends halfway through its action table.
    decoded_actions = []
    for action_id, value in action_values:
        old_value, new_value = _store_action_value(
            ctx,
            packet_type,
            action_id,
            value,
        )
        decoded_actions.append((action_id, old_value, new_value))

    if ctx.session:
        ctx.session.physics_input_sequence += 1
        entity = ctx.session.entity
        # Retail starts owner controls only after a TANK creates its local
        # player. A snapshot ACK or resend request cannot prove that transition.
        # Preserve a newer spawn if it replaced this one while decoding input.
        if (decoded_actions and pending_spawn is not None
                and ctx.session.spawn_delivery is pending_spawn
                and entity is action_entity is pending_spawn.entity
                and entity.is_manned and entity.health_points > 0
                and ctx.session.physics_input_sequence > pending_spawn.input_sequence):
            ctx.session.spawn_delivery = None
        jump_pressed = any(
            action_id == 4
            and (old_value is None or old_value == 0.0)
            and new_value != 0.0
            for action_id, old_value, new_value in decoded_actions
        )
        if (
            entity is not None
            and getattr(entity, "is_docked", False)
            and jump_pressed
            and ctx.server.hooks.ground_docking_enabled
        ):
            # Packet 0x38 put both the owner client and native body to sleep.
            # Wake that state before submitting channel 4 so the recreated
            # native entity can validate support on its next physics tick.
            _clear_ground_docked(
                ctx.server,
                ctx.session,
                rearm_for_jump=True,
            )
        if (
            entity is not None
            and getattr(entity, "is_manned", True)
            and not getattr(entity, "is_docked", False)
            and getattr(entity, "input_sequence", -1)
            < ctx.session.physics_input_sequence
        ):
            entity.record_input_sample(
                sequence=ctx.session.physics_input_sequence,
                client_time_or_sequence=client_time_or_sequence,
                client_flags=packet_time_or_flags,
            )

    return decoded_actions


@dispatcher.datagram_route(0x09)
def on_action_dump(ctx: UdpContext, reader: PacketReader):
    decoded_actions = parse_action_packet(ctx, reader, is_dump=True)
    ctx.server.hooks.action_packet(ctx, "ACTION_DUMP", 0x09, decoded_actions)

@dispatcher.datagram_route(0x0A)
def on_action_update(ctx: UdpContext, reader: PacketReader):
    decoded_actions = parse_action_packet(ctx, reader, is_dump=False)
    ctx.server.hooks.action_packet(ctx, "ACTION_UPDATE", 0x0A, decoded_actions)

# -------------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------------
def send_system_message(ctx: UdpContext | TcpContext, message: str, receipient_id: int = 0):
    ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=0, #ctx.server.cfg.player.player_id, 
                chat_scope_id=0, 
                recepient_id=receipient_id, 
                message=message
            ))
    
WORLD_ENTITY_OPCODES = frozenset((0x0D, 0x0E, 0x0F, 0x15, 0x18, 0x1D, 0x1E, 0x29, 0x38))


def broadcast(server: WulframServerContext, packet_data: bytes | Packet, exclude_session: ClientSession | None = None):
    """
    Generic broadcaster. Serializes a packet once and sends it to all logged-in players.
    """

    if isinstance(packet_data, Packet):
        payload = packet_data.serialize()
    else:
        payload = packet_data
    
    for session in tuple(server.sessions):
        # Skip not logged in or excluded sessions
        if not session.is_logged_in or session == exclude_session:
            continue
        # WORLD_STATS resets the original client's entity registry. Only its
        # subsequent WANT_UPDATES proves that the new world finished loading.
        if payload and payload[0] in WORLD_ENTITY_OPCODES and not session.is_ready_for_updates:
            continue
            
        try:
            if payload[:1] == b'\x16' and getattr(session, 'tcp_transport', None) is not None:
                # The existing per-client control worker sends the latest map.
                # One coalescing event bounds memory and keeps slow TCP writes
                # (or an in-flight snapshot) out of the simulation thread.
                session.world_change_event.set()
            elif session.udp_context:
                session.udp_context.send(payload)
        except Exception as e:
            print(f"[Broadcast] Error sending to {session.name}: {e}")

def broadcast_chat(server: WulframServerContext, message: str, source_player_id: int, scope_id: int):
    """
    Sends a CommMessagePacket to all connected players (including the sender).
    """
    source = next((s for s in server.sessions if s.player_id == source_player_id), None)
    if source is None or not source.is_logged_in:
        return
    packet = CommMessagePacket(
        message_type=5, # 5 = User Chat? (0=System, 1=?, 5=Chat)
        source_player_id=source_player_id, 
        chat_scope_id=scope_id, 
        recepient_id=0, 
        message=message
    )
    
    encoded = packet.serialize()
    
    count = 0
    for session in server.sessions:
        # Only send to players who are fully logged in
        if not session.is_logged_in:
            continue
        if scope_id == 4 and (source.team not in (1, 2) or session.team != source.team):
            continue
            
        # Prefer UDP for chat (Reliable Stream 1), fallback to TCP if necessary
        try:
            if session.udp_context:
                # We reuse the raw byte payload to avoid re-serializing 50 times
                # Note: UdpContext.send handles framing
                session.udp_context.send(encoded)
                count += 1
        except Exception as e:
            print(f"[Broadcast] Failed to send to {session.name}: {e}")
            
    print(f"[Chat] Broadcasted to {count} players.")

def map_state_path(server: WulframServerContext, map_name: str) -> Path:
    return server.content_root / "shared" / "data" / "maps" / map_name / "state"


def map_land_path(server: WulframServerContext, map_name: str) -> Path:
    return server.content_root / "shared" / "data" / "maps" / map_name / "land"


def verify_map_state_exists(server: WulframServerContext, map_name: str) -> bool:
    return map_state_path(server, map_name).is_file()


def verify_map_land_exists(server: WulframServerContext, map_name: str) -> bool:
    return map_land_path(server, map_name).is_file()


def load_map_state(
    server: WulframServerContext,
    map_name: str,
    *,
    notification_context: TcpContext | UdpContext | None = None,
) -> bool:
    path = map_state_path(server, map_name)
    if path.is_file():
        try:
            data = path.read_text(encoding="utf-8")
            MapLoader(server.entities).load_from_string(data)
        except (OSError, UnicodeError, ValueError) as error:
            print(f"Failed to load map: {error}")
            if notification_context is not None:
                send_system_message(notification_context, "Error loading map.")
            return False
        message = f"Loaded map state: {map_name}"
    else:
        land = map_land_path(server, map_name)
        if not land.is_file():
            if notification_context is not None:
                send_system_message(
                    notification_context,
                    f"Could not find map land file at: {land}",
                )
            print(f"[MapLoader] Land file not found: {land}")
            return False
        message = f"Map {map_name} has no state file; loaded terrain only."
        print(f"[MapLoader] {message}")

    if notification_context is not None:
        send_system_message(notification_context, message)
    # Loading server content must not send an unsolicited VIEW_UPDATE. A UDP
    # snapshot can overtake WORLD_STATS and reach an uninitialized client world.
    # on_want_updates sends the first snapshot after the client's load completes.
    return True

# -------------------------------------------------------------------------
# BOOTSTRAP LOGIC
# -------------------------------------------------------------------------

def resolve_advertised_udp_host(client_sock: socket.socket, ctx: TcpContext) -> str:
    configured_host = (ctx.server.cfg.network.server_ip or "").strip()
    if configured_host.lower() not in ("", "auto", "0.0.0.0", "::"):
        _warn_if_loopback_advertised_to_remote(configured_host, ctx)
        return configured_host

    try:
        local_host = client_sock.getsockname()[0]
    except OSError:
        local_host = ""

    if not local_host or local_host in ("0.0.0.0", "::"):
        local_host = ctx.server.cfg.network.host

    if not local_host or local_host in ("0.0.0.0", "::"):
        local_host = "127.0.0.1"

    print(
        "[INFO] Auto UDP advertise host "
        f"client={ctx.session.address[0]} local_socket={local_host} configured={configured_host or 'auto'}"
    )
    return local_host


def _warn_if_loopback_advertised_to_remote(configured_host: str, ctx: TcpContext) -> None:
    try:
        advertised = ipaddress.ip_address(configured_host)
        client_ip = ipaddress.ip_address(ctx.session.address[0])
    except ValueError:
        return

    if advertised.is_loopback and not client_ip.is_loopback:
        print(
            "[WARN] network.server_ip is loopback but client is remote; "
            f"client={client_ip} advertised_udp_host={advertised}. "
            "Use server_ip=\"auto\" or your LAN/Tailscale address."
        )

def do_login_and_bootstrap(client_sock: socket.socket, ctx: TcpContext, dispatcher: PacketDispatcher):
    """
    Handles the initial sequence: Hello -> UDP Link -> Login -> World Entry.
    """
    # Clear the barrier before advertising the key. A localhost/headless client
    # can echo it before send() returns; clearing afterward would erase a valid
    # link and leave the TCP bootstrap waiting for fifteen seconds.
    ctx.session.key_echoed_event.clear()

    # 1. Send UDP Config (Hello Sub 1)
    print(f"[INFO] Setting session {ctx.session.address} to WAIT for UDP...")
    advertised_udp_host = resolve_advertised_udp_host(client_sock, ctx)
    print(
        "[INFO] Advertising UDP endpoint "
        f"{advertised_udp_host}:{ctx.server.cfg.network.udp_port} to {ctx.session.address}"
    )
    
    # This let's the client know which ip and port to connect to with UDP
    ctx.send(HelloPacket.create_udp_config(
        port=ctx.server.cfg.network.udp_port, 
        host=advertised_udp_host
    ))

    # 2. Send session key to the client
    # The client will then send the session key to the UDP connection
    ctx.send(HelloPacket.create_key(ctx.session.session_key))

    # 3. The Key Exchange Loop
    # We're waiting for the client to send the session key via UDP
    print(">>> Waiting for Client Key Exchange...")
    if (ctx.session.key_echoed_event.wait(timeout=15.0) and ctx.session.udp_context is not None
            and not ctx.session.stop_ping_event.is_set()):
        print(">>> Session key was successfully sent via UDP!")
        # And we have now sent IdentifiedUdpPacket
    else:
        raise ConnectionError("UDP session key exchange timed out")

    # --- Login Flow ---
    print(">>> Waiting for username (LOGIN 0x21)...")
    
    # Allow a new player time to read the guide and enter a callsign. The
    # absolute deadline and pending-connection limits still bound idle peers.
    login_deadline = time.monotonic() + 120.0
    
    for attempt in range(5):
        while not ctx.session.login_received.is_set():
            payload = ctx.transport.recv_payload(deadline=login_deadline)
            if not payload or not ctx.session.tcp_rate.allow():
                raise ConnectionError("Login connection closed or rate exceeded")
            dispatcher.dispatch_payload(ctx, payload)

        if ctx.session.login_subcommand != 3:
            ctx.send(LoginStatusPacket(code=1, is_donor=True))
            ctx.session.login_received.clear()
            while not ctx.session.login_received.is_set():
                payload = ctx.transport.recv_payload(deadline=login_deadline)
                if not payload or not ctx.session.tcp_rate.allow():
                    raise ConnectionError("Password connection closed or rate exceeded")
                dispatcher.dispatch_payload(ctx, payload)

        if ctx.session.stop_ping_event.is_set():
            raise ConnectionError("Login connection closed")
        accepted = ctx.server.hooks.authenticate(ctx.session)
        ctx.session.supplied_password = ""
        if accepted:
            break
        # Retail ProcessLoginStatus (0x4617f0), jump-table entry 6, displays
        # "Invalid password specified. Try again." and reopens login.
        ctx.send(LoginStatusPacket(code=6, is_donor=True))
        ctx.session.login_received.clear()
        print(f"[login] password rejected; retry={attempt + 1}")
    else:
        raise PermissionError("Login attempt limit reached")

    with ctx.server._login_lock:
        if any(s is not ctx.session and s.is_logged_in and s.name.casefold() == ctx.session.name.casefold()
               for s in ctx.server.sessions):
            raise PermissionError("That callsign is already connected")
        ctx.session.player_id = ctx.server.get_next_player_id()
        ctx.session.team = 0
        ctx.session.is_logged_in = True
    print(f">>> Login Complete! Assigned Player ID: {ctx.session.player_id}")
    ctx.server.hooks.login_accepted(ctx.server, ctx.session)
    ctx.server.trace.state(
        "LOGIN_ACCEPTED",
        player=ctx.session.player_id,
        login_subcommand=ctx.session.login_subcommand,
    )

    # NOW we send Verified (Hello Sub 3)
    # This tells the client: "UDP is good, Key is good, we're now logged in."
    print(">>> Key Verified. Sending 'Hello Verified' (Sub 3).")

    # Send via UDP if linked, otherwise fallback to TCP
    if ctx.session.udp_context:
        print("    > Sending via UDP (Preferred)")
        ctx.session.udp_context.send(HelloPacket.create_verified())
    else:
        print("    > Sending via TCP (Fallback)")
        ctx.send(HelloPacket.create_verified())

    # The client responds to HELLO verified with ROOT + D_HANDSHAKE. Wait for
    # its acknowledgement of our D_HANDSHAKE before sending world state over
    # TCP; otherwise the independent transport threads can reorder bootstrap
    # ahead of transport readiness and crash the canonical client.
    handshake_deadline = time.monotonic() + 8.0
    while not ctx.session.d_handshake_ack_event.wait(timeout=.5):
        if time.monotonic() >= handshake_deadline or ctx.session.stop_ping_event.is_set():
            raise ConnectionError("UDP D_HANDSHAKE acknowledgement timed out")
        # Both HELLO verified and the stream handshake travel over UDP. Keep
        # the bounded bootstrap alive when either direction loses a datagram.
        replies = ctx.session.udp_handshake_replies or (HelloPacket.create_verified().serialize(),)
        for reply in replies:
            ctx.session.udp_context.send(reply)
    if ctx.session.stop_ping_event.is_set():
        raise ConnectionError("Login connection closed")
    ctx.server.trace.state(
        "UDP_TRANSPORT_READY",
        player=ctx.session.player_id,
    )

    ctx.send(TeamInfoPacket())
    # TEAM_INFO initializes pointers consumed by LOGIN_STATUS code 8 when the
    # client was launched with -side. Preserve packet order and also give the
    # client one scheduler slice to finish that initialization before the
    # dependent status packet arrives.
    time.sleep(0.5)
    ctx.send(LoginStatusPacket(code=8, is_donor=True))
    ctx.send(PlayerInfoPacket(ctx.session.player_id, False))
    ctx.send(GameClockPacket())
    ctx.send(MotdPacket(ctx.server.cfg.game.motd))
    ctx.send(BehaviorPacket(
        ctx.server.packet_cfg.behavior,
        ctx.server.packet_cfg.combat,
        ctx.server.packet_cfg.jet_layout_profile,
    ))

    print("[SEND] TRANSLATION (0x32) - Configuration Compression Table...")
    ctx.send(TranslationPacket())
    
    # --- ROSTER SYNC ---
    
    # 1. Create the Roster Packet for THIS new player
    from wulfram_server.matches import score_for, stats_packet
    my_score = score_for(ctx.session)
    my_roster_pkt = AddToRosterPacket(
        account_id=ctx.session.player_id,
        name=ctx.session.name,
        nametag=ctx.server.cfg.player.nametag,
        team=ctx.session.team,
        total_kills=my_score.total_kills,
        total_deaths=my_score.total_deaths,
    )

    # 2. Tell ME about MYSELF (so I see myself in the list)
    ctx.send(my_roster_pkt)
    ctx.send(stats_packet(ctx.session))

    # 3. Tell EVERYONE ELSE about ME
    broadcast(ctx.server, my_roster_pkt, exclude_session=ctx.session)

    # 4. Tell ME about EVERYONE ELSE (Catch up on existing players)
    for other_session in ctx.server.sessions:
        if other_session.is_logged_in and other_session != ctx.session:
            other_score = score_for(other_session)
            # Create a packet for the existing player
            other_pkt = AddToRosterPacket(
                account_id=other_session.player_id,
                name=other_session.name,
                nametag=ctx.server.cfg.player.nametag,
                team=other_session.team,
                total_kills=other_score.total_kills,
                total_deaths=other_score.total_deaths,
            )
            print(f"Me: {ctx.session.player_id} | Team: {ctx.session.team} | Other player: {other_session.player_id} | Team: {other_session.team}")
            # Send it to the NEW player (ctx)
            ctx.send(other_pkt)
            ctx.send(stats_packet(other_session))

    if (not ctx.server.first_map_load):
        if not load_map_state(ctx.server, ctx.server.current_map_name):
            raise RuntimeError(
                f"could not load map state {ctx.server.current_map_name!r}"
            )
        ctx.server.land.load(map_land_path(ctx.server, ctx.server.current_map_name))
        ctx.server.first_map_load = True

    announce_world(ctx, initial=True)
    start_ping_loop(ctx)
