"""Entity traffic must wait for the retail client's WANT_UPDATES barrier."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from wulfram_server import admin_commands, application as app
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.hooks import ServerHooks


def client(ready):
    return SimpleNamespace(
        is_logged_in=True, is_ready_for_updates=ready, world_announced=ready,
        is_bot=False, name="Human", entity=None, team=1, player_id=1,
        udp_context=SimpleNamespace(send=Mock()), tcp_sock=None,
    )


class WorldReadinessTests(unittest.TestCase):
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
