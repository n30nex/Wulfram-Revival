"""Real TCP/UDP bootstrap with CPU roster entries; no native assets needed."""
from dataclasses import replace
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.hooks import ServerHooks
from wulfram_server.network.packets.packet_config import PacketConfig
from wulfram_server.network.streams import PacketReader, PacketWriter
from wulfram_server.network.transport.tcp_transport import TcpTransport
from wulfram_server.network.transport.udp_transport import UdpTransport


class NetworkTestHooks(ServerHooks):
    authoritative_physics_enabled = False

    def __init__(self):
        self.world_synced = threading.Event()

    def authenticate(self, session):
        return session.supplied_password == "player"

    def world_ready(self, context):
        self.world_synced.set()


class BotHandshakeTests(unittest.TestCase):
    def test_human_bootstrap_after_four_bots(self):
        config = Config()
        config = replace(config, network=replace(config.network, host="127.0.0.1", server_ip="127.0.0.1"))
        hooks = NetworkTestHooks()
        server = app.WulframServerContext(
            config,
            PacketConfig.load(str(ROOT / "server/wulfram_server/content/packets.toml")),
            content_root=ROOT / "server/wulfram_server/content", hooks=hooks,
        )
        server.first_map_load = True
        for index, team in enumerate((1, 2, 1, 2)):
            server.entities.create_entity(27, team, (index * 100.0, 0.0, 0.0))
            server.bots.add(team=team)
        server.udp_sock.bind(("127.0.0.1", 0))
        server.udp_sock.settimeout(3)
        server.cfg = replace(config, network=replace(config.network, udp_port=server.udp_sock.getsockname()[1]))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            client = socket.create_connection(listener.getsockname(), timeout=3)
            peer, client_address = listener.accept()
        udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_client.bind(("127.0.0.1", 0))
        udp_client.settimeout(3)
        client.settimeout(3)
        session = app.ClientSession(server, peer, client_address)
        server.sessions.append(session)
        worker = threading.Thread(target=server._handle_tcp_client, args=(session,), daemon=True)
        transport = TcpTransport(client)
        context = app.UdpContext(UdpTransport(server.udp_sock), udp_client.getsockname(), server)

        def dispatch_udp(payload):
            udp_client.sendto(payload, server.udp_sock.getsockname())
            actual, address = server.udp_sock.recvfrom(65535)
            self.assertEqual(address, context.addr)
            app.dispatcher.dispatch_datagram(context, actual)

        def echo_key(key):
            writer = PacketWriter()
            writer.write_string(key)
            dispatch_udp(b"\x13\x01" + writer.get_bytes())

        try:
            worker.start()
            self.assertTrue(transport.recv_payload().startswith(b"\x13\x01"))
            key_packet = transport.recv_payload()
            self.assertEqual(key_packet[:2], b"\x13\x02")
            key = PacketReader(key_packet[2:]).read_string()
            echo_key("unknown-key")
            self.assertIsNone(context.session)
            self.assertFalse(session.key_echoed_event.is_set())
            echo_key(key)
            self.assertEqual(udp_client.recv(65535), b"\x4d")
            self.assertIs(context.session, session)
            self.assertIs(session.udp_context, context)
            self.assertTrue(session.key_echoed_event.is_set())

            login = PacketWriter()
            login.write_byte(3)
            login.write_string("Human Player")
            login.write_string("player")
            # An early/malicious readiness request cannot bypass world loading.
            transport.send_payload(b"\x39\x01")
            bad_login = PacketWriter()
            bad_login.write_byte(3)
            bad_login.write_string("Human Player")
            bad_login.write_string("wrong")
            transport.send_payload(b"\x21" + bad_login.get_bytes())
            self.assertEqual(transport.recv_payload(), b"\x22\x01\x06")
            self.assertFalse(session.is_logged_in)
            self.assertEqual(session.supplied_password, "")
            # Retry the manual callsign/password flow on the same connection.
            callsign = PacketWriter()
            callsign.write_byte(1)
            callsign.write_string("Human Player")
            callsign.write_string("")
            transport.send_payload(b"\x21" + callsign.get_bytes())
            self.assertEqual(transport.recv_payload(), b"\x22\x01\x01")
            transport.send_payload(b"\x21" + login.get_bytes())
            self.assertEqual(udp_client.recv(65535), b"\x13\x03")
            # Drop the first HELLO verified. The server must retry without a
            # fresh TCP connection or duplicate authentication side effects.
            self.assertEqual(udp_client.recv(65535), b"\x13\x03")
            root = PacketWriter()
            root.write_string("Hello There")
            dispatch_udp(b"\x08" + root.get_bytes() + b"\x03" + struct.pack(">IIII", 123, 1, 0, 0))
            replies = [udp_client.recv(65535)[0] for _ in range(4)]
            self.assertEqual(replies, [0x02, 0x03, 0x04, 0x04])
            # Drop the first entire handshake burst, including stream setup.
            retries = [udp_client.recv(65535)[0] for _ in range(4)]
            self.assertEqual(retries, replies)
            dispatch_udp(b"\x02\x00" + struct.pack(">I", 124))
            self.assertTrue(session.d_handshake_ack_event.is_set())

            packets = []
            while not packets or packets[-1][0] != 0x16:
                packets.append(transport.recv_payload())
            self.assertNotIn(0x0F, [payload[0] for payload in packets])
            roster = [payload for payload in packets if payload[0] == 0x1A]
            self.assertEqual(len(roster), 5)
            for bot in server.bots.bots:
                self.assertTrue(any(bot.name.encode() in payload for payload in roster))
                self.assertIsNone(bot.udp_context)
            self.assertTrue(session.is_logged_in)
            transport.send_payload(b"\x39\x01")
            self.assertTrue(hooks.world_synced.wait(3))
            self.assertTrue(session.is_ready_for_updates)
            dispatch_udp(b"\x03" + struct.pack(">IIII", 123, 1, 0, 0))
            self.assertTrue(session.d_handshake_ack_event.is_set())
            self.assertTrue(session.is_ready_for_updates)
            self.assertEqual(udp_client.recv(65535)[:2], b"\x02\x00")
            session.team = 1
            free_pad = server.entities.create_entity(27, 1, (400.0, 0.0, 0.0))
            # The first pad is occupied by a bot. Exercise the real UDP route,
            # not only the selector, and verify a second request cannot stack
            # another vehicle when every friendly pad is occupied.
            dispatch_udp(b"\x25" + struct.pack(">HHBiiii", 1, 22, 0, 1, 0, 2000, 700))
            vehicle = session.entity
            self.assertIsNotNone(vehicle)
            self.assertEqual(vehicle.pos, free_pad.pos)
            self.assertEqual(vehicle.health, 1.0)
            vehicle.spawn_protection_remaining = 2
            vehicle.set_health_points(47)
            vehicle.energy = .38
            another_pad = server.entities.create_entity(27, 1, (600.0, 0.0, 0.0))
            dispatch_udp(b"\x25" + struct.pack(">HHBiiii", 2, 22, 0, another_pad.net_id, 0, 2000, 700))
            self.assertIs(session.entity, vehicle)
            self.assertEqual(vehicle.health_points, 47)
            self.assertEqual(vehicle.energy, .38)
            self.assertEqual(vehicle.spawn_protection_remaining, 2)
            dispatch_udp(b"\x25" + struct.pack(">HHBiiii", 3, 22, 0, 1, 0, 2000, 700))
            self.assertIs(session.entity, vehicle)
        finally:
            session.key_echoed_event.set()
            session.login_received.set()
            session.d_handshake_ack_event.set()
            session.stop_ping_event.set()
            client.close()
            worker.join(timeout=3)
            peer.close()
            udp_client.close()
            server.tcp_sock.close()
            server.udp_sock.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(server.sessions), 4)


if __name__ == "__main__":
    unittest.main()
