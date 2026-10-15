"""Native generations and reliable control, without changing retail traffic."""
import struct
import threading
import time
import unittest
from types import MethodType
from unittest.mock import Mock, patch
from test_bots import make_server
from wulfram_server import application as app
from wulfram_server.network import native_world as native
from wulfram_server.network.packets.gameplay import DeleteObjectPacket
from wulfram_server.network.streams import PacketDecodeError, PacketWriter
from wulfram_server.network.translation_config import COMBAT_EVENT_HELLO


class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.server.world_identity = (3, 'crossroads')
        self.server.current_map_name = 'crossroads'
        self.server.trace = Mock()
        self.server.logger = Mock()
        self.server.allow_packet = MethodType(app.WulframServerContext.allow_packet, self.server)
        self.session = app.ClientSession(self.server, Mock(), ('127.0.0.1', 12345))
        self.server.sessions = [self.session]
        self.session.player_id = 100
        self.session.is_logged_in = self.session.is_ready_for_updates = True
        self.session.native_lifecycle = True
        self.session.native_generation = 1
        self.session.native_announced_epoch = 3
        self.session.entity = self.server.entities.create_entity(0, 1)
        self.udp = app.UdpContext(Mock(), ('127.0.0.1', 12346), self.server, self.session)
        self.session.udp_context = self.udp
        self.tcp = app.TcpContext(Mock(), self.server, self.session)

    def test_scope_size_truncation_nested_and_serial_wrap(self):
        body = b'\x0a\x00'
        encoded = native.encode(body, 3, 42, 7, connection=1)
        self.assertEqual(encoded, struct.pack('>BQIIIH', 0x50, 1, 3, 42, 7, 2)+body)
        self.assertEqual(native.decode(encoded), (1, 3, 42, 7, body))
        for length in range(len(encoded)):
            with self.assertRaises(PacketDecodeError): native.decode(encoded[:length])
        with self.assertRaises(PacketDecodeError): native.decode(encoded+b'\x00')
        with self.assertRaises(ValueError): native.encode(encoded, 3, connection=1)
        with self.assertRaises(ValueError): native.encode(bytes(native.MAX_BODY+1), 3, connection=1)
        self.assertTrue(native.newer(1, 0xFFFFFFFF))
        self.assertFalse(native.newer(0xFFFFFFFE, 1))
        self.assertFalse(native.newer(7, 7))

    def test_root_requests_are_authenticated_and_old_greeting_preserves_opt_in(self):
        self.session.native_lifecycle = False
        writer = PacketWriter()
        for greeting in (native.HELLO, COMBAT_EVENT_HELLO):
            writer.write_byte(8); writer.write_string(greeting)
        self.session.is_logged_in = False
        app.dispatcher.dispatch_datagram(self.udp, writer.get_bytes())
        self.assertFalse(self.session.requested_lifecycle)
        self.session.is_logged_in = True
        app.dispatcher.dispatch_datagram(self.udp, writer.get_bytes())
        self.assertTrue(self.session.requested_lifecycle)
        self.assertTrue(self.session.requested_precise_actions and self.session.requested_combat_events)
        self.assertFalse(self.session.native_lifecycle)  # Only bootstrap activates it.

    def test_deletion_uses_control_queue_and_old_world_data_is_retired(self):
        deletion = DeleteObjectPacket(self.session.entity.net_id).serialize()
        self.udp.send(deletion)
        self.udp.transport.send.assert_not_called()
        self.assertEqual(len(self.session.native_control), 1)
        app._flush_native_control(self.tcp)
        payload = self.tcp.transport.send_payload.call_args.args[0]
        self.assertEqual(native.decode(payload), (1, 3, 0, 0, deletion))
        self.tcp.transport.send_payload.reset_mock()
        app._queue_native_control(self.session, native.encode(deletion, 2, connection=1))
        app._queue_native_control(self.session, native.encode(deletion, 4, connection=1))
        app._flush_native_control(self.tcp)
        self.tcp.transport.send_payload.assert_not_called()
        self.assertEqual(len(self.session.native_control), 1)
        self.session.native_announced_epoch = 4
        app._flush_native_control(self.tcp)
        self.assertEqual(native.decode(self.tcp.transport.send_payload.call_args.args[0])[1], 4)

    def test_retail_stream_and_native_snapshot_budget(self):
        self.session.native_lifecycle = False
        deletion = DeleteObjectPacket(42).serialize()
        self.udp.send(deletion)
        self.udp.transport.send.assert_called_once_with(deletion, self.udp.addr)
        self.assertFalse(self.session.native_control)
        for index in range(80):
            self.server.entities.create_entity(index % 2, 1, (index*10, index*20, 10))
        packets = list(self.server.entities.get_snapshot_packets(7, max_payload=native.UPDATE_LIMIT))
        self.assertGreater(len(packets), 1)
        self.assertTrue(all(len(native.encode(packet, 3, connection=1)) <= 1200 for packet in packets))

    def test_stale_epoch_owner_and_input_sequence_never_execute(self):
        observed = []
        def receive(ctx, reader):
            observed.append(reader.read_byte())
        owner = self.session.entity.net_id
        with patch.dict(app.dispatcher._datagram_handlers, {0x0A: receive}):
            app._accept_native_scope(self.udp, native.encode(b'\x0a\x09', 3, owner, 99, connection=99))
            for epoch, actor, seq, value in ((2, owner, 1, 1), (3, owner+1, 2, 2),
                                           (3, owner, 4, 4), (3, owner, 3, 3), (3, owner, 4, 5)):
                app._accept_native_scope(self.udp, native.encode(bytes((0x0A, value)), epoch, actor, seq, connection=1))
            self.assertEqual(observed, [])  # Receive threads cannot mutate a vehicle.
            app._drain_native_requests(self.server)
        self.assertEqual(observed, [4])
        self.assertEqual(self.session.native_action_sequence, 4)
        self.assertIsNone(native.dispatch_session.get())

    def test_raw_input_cannot_bypass_scope_on_a_different_thread(self):
        self.assertFalse(self.server.allow_packet(self.udp, 0x0A))
        token = native.dispatch_session.set(self.session)
        try:
            self.assertTrue(self.server.allow_packet(self.udp, 0x0A))
            result = []
            thread = threading.Thread(target=lambda: result.append(self.server.allow_packet(self.udp, 0x0A)))
            thread.start(); thread.join(timeout=1)
            self.assertEqual(result, [False])
        finally:
            native.dispatch_session.reset(token)

    def test_slow_control_socket_never_holds_simulation_queue_lock(self):
        entered, release = threading.Event(), threading.Event()
        def stall(_payload):
            entered.set(); release.wait(1)
        self.tcp.transport.send_payload.side_effect = stall
        app._queue_native_control(self.session, native.encode(b'\x1f', 0, connection=1))
        worker = threading.Thread(target=app._flush_native_control, args=(self.tcp,))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            for _ in range(20): app._queue_native_control(self.session, native.encode(b'\x1f', 0, connection=1))
            self.assertLess(time.monotonic()-started, .1)
        finally:
            release.set(); worker.join(timeout=2)
        self.assertFalse(worker.is_alive())

    def test_queue_overflow_disconnects_only_the_offending_peer(self):
        for _ in range(513): app._queue_native_control(self.session, native.encode(b'\x1f', 0, connection=1))
        self.assertEqual(len(self.session.native_control), 512)
        self.assertTrue(self.session.stop_ping_event.is_set())

    def test_fast_readiness_waits_for_world_announcement_commit(self):
        entered, release = threading.Event(), threading.Event()
        self.server.world_identity = (4, 'mayhem')
        self.session.world_announced = True
        self.tcp.transport.send_payload.side_effect = lambda _data: (entered.set(), release.wait(1))
        announced = threading.Thread(target=app.announce_world, args=(self.tcp,))
        received = []
        with patch.dict(app.dispatcher._handlers, {0x39: lambda _ctx, _body: received.append(self.session.native_announced_epoch)}):
            announced.start()
            self.assertTrue(entered.wait(1))
            readiness = threading.Thread(target=app.on_native_control, args=(self.tcp, native.encode(b'\x39\x01', 4, 0, 7, connection=1)))
            readiness.start()
            try:
                self.assertEqual(received, [])
            finally:
                release.set(); announced.join(timeout=2); readiness.join(timeout=2)
        self.assertEqual(received, [4])
        self.assertFalse(announced.is_alive() or readiness.is_alive())

    def test_failed_request_is_contained_to_its_peer(self):
        with patch.dict(app.dispatcher._datagram_handlers, {0x0A: Mock(side_effect=ValueError('bad request'))}):
            app._accept_native_scope(self.udp, native.encode(b'\x0a\x00', 3, self.session.entity.net_id, 1, connection=1))
            app._drain_native_requests(self.server)
        self.assertTrue(self.session.stop_ping_event.is_set())
        self.assertIsNone(native.dispatch_session.get())

    def test_ownerless_command_cannot_smuggle_an_action_record(self):
        message = PacketWriter()
        message.write_int16(0); message.write_int16(0); message.write_string('hello')
        command = b'\x20'+struct.pack('>HH', 1, len(message.get_bytes())+5)+message.get_bytes()
        for combined in (command+b'\x0a\x00', command[:3]+struct.pack('>H', len(command)+2)+command[5:]+b'\x0a\x00'):
            with self.assertRaises(PacketDecodeError):
                app._accept_native_scope(self.udp, native.encode(combined, 3, connection=1))
        self.assertTrue(self.session.native_requests.empty())
        self.assertFalse(self.session.native_control)

    def test_native_actions_validate_the_entire_body_before_mutation(self):
        packet = PacketWriter()
        packet.write_byte(0x0A); packet.write_byte(1)
        packet.write_int32(1); packet.write_int32(0)
        packet.write_bits(8, 16); packet.write_bool(True)
        malformed = packet.get_bytes()+b'\x19\x00\x01'
        app._accept_native_scope(self.udp, native.encode(malformed, 3, self.session.entity.net_id, 1, connection=1))
        app._drain_native_requests(self.server)
        self.assertEqual(self.session.entity.actions, {})
        self.assertTrue(self.session.stop_ping_event.is_set())


if __name__ == '__main__':
    unittest.main()
