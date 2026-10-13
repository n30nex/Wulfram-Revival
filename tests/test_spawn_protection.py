"""Spawn safety uses the same damage and attack rules for human and CPU players."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_bots import make_server
from wulfram_server import application as app
from wulfram_server.core.combat import CombatSystem, AUTOCANNON_ACTION, PULSE_ACTION, PIERCER_ACTION
from wulfram_server.core.entity import SPAWN_PROTECTION_SECONDS


class SpawnProtectionTests(unittest.TestCase):
    def test_damage_is_blocked_then_returns_after_five_simulation_seconds(self):
        server = make_server()
        bot = server.bots.add(team=1)
        self.assertEqual(bot.entity.spawn_protection_remaining, SPAWN_PROTECTION_SECONDS)
        self.assertFalse(bot.entity.apply_damage(500))
        self.assertEqual(bot.entity.health_points, 100)
        combat = CombatSystem(server)
        combat.step(4.9)
        self.assertFalse(bot.entity.apply_damage(500))
        combat.step(.11)
        self.assertTrue(bot.entity.apply_damage(500))

    def test_every_offensive_action_ends_protection_even_without_fuel(self):
        for loadout, action in (("tank", AUTOCANNON_ACTION), ("tank", PULSE_ACTION),
                                ("siege", PIERCER_ACTION), ("scout", AUTOCANNON_ACTION)):
            with self.subTest(loadout=loadout, action=action):
                server = make_server()
                bot = server.bots.add(team=1, loadout=loadout)
                bot.entity.energy = 0
                bot.entity.actions[action] = 1
                CombatSystem(server).step(.04)
                self.assertEqual(bot.entity.spawn_protection_remaining, 0)
                self.assertTrue(bot.entity.apply_damage(500))

    def test_attacking_cancels_shield_before_incoming_projectiles_resolve(self):
        server = make_server()
        bot = server.bots.add(team=1)
        bot.entity.actions[AUTOCANNON_ACTION] = 1
        bot.entity.energy = 0
        combat = CombatSystem(server)
        with patch.object(combat, "_advance_pulse_shells",
                          side_effect=lambda *_: bot.entity.apply_damage(500)):
            combat.step(.04)
        self.assertEqual(bot.entity.health_points, 0)

    def test_respawn_has_a_fresh_shield_on_a_new_entity(self):
        server = make_server()
        bot = server.bots.add(team=1)
        old = bot.entity
        old.spawn_protection_remaining = 0
        server.entities.remove_entity(old.net_id)
        bot.entity = None
        self.assertTrue(server.bots._spawn(bot, 100))
        self.assertNotEqual(bot.entity.net_id, old.net_id)
        self.assertEqual(bot.entity.spawn_protection_remaining, SPAWN_PROTECTION_SECONDS)
        self.assertEqual(old.spawn_protection_remaining, 0)

    def test_human_gets_one_expiry_notice_and_existing_world_entities_get_no_shield(self):
        server = make_server()
        entity = server.entities.create_entity(0, 1, (100, 0, 15))
        self.assertEqual(entity.spawn_protection_remaining, 0)
        session = SimpleNamespace(server=server, player_id=80, entity=entity,
                                  is_logged_in=True, udp_context=Mock())
        server.sessions.append(session)
        app._note_entity_spawn(session, entity, "reincarnate")
        app._update_spawn_protection_notices(server)
        session.udp_context.send.assert_not_called()
        entity.spawn_protection_remaining = 0
        app._update_spawn_protection_notices(server)
        app._update_spawn_protection_notices(server)
        session.udp_context.send.assert_called_once()
        self.assertIn("shield ended", session.udp_context.send.call_args.args[0].message)


if __name__ == "__main__":
    unittest.main()
