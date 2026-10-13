"""Run with python -m unittest discover -s tests -v; no game assets required."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import math
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from wulfram_server.bots import BotManager
from wulfram_server.core.combat import CombatSystem
from wulfram_server.core.config import Config, ConfigurationError
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.hooks import ProductionHooks, ServerHooks
from wulfram_server.network.packets.packet_config import PacketConfig


def make_server():
    ids = iter(range(1, 100))
    server = SimpleNamespace(
        cfg=Config(),
        packet_cfg=PacketConfig.load(str(ROOT / "server/wulfram_server/content/packets.toml")),
        entities=EntityManager(), sessions=[], hooks=ServerHooks(),
        physics=SimpleNamespace(trace_segment=Mock(return_value={"hit": False, "entity_id": 0})),
        get_next_player_id=lambda: next(ids), map_change_transition=None,
    )
    server.bots = BotManager(server)
    def spend_fuel(entity, amount):
        if entity.energy * 33000 < amount:
            return False
        entity.energy = max(0.0, entity.energy - amount / 33000)
        return True
    server.physics.spend_fuel = spend_fuel
    server.physics.refuel = lambda entity, amount: setattr(entity, "energy", min(1.0, entity.energy + amount / 33000))
    server.entities.create_entity(27, 1, (0.0, 0.0, 0.0))
    server.entities.create_entity(27, 2, (500.0, 0.0, 0.0))
    return server


class BotTests(unittest.TestCase):
    def test_waiting_first_deployment_precedes_repeated_respawns(self):
        server = make_server()
        veteran = server.bots.add(team=1)
        waiting = server.bots.add(team=1)
        self.assertIsNone(waiting.entity)
        server.entities.remove_entity(veteran.entity.net_id)
        veteran.entity = None
        server.bots.step(100)
        self.assertIsNotNone(waiting.entity)
        self.assertIsNone(veteran.entity)

    def test_retail_team_capacity_leaves_human_slots_with_64_bots(self):
        from wulfram_server.application import WulframServerContext
        from wulfram_server.network.packets.behavior import BehaviorPacket
        cfg = Config(game=replace(Config().game, player_limit=80, bots_per_team=32))
        hooks = ServerHooks()
        hooks.authoritative_physics_enabled = False
        server = WulframServerContext(cfg, PacketConfig(), content_root=ROOT, hooks=hooks)
        try:
            wire = BehaviorPacket(server.packet_cfg.behavior).serialize()
            # The retail decoder stores the header's int at 0x67917c; the
            # team chooser compares its roster count against this value.
            capacity = struct.unpack_from(">i", wire, 22)[0]
            self.assertEqual(capacity, 40)
            self.assertEqual(capacity - cfg.game.bots_per_team, 8)
        finally:
            server.tcp_sock.close()
            server.udp_sock.close()

    def test_fight_uses_authoritative_combat_and_pursues_obstructed_targets(self):
        server = make_server()
        bot = server.bots.add("Red CPU", 1)
        target = server.entities.create_entity(0, 2, (100.0, 0.0, 15.0))
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": target.net_id}
        # Spawn uses the real monotonic clock; force a decision deterministically.
        bot.next_decision_at = 0.0
        server.bots.step(101.0)
        self.assertEqual(bot.entity.actions[8], 0.0)
        server.bots.step(101.8)
        self.assertEqual(bot.entity.actions[8], 1.0)
        self.assertEqual(bot.entity.actions[12], 1.0)
        self.assertEqual(bot.entity.actions[2], 0.0)
        self.assertGreater(bot.entity.input_sequence, 0)
        CombatSystem(server).step(0.04)
        self.assertLess(target.health_points, target.max_health)
        self.assertLess(bot.entity.energy, 1.0)
        self.assertTrue(any(entity.unit_type == 6 for entity in server.entities.get_all()))

        friendly = server.entities.create_entity(0, 1, (50.0, 0.0, 15.0))
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": friendly.net_id}
        server.bots.step(102.0)
        self.assertEqual(bot.entity.actions[8], 0.0)
        self.assertEqual(bot.entity.actions[12], 0.0)
        self.assertTrue(bot.wants_move)
        self.assertGreater(abs(bot.entity.actions[1])+abs(bot.entity.actions[2]), 0.0)
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": 0}
        server.bots.step(103.0)
        self.assertEqual(bot.entity.actions[8], 0.0)
        self.assertTrue(bot.wants_move)
        self.assertGreater(abs(bot.entity.actions[1])+abs(bot.entity.actions[2]), 0.0)

    def test_spawn_uses_another_free_pad_before_queuing(self):
        server = make_server()
        first = server.bots.add(team=1)
        second_pad = server.entities.create_entity(27, 1, (100.0, 0.0, 0.0))
        second = server.bots.add(team=1)
        self.assertEqual(first.entity.pos, (0.0, 0.0, 15.0))
        self.assertEqual(second.entity.pos, (second_pad.pos[0], 0.0, 15.0))
        self.assertTrue(server.bots.can_spawn(1))
        queued = server.bots.add(team=1)
        self.assertIsNone(queued.entity)
        second.entity.pos = (100.0, 50.0, 15.0)
        server.bots.step(100.0)
        self.assertEqual(queued.entity.pos, (100.0, 0.0, 15.0))

    def test_human_pad_choice_uses_nearest_free_friendly_pad(self):
        server = make_server()
        near = server.entities.create_entity(27, 1, (80.0, 0.0, 0.0))
        far = server.entities.create_entity(27, 1, (200.0, 0.0, 0.0))
        preferred = server.entities.get_entity(1)
        choose = lambda: server.bots._spawn_pad(1, require_free=True, preferred_id=preferred.net_id)
        self.assertIs(choose(), preferred)
        server.entities.create_entity(0, 1, (0.0, 0.0, 15.0))
        self.assertIs(choose(), near)
        server.entities.create_entity(1, 2, (80.0, 0.0, 15.0))
        self.assertIs(choose(), far)
        far.set_health_points(0)
        self.assertIsNone(choose())

    def test_turns_toward_enemy_and_never_spawns_on_enemy_pad(self):
        server = make_server()
        bot = server.bots.add(team=1)
        target = server.entities.create_entity(0, 2, (0.0, 200.0, 15.0))
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": target.net_id}
        bot.next_decision_at = 0.0
        server.bots.step(100.0)
        self.assertGreater(bot.entity.current_input_sample().controls.turn, 0.0)
        self.assertEqual(bot.entity.actions[8], 0.0)
        bot.entity.rot = (0.0, 0.0, math.pi / 2)
        server.physics.trace_segment.return_value = {"hit": True, "entity_id": target.net_id}
        server.bots.step(101.0)
        self.assertEqual(bot.entity.actions[8], 1.0)
        for entity in server.entities.get_all():
            if entity.unit_type == 27 and entity.team_id == 1:
                entity.set_health_points(0.0)
        self.assertFalse(server.bots.can_spawn(1))
        with self.assertRaisesRegex(ValueError, "living repair pad"):
            server.bots.add(team=1)
        bot.entity = None
        server.bots.step(102.0)
        self.assertIsNone(bot.entity)

    def test_config_defaults_and_capacity_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_dir = root / "shared/data/maps/your-map"
            map_dir.mkdir(parents=True)
            (map_dir / "land").touch()
            (map_dir / "state").touch()
            gameplay = root / "gameplay.toml"
            gameplay.write_text((ROOT / "server/wulfram_server/content/gameplay.toml").read_text())
            path = root / "server.toml"
            example = (ROOT / "config/server.example.toml").read_text()
            example = example.replace("runtime/state", (root / "staging/state").as_posix())
            example = example.replace("runtime/logs", (root / "staging/logs").as_posix())
            environment = {"WULFRAM_STAGING_PASSWORD": "player", "WULFRAM_STAGING_ADMIN_PASSWORD": "admin"}
            for value in (None, "0", "2"):
                line = "" if value is None else f"bots_per_team = {value}\n"
                path.write_text(example.replace("bots_per_team = 0\n", line))
                config = Config.load_strict(path, gameplay_filename=gameplay, environment=environment)
                self.assertEqual(config.game.bots_per_team, int(value or 0))
            for value in ("-1", "10", "32", "true", "1.5"):
                path.write_text(example.replace("bots_per_team = 0", f"bots_per_team = {value}"))
                with self.assertRaises(ConfigurationError):
                    Config.load_strict(path, gameplay_filename=gameplay, environment=environment)
            # A 64-CPU match needs additional slots for actual players.
            large_match = example.replace("player_limit = 20", "player_limit = 80").replace(
                "bots_per_team = 0", "bots_per_team = 32")
            path.write_text(large_match)
            config = Config.load_strict(path, gameplay_filename=gameplay, environment=environment)
            self.assertEqual((config.game.bots_per_team, config.game.player_limit), (32, 80))
            for invalid in (
                large_match.replace("player_limit = 80", "player_limit = 64"),
                large_match.replace("player_limit = 80", "player_limit = 129"),
                large_match.replace("bots_per_team = 32", "bots_per_team = 33"),
            ):
                path.write_text(invalid)
                with self.assertRaises(ConfigurationError):
                    Config.load_strict(path, gameplay_filename=gameplay, environment=environment)

    def test_startup_populates_both_teams_before_first_client(self):
        server = make_server()
        server.cfg = replace(server.cfg, game=replace(server.cfg.game, bots_per_team=2))
        server.current_map_name = "crossroads"
        server.content_root = Path("unused")
        server.land = SimpleNamespace(loaded=True, load=Mock(),identity='fixture',revision=1,
                                      width=3,height=3,cell_size_x=250.,cell_size_y=250.,
                                      heights=[[0.]*3 for _ in range(3)])
        server.first_map_load = False
        hooks = ProductionHooks(server.cfg, {"WULFRAM_SERVER_PASSWORD": "player", "WULFRAM_SERVER_ADMIN_PASSWORD": "admin"})
        with patch("wulfram_server.hooks.operations.prepare_operational_directories"), patch("wulfram_server.application.load_map_state", return_value=True):
            hooks.start(server)
        self.assertEqual([bot.team for bot in server.bots.bots], [1, 2, 1, 2])
        self.assertTrue(server.first_map_load)
        self.assertEqual(len(server.sessions), 4)
        self.assertEqual(sum(bot.entity is not None for bot in server.bots.bots), 2)
        for bot in server.bots.bots[:2]:
            x, y, z = bot.entity.pos
            bot.entity.pos = (x, y + 30.0, z)
        server.bots.step(100.0)
        self.assertTrue(all(bot.entity is not None for bot in server.bots.bots))


if __name__ == "__main__":
    unittest.main()
