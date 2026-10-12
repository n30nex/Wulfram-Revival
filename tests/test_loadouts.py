from collections import Counter
from dataclasses import replace
import unittest

from test_bots import make_server
from wulfram_server import admin_commands, application as app
from wulfram_server.core.combat import CombatSystem, REPAIR_ACTION, PIERCER_ACTION


class LoadoutTests(unittest.TestCase):
    def test_each_team_has_the_same_mixed_bot_roles(self):
        server = make_server()
        server.cfg = replace(server.cfg, game=replace(server.cfg.game, player_limit=80))
        for _ in range(32):
            server.bots.add(team=1)
            server.bots.add(team=2)
        for team in (1, 2):
            self.assertEqual(Counter(bot.vehicle_loadout for bot in server.bots.bots if bot.team == team),
                             {"tank": 20, "scout": 8, "siege": 4})

    def test_repair_requires_friendly_live_target_line_of_sight_and_resources(self):
        server = make_server()
        admin_commands.initialize(server)
        medic = server.bots.add(team=1, loadout="scout")
        medic.entity.pos = (200, 0, 15)
        ally = server.entities.create_entity(0, 1, (300, 0, 15))
        ally.set_health_points(40)
        medic.entity.actions[REPAIR_ACTION] = 1
        combat = CombatSystem(server)
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": 0}
        combat.step(0.04)
        self.assertEqual(ally.health_points, 40)
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": ally.net_id}
        combat.step(0.04)
        self.assertEqual(ally.health_points, 41)
        self.assertEqual(medic.entity.weapon_ready_mask, 2)
        self.assertLess(medic.entity.energy, 1)
        self.assertLess(medic.entity.repair_charge, 1)
        self.assertEqual(medic.score.healing, 1)
        ally.team_id = 2
        combat.step(0.04)
        self.assertEqual(ally.health_points, 41)
        ally.team_id = 1
        medic.entity.energy = 0
        combat.step(0.04)
        self.assertEqual(ally.health_points, 41)

    def test_piercer_has_cooldown_fuel_cost_and_no_splash(self):
        server = make_server()
        gunner = server.bots.add(team=1)
        gunner.entity.actions[PIERCER_ACTION] = 1
        combat = CombatSystem(server)
        destroyed = {}
        combat._advance_tank_weapons(gunner.entity, 0.04, destroyed)
        projectiles = [entity for entity in server.entities.get_all() if entity.unit_type == 6]
        self.assertEqual(len(projectiles), 1)
        projectile = projectiles[0]
        self.assertEqual(projectile.projectile_kind, "piercer")
        self.assertAlmostEqual(projectile.vel[0], server.packet_cfg.combat.piercer_launch_speed)
        self.assertLess(gunner.entity.energy, 1)
        combat._advance_tank_weapons(gunner.entity, 0.04, destroyed)
        self.assertEqual(sum(entity.unit_type == 6 for entity in server.entities.get_all()), 1)
        victim = server.entities.create_entity(0, 2, (100, 0, 15))
        bystander = server.entities.create_entity(0, 2, (101, 0, 15))
        combat._resolve_pulse_impact(projectile, victim.net_id, destroyed)
        self.assertEqual(victim.health_points, 0)
        self.assertEqual(bystander.health_points, 100)
        self.assertEqual(destroyed[victim.net_id].killer_player_id, gunner.player_id)

    def test_siege_trades_cargo_for_armor_and_neutral_cargo_is_claimed(self):
        server = make_server()
        siege = server.bots.add(team=1, loadout="siege")
        self.assertEqual(siege.entity.max_health, 180)
        cargo = server.entities.create_entity(19, 0, (0, 0, 0))
        cargo.cargo_item_id = 5
        self.assertFalse(app._pickup_cargo(server, siege, cargo))
        siege.entity.pos = (100, 0, 15)
        tank = server.bots.add(team=1, loadout="tank")
        self.assertTrue(app._pickup_cargo(server, tank, cargo))
        self.assertEqual(tank.carried_cargo_team_id, 1)
        self.assertEqual(tank.carried_cargo_item_id, 5)


if __name__ == "__main__":
    unittest.main()
