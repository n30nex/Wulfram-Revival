"""Entity traffic must wait for the retail client's WANT_UPDATES barrier."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from wulfram_server import admin_commands, application as app
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.hooks import ServerHooks
from wulfram_server.network.packets import WorldStatsPacket
from test_bots import make_server


def client(ready):
    return SimpleNamespace(
        is_logged_in=True, is_ready_for_updates=ready, world_announced=ready,
        is_bot=False, name="Human", entity=None, team=1, player_id=1,
        udp_context=SimpleNamespace(send=Mock()), tcp_sock=None,
    )


class WorldReadinessTests(unittest.TestCase):
    def connected_world(self, count=1):
        server = make_server()
        server.land = object()
        server.current_map_name = 'crossroads'
        server.trace = Mock()
        server.logger = Mock()
        server.udp_sessions = {}
        for index in range(count):
            session = app.ClientSession(server, Mock(), ('127.0.0.1', 40000+index))
            session.player_id = index+1
            session.is_logged_in = session.world_announced = True
            session.tcp_transport = Mock()
            session.udp_context = Mock()
            server.sessions.append(session)
        return server

    def test_map_announcement_uses_the_existing_reliable_tcp_channel(self):
        server = self.connected_world()
        server.current_map_name = 'mayhem'
        app.broadcast(server, WorldStatsPacket(map_name='mayhem'))
        session = server.sessions[0]
        self.assertTrue(session.world_change_event.is_set())
        app.announce_world(app.TcpContext(session.tcp_transport, server, session))
        session.tcp_transport.send_payload.assert_called_once_with(WorldStatsPacket(map_name='mayhem').serialize())
        session.udp_context.send.assert_not_called()

    def test_disconnect_during_broadcast_does_not_skip_the_next_player(self):
        server = self.connected_world(2)
        first, second = server.sessions
        first.udp_context.send.side_effect = lambda payload: server.sessions.remove(first)
        app.broadcast(server, b'\x1b\x00\x00\x00\x01')
        second.udp_context.send.assert_called_once()

    def test_readiness_waits_for_teardown_and_pending_world_announcement(self):
        for phase in ('teardown', 'announcement'):
            with self.subTest(phase=phase):
                server = self.connected_world()
                session = server.sessions[0]
                if phase == 'teardown':
                    server.map_change_transition = object()
                else:
                    session.world_change_event.set()
                app.on_want_updates(app.TcpContext(session.tcp_transport, server, session), b'\x39\x01')
                self.assertFalse(session.is_ready_for_updates)
                session.tcp_transport.send_payload.assert_not_called()

    def test_queued_map_changes_coalesce_to_the_current_world(self):
        server = self.connected_world()
        session = server.sessions[0]
        for name in ('mayhem', 'crossroads', 'frontier'):
            server.current_map_name = name
            app.broadcast(server, WorldStatsPacket(map_name=name))
        app.announce_world(app.TcpContext(session.tcp_transport, server, session))
        session.tcp_transport.send_payload.assert_called_once_with(WorldStatsPacket(map_name='frontier').serialize())
        self.assertFalse(session.world_change_event.is_set())

    def test_map_change_does_not_announce_to_an_unfinished_login(self):
        server = self.connected_world()
        session = server.sessions[0]
        session.world_announced = False
        transition = admin_commands.MapChangeTransition(
            admin_commands.MapChangeRequest(None, 'mayhem'), object(), None, 0.)
        admin_commands._complete_map_change(server, transition)
        app.announce_world(app.TcpContext(session.tcp_transport, server, session))
        self.assertFalse(session.world_announced)
        sent = [call.args[0] for call in session.tcp_transport.send_payload.call_args_list
                + session.udp_context.send.call_args_list]
        sent = [packet if isinstance(packet, bytes) else packet.serialize() for packet in sent]
        self.assertNotIn(0x16, [packet[0] for packet in sent])

    def test_inflight_old_snapshot_finishes_before_new_world_announcement(self):
        server = self.connected_world()
        session = server.sessions[0]
        ctx = app.TcpContext(session.tcp_transport, server, session)
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        sent = []
        def send(payload):
            sent.append(payload)
            if payload == b'\x0fFIRST':
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('snapshot test barrier timed out')
        session.tcp_transport.send_payload.side_effect = send
        transition = admin_commands.MapChangeTransition(
            admin_commands.MapChangeRequest(None, 'mayhem'), object(), None, 0.)
        failures = []
        def ready():
            try:
                app.on_want_updates(ctx, b'\x39\x01')
            except Exception as error:
                failures.append(error)
        def change():
            try:
                admin_commands._complete_map_change(server, transition)
                app.announce_world(ctx)
            except Exception as error:
                failures.append(error)
            finally:
                completed.set()
        with patch.object(server.entities, 'get_snapshot_packets', return_value=[b'\x0fFIRST', b'\x0fSECOND']):
            snapshot_worker = threading.Thread(target=ready)
            map_worker = threading.Thread(target=change)
            snapshot_worker.start()
            try:
                self.assertTrue(entered.wait(1))
                map_worker.start()
                # With the old implementation the map announcement completed
                # while the old snapshot was still paused in its first frame.
                completed.wait(.05)
            finally:
                release.set()
                snapshot_worker.join(2)
                if map_worker.ident is not None:
                    map_worker.join(2)
        self.assertEqual(failures, [])
        self.assertFalse(snapshot_worker.is_alive())
        self.assertFalse(map_worker.is_alive())
        self.assertFalse(session.is_ready_for_updates)
        world_index = next(index for index, packet in enumerate(sent) if packet[0] == 0x16)
        self.assertGreater(world_index, sent.index(b'\x0fSECOND'))

    def test_map_broadcast_does_not_wait_for_a_slow_client_snapshot(self):
        server = self.connected_world()
        session = server.sessions[0]
        with session.world_lock:
            worker = threading.Thread(target=app.broadcast, args=(server, WorldStatsPacket(map_name='mayhem')))
            worker.start()
            worker.join(.5)
            blocked = worker.is_alive()
        worker.join(1)
        self.assertFalse(blocked)
        self.assertTrue(session.world_change_event.is_set())
        session.tcp_transport.send_payload.assert_not_called()

    def test_map_load_never_sends_entities_before_client_requests_them(self):
        loading = client(False)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_dir = root / "shared/data/maps/test"
            map_dir.mkdir(parents=True)
            (map_dir / "state").write_text("e 1 1 2 3 0 0 0 1\n")
            server = SimpleNamespace(content_root=root, entities=EntityManager(), sessions=[loading])
            self.assertTrue(app.load_map_state(server, "test"))
            self.assertEqual(len(server.entities.get_all()), 1)
            loading.udp_context.send.assert_not_called()

    def test_world_broadcasts_wait_but_roster_chat_and_world_announcement_do_not(self):
        loading, ready = client(False), client(True)
        server = SimpleNamespace(sessions=[loading, ready])
        for opcode in app.WORLD_ENTITY_OPCODES:
            app.broadcast(server, bytes([opcode]))
        loading.udp_context.send.assert_not_called()
        self.assertEqual(ready.udp_context.send.call_count, len(app.WORLD_ENTITY_OPCODES))
        for opcode in (0x16, 0x1A, 0x1B, 0x1C, 0x1F):
            app.broadcast(server, bytes([opcode]))
        self.assertEqual(loading.udp_context.send.call_count, 5)
        ready.udp_context.send.reset_mock()
        loading.udp_context.send.reset_mock()
        carrier = SimpleNamespace(player_id=3, carried_cargo_item_id=2, carried_cargo_team_id=1, team=1)
        app._send_carrying_info(server, carrier, has_cargo=True)
        loading.udp_context.send.assert_not_called()
        ready.udp_context.send.assert_called_once()

    def test_map_change_rearms_readiness_without_an_immediate_snapshot(self):
        session = client(True)
        server = SimpleNamespace(sessions=[session], hooks=ServerHooks(), entities=EntityManager())
        request = admin_commands.MapChangeRequest(None, "next-map")
        transition = admin_commands.MapChangeTransition(request, object(), "e 1 1 2 3 0 0 0 1", 0.0)
        admin_commands._complete_map_change(server, transition)
        self.assertFalse(session.is_ready_for_updates)
        self.assertTrue(session.world_announced)
        packets = [call.args[0] for call in session.udp_context.send.call_args_list]
        wire = [packet if isinstance(packet, bytes) else packet.serialize() for packet in packets]
        self.assertIn(0x16, [packet[0] for packet in wire])
        self.assertNotIn(0x0F, [packet[0] for packet in wire])


if __name__ == "__main__":
    unittest.main()
