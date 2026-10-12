"""Public connection regressions; real sockets, no game assets or live traffic."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import random
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.directory_query import TCP_QUERY_MAGIC, try_tcp_query
from wulfram_server.hooks import ServerHooks
from wulfram_server.hooks import ProductionHooks
from wulfram_server.network.limits import RateLimit
from wulfram_server.network.packets.packet_config import PacketConfig
from wulfram_server.network.streams import PacketDecodeError, PacketWriter
from wulfram_server.network.transport.tcp_transport import TcpTransport


class NetworkBoundaryTests(unittest.TestCase):
    def setUp(self):
        hooks = ServerHooks()
        hooks.authoritative_physics_enabled = False
        self.server = app.WulframServerContext(Config(), PacketConfig(), content_root=ROOT, hooks=hooks)
        self.server.udp_transport = Mock()
        self.addCleanup(self.server.tcp_sock.close)
        self.addCleanup(self.server.udp_sock.close)

    def session(self, address=("127.0.0.1", 30000)):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        session = app.ClientSession(self.server, left, address)
        self.server.sessions.append(session)
        return session

    @staticmethod
    def key_packet(key):
        packet = PacketWriter()
        packet.write_string(key)
        return b"\x13\x01" + packet.get_bytes()

    def test_unverified_udp_has_no_persistent_state_or_amplified_reply(self):
        rng = random.Random(281)
        with redirect_stdout(StringIO()):
            for port in range(10000, 12000):
                data = bytes([rng.randrange(256)]) + rng.randbytes(rng.randrange(60))
                try:
                    self.server._receive_datagram(data, ("127.0.0.1", port))
                except PacketDecodeError:
                    pass
        self.assertEqual(self.server.udp_sessions, {})
        self.server.udp_transport.send.assert_not_called()

    def test_verified_udp_is_source_bound_and_removed_on_disconnect(self):
        session = self.session()
        key = self.key_packet(session.session_key)
        self.assertGreaterEqual(len(session.session_key), 24)
        self.server._receive_datagram(key, ("127.0.0.2", 40000))
        self.assertFalse(session.key_echoed_event.is_set())
        self.server._receive_datagram(key, ("127.0.0.1", 40000))
        context = session.udp_context
        self.assertIsNotNone(context)
        self.server._receive_datagram(key, ("127.0.0.1", 40001))
        self.assertIs(session.udp_context, context)
        self.assertEqual(len(self.server.udp_sessions), 1)
        session.cleanup()
        session.cleanup()
        self.assertIsNone(context.session)
        self.server._receive_datagram(key, ("127.0.0.1", 40000))
        self.assertEqual(self.server.udp_sessions, {})

    def test_key_link_does_not_authorize_gameplay_or_rename_after_login(self):
        session = self.session()
        self.server._receive_datagram(self.key_packet(session.session_key), ("127.0.0.1", 40000))
        team_change = b"\x25" + struct.pack(">HHBii", 1, 14, 1, 1, 0)
        app.dispatcher.dispatch_datagram(session.udp_context, team_change)
        self.assertEqual(session.team, 0)
        session.is_logged_in = True
        session.name = "Pilot"
        packet = PacketWriter()
        packet.write_byte(3)
        packet.write_string("Someone Else")
        packet.write_string("player")
        ctx = app.TcpContext(Mock(), self.server, session)
        app.dispatcher.dispatch_payload(ctx, b"\x21" + packet.get_bytes())
        self.assertEqual(session.name, "Pilot")

    def test_invalid_callsigns_cannot_enter_roster_markup_or_logs(self):
        session = self.session()
        ctx = app.TcpContext(Mock(), self.server, session)
        for name in ("", "A" * 25, "<font color=red>", "Log\nInjection"):
            writer = PacketWriter()
            writer.write_byte(3)
            writer.write_string(name)
            writer.write_string("player")
            with self.subTest(name=name), self.assertRaises(PacketDecodeError):
                app.on_login_request(ctx, b"\x21" + writer.get_bytes())
        self.assertEqual(session.name, "Unknown")

    def test_partial_tcp_headers_and_bodies_have_absolute_deadlines(self):
        for wire in (b"\x00", b"\x00\x20\x13", b"\x00\x01", b"\xff\xff"):
            with self.subTest(wire=wire):
                left, right = socket.socketpair()
                try:
                    transport = TcpTransport(left)
                    right.sendall(wire)
                    start = time.monotonic()
                    with self.assertRaises((TimeoutError, ValueError)):
                        transport.recv_payload(deadline=start + .05)
                    self.assertLess(time.monotonic() - start, .5)
                finally:
                    left.close()
                    right.close()

    def test_slow_directory_query_is_closed_without_escaping_listener(self):
        left, right = socket.socketpair()
        try:
            right.sendall(TCP_QUERY_MAGIC)
            self.assertTrue(try_tcp_query(left, self.server.instance_id, timeout=.03))
        finally:
            left.close()
            right.close()

    def test_concurrent_tcp_writers_preserve_frames(self):
        left, right = socket.socketpair()
        try:
            transport, receiver = TcpTransport(left), TcpTransport(right)
            payloads = [bytes([value]) * 100 for value in range(1, 5)]
            workers = [threading.Thread(target=transport.send_payload, args=(payload,)) for payload in payloads]
            for worker in workers:
                worker.start()
            actual = [receiver.recv_payload(deadline=time.monotonic()+1) for _ in payloads]
            for worker in workers:
                worker.join(1)
            self.assertCountEqual(actual, payloads)
        finally:
            left.close()
            right.close()

    def test_rate_limit_memory_and_expiry_are_bounded(self):
        limit = RateLimit(2, 1, keys=2)
        self.assertTrue(limit.allow("one", now=0))
        self.assertTrue(limit.allow("one", now=0))
        self.assertFalse(limit.allow("one", now=0))
        self.assertTrue(limit.allow("two", now=0))
        for key in range(1000):
            self.assertFalse(limit.allow(key, now=0))
        self.assertEqual(len(limit.windows), 2)
        self.assertTrue(limit.allow("new", now=1))
        self.assertEqual(len(limit.windows), 1)

    def test_authenticated_malformed_datagrams_do_not_escape_parser_errors(self):
        session = self.session()
        self.server._receive_datagram(self.key_packet(session.session_key), ("127.0.0.1", 40000))
        session.is_logged_in = session.is_ready_for_updates = True
        rng = random.Random(91)
        with redirect_stdout(StringIO()):
            for opcode in app.dispatcher._datagram_handlers:
                for _ in range(30):
                    data = bytes([opcode]) + rng.randbytes(rng.randrange(60))
                    try:
                        app.dispatcher.dispatch_datagram(session.udp_context, data)
                    except PacketDecodeError:
                        pass

    def test_game_loop_failure_requests_a_supervisor_restart(self):
        with patch.object(app, "global_game_loop", side_effect=RuntimeError("test fault")):
            self.server._run_game_loop()
        self.assertTrue(self.server.stop_event.is_set())
        self.assertIsNotNone(self.server.fatal_error)

    def test_admin_credential_cannot_authorize_an_internet_peer(self):
        hooks = ProductionHooks(Config(), {"WULFRAM_SERVER_PASSWORD":"join", "WULFRAM_SERVER_ADMIN_PASSWORD":"admin"})
        for address, password, accepted, admin in (
            ("8.8.8.8", "admin", False, False), ("8.8.8.8", "join", True, False),
            ("192.168.0.10", "admin", True, True), ("127.0.0.1", "admin", True, True)):
            session = self.session((address, 30000))
            session.supplied_password = password
            self.assertEqual(hooks.authenticate(session), accepted)
            self.assertEqual(session.is_admin, admin)
            self.assertEqual(session.supplied_password, "")

    def test_team_chat_stays_on_the_senders_team(self):
        for player_id, team in enumerate((1, 1, 2), 1):
            session = self.session()
            session.player_id, session.team, session.is_logged_in = player_id, team, True
            session.udp_context = Mock()
        app.broadcast_chat(self.server, "Defend our pad", 1, 4)
        for session in self.server.sessions:
            self.assertEqual(session.udp_context.send.call_count, int(session.team == 1))


if __name__ == "__main__":
    unittest.main()
