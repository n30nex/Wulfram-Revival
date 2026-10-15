"""Only accepted authoritative shots produce opt-in presentation events."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_bots import make_server
from wulfram_server import application as app
from wulfram_server.core.combat import CombatSystem, SHOT_TANK, SHOT_PULSE, SHOT_PIERCER, SHOT_IMPACT, SHOT_SURFACE, SHOT_MISS
from wulfram_server.core.entity import PendingTransientEvent
from wulfram_server.network.packets.gameplay import PositionalTransient, TransientArrayPacket


class CombatPresentationTests(unittest.TestCase):
    def test_no_shot_for_empty_fuel_or_cooldown_and_misses_have_real_endpoints(self):
        server = make_server()
        tank = server.bots.add(team=1).entity
        combat = CombatSystem(server)
        tank.actions[8] = 1
        tank.energy = 0
        combat._advance_tank_weapons(tank, .04, {})
        self.assertEqual(tank.pending_transient_events, [])
        tank.energy = 1
        server.physics.trace_segment.return_value = {'hit': False, 'entity_id': 0, 'point': (0, 0, 0)}
        combat._advance_tank_weapons(tank, .04, {})
        first, last = tank.pending_transient_events
        self.assertEqual((first.event_type, last.event_type), (SHOT_TANK, SHOT_MISS))
        self.assertEqual(first.secondary_id, last.secondary_id)
        self.assertTrue(first.modern_only and last.modern_only)
        self.assertNotEqual(last.position, (0, 0, 0))
        self.assertEqual(combat._shot_sequence, 1)  # Audio must not advance scatter RNG.
        tank.pending_transient_events.clear()
        combat._advance_tank_weapons(tank, .001, {})
        self.assertEqual(tank.pending_transient_events, [])

    def test_impact_uses_authoritative_point_and_projectile_cues_are_distinct(self):
        server = make_server()
        tank = server.bots.add(team=1).entity
        combat = CombatSystem(server)
        server.physics.trace_segment.return_value = {'hit': True, 'entity_id': 0, 'point': (20, 30, 4)}
        tank.actions[8] = 1
        combat._advance_tank_weapons(tank, .04, {})
        self.assertEqual(tank.pending_transient_events[-1].event_type, SHOT_SURFACE)
        self.assertEqual(tank.pending_transient_events[-1].position, (20, 30, 4))
        combat._fire_pulse(tank)
        combat._fire_pulse(tank, piercer=True)
        self.assertEqual([e.event_type for e in tank.pending_transient_events[-2:]], [SHOT_PULSE, SHOT_PIERCER])
        self.assertEqual(len({e.secondary_id for e in tank.pending_transient_events}), 3)

    def test_legacy_stream_excludes_extensions_and_queue_is_drained_once(self):
        server = make_server()
        source = server.entities.get_all()[0]
        common = PendingTransientEvent(0x10, position=(1, 2, 3))
        private = PendingTransientEvent(SHOT_TANK, position=(4, 5, 6), secondary_id=7, modern_only=True)
        source.pending_transient_events.extend((common, private))
        def session(modern):
            return SimpleNamespace(is_logged_in=True, is_ready_for_updates=True,
                udp_context=Mock(), entity=None, combat_events=modern)
        legacy, modern = session(False), session(True)
        server.sessions = [legacy, modern]
        app._broadcast_pending_transients(server)
        legacy.udp_context.send.assert_called_once_with(TransientArrayPacket([PositionalTransient(0x10, (1, 2, 3))]).serialize())
        modern.udp_context.send.assert_called_once_with(TransientArrayPacket([
            PositionalTransient(0x10, (1, 2, 3)), PositionalTransient(SHOT_TANK, (4, 5, 6), 7)]).serialize())
        self.assertEqual(source.pending_transient_events, [])
        app._broadcast_pending_transients(server)
        self.assertEqual(modern.udp_context.send.call_count, 1)

    def test_busy_modern_batches_do_not_fragment_and_legacy_gets_no_extensions(self):
        server = make_server()
        source = server.entities.get_all()[0]
        source.pending_transient_events.extend(PendingTransientEvent(
            SHOT_TANK, position=(1, 2, 3), secondary_id=index+1, modern_only=True) for index in range(300))
        sessions = [SimpleNamespace(is_logged_in=True, is_ready_for_updates=True,
            udp_context=Mock(), entity=None, combat_events=value) for value in (False, True)]
        server.sessions = sessions
        app._broadcast_pending_transients(server)
        sessions[0].udp_context.send.assert_not_called()
        packets = [call.args[0] for call in sessions[1].udp_context.send.call_args_list]
        self.assertEqual([packet[1] for packet in packets], [96, 96, 96, 12])
        self.assertTrue(all(len(packet) <= 1200 for packet in packets))


if __name__ == '__main__':
    unittest.main()
