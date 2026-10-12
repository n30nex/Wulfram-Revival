"""Real scoring, round transitions and public metadata boundaries."""
from dataclasses import replace
import json
import struct
import unittest
from unittest.mock import patch

from test_bots import make_server
from wulfram_server import admin_commands, application as app, matches
from wulfram_server.core.combat import Destruction
from wulfram_server.network.packets.player import UpdateStatsPacket


class MatchTests(unittest.TestCase):
    def server(self):
        server = make_server()
        server.current_map_name = "crossroads"
        server.cfg = replace(server.cfg, game=replace(server.cfg.game,
            round_seconds=60, map_rotation=("crossroads", "mayhem")))
        admin_commands.initialize(server)
        return server

    def test_combat_scores_once_and_credit_survives_shooters_death(self):
        server = self.server()
        shooter = server.bots.add("Attacker", 1)
        victim = server.bots.add("Defender", 2)
        victim.entity.set_health_points(0)
        death = Destruction(victim.entity.net_id, killer_player_id=shooter.player_id)
        # A projectile retains its player's ID after its original Tank is gone.
        shooter.entity = None
        app._finalize_combat_destructions(server, [death, death])
        self.assertEqual((shooter.score.kills, shooter.score.points, victim.score.deaths), (1, 1, 1))
        self.assertEqual(server.match_state.team_scores, {1: 1, 2: 0})
        matches.reset_round(server)
        self.assertEqual((shooter.score.kills, shooter.score.total_kills), (0, 1))
        self.assertEqual((victim.score.deaths, victim.score.total_deaths), (0, 1))

    def test_structure_points_and_friendly_kills_do_not_create_enemy_kills(self):
        server = self.server()
        shooter = server.bots.add(team=1)
        target = server.entities.create_entity(30, 2, (200, 50, 0))
        target.set_health_points(0)
        app._finalize_combat_destructions(server, [Destruction(target.net_id, killer_player_id=shooter.player_id)])
        self.assertEqual((shooter.score.kills, shooter.score.structures, shooter.score.points), (0, 1, 3))
        friend = server.bots.add(team=1)
        shooter.entity.pos = (100, 0, 15)
        server.bots.step(100)
        self.assertIsNotNone(friend.entity)
        friend.entity.set_health_points(0)
        app._finalize_combat_destructions(server, [Destruction(friend.entity.net_id, killer_player_id=shooter.player_id)])
        self.assertEqual(shooter.score.points, 3)
        self.assertEqual(friend.score.deaths, 1)

    def test_timeout_result_and_tie_queue_only_one_next_map(self):
        for scores, winner in (({1: 9, 2: 4}, 1), ({1: 3, 2: 3}, 0)):
            with self.subTest(scores=scores):
                server = self.server()
                server.match_state.armed = True
                server.match_state.started_at = 0
                server.match_state.team_scores = scores
                with patch("wulfram_server.matches.time.monotonic", return_value=61), \
                     patch("wulfram_server.application.verify_map_land_exists", return_value=True):
                    admin_commands.check_win_condition(server)
                    admin_commands.check_win_condition(server)
                self.assertEqual(server.match_state.winner_team, winner)
                self.assertEqual(server.admin_command_queue.qsize(), 1)
                self.assertEqual(server.admin_command_queue.get_nowait().map_name, "mayhem")

    def test_rotation_visits_each_configured_map_in_order(self):
        server=self.server()
        server.cfg=replace(server.cfg,game=replace(server.cfg.game,map_rotation=('crossroads','mayhem','frontier')))
        with patch('wulfram_server.application.verify_map_land_exists',return_value=True):
            for expected in ('mayhem','frontier','crossroads','mayhem'):
                server.current_map_name=admin_commands._choose_rotation_map(server)
                self.assertEqual(server.current_map_name,expected)
        with patch('wulfram_server.application.verify_map_land_exists',side_effect=lambda server,name:name!='frontier'):
            self.assertEqual(admin_commands._choose_rotation_map(server),'crossroads')

    def test_retail_score_fields_and_no_fabricated_initial_values(self):
        self.assertEqual(struct.unpack(">iihhhhhiii", UpdateStatsPacket(7, 2, 12, 4, 3).serialize()[1:]),
                         (7, 6, 2, 33, 12, 4, 3, 0, 0, 10))
        self.assertEqual(struct.unpack(">iihhhhhiii", UpdateStatsPacket(7, 2).serialize()[1:]),
                         (7, 6, 2, 33, 0, 0, 0, 0, 0, 10))

    def test_public_snapshot_excludes_transport_credentials_and_internal_state(self):
        server = self.server()
        bot = server.bots.add(team=1)
        bot.session_key = "private-test-key"
        bot.address = ("192.0.2.77", 4242)
        server.private_password = "private-test-password"
        document = matches.public_snapshot(server)
        encoded = json.dumps(document)
        for secret in (bot.session_key, bot.address[0], server.private_password, "tcp_sock", "state_directory"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(document["bots"], 1)
        self.assertEqual(document["leaders"][0]["kills"], 0)


if __name__ == "__main__":
    unittest.main()
