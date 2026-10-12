"""Check decisions that distinguish a team from a queue of nearest-target bots."""
from collections import Counter
from dataclasses import replace
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_bots import make_server


class TacticsTests(unittest.TestCase):
    def arena(self, count=8):
        server = make_server()
        server.cfg = replace(server.cfg,game=replace(server.cfg.game,player_limit=80))
        pads = server.entities.get_all()
        pads[0].pos, pads[1].pos = (500.,2500.,0.),(4500.,2500.,0.)
        server.land = SimpleNamespace(loaded=True,identity='flat',revision=1,width=25,height=25,
                                     cell_size_x=250.,cell_size_y=250.,heights=[[0.]*25 for _ in range(25)])
        server.bots.prepare_navigation()
        for index in range(count):
            bot = server.bots.add(team=1)
            if bot.entity is None:
                bot.entity = server.entities.create_entity(0,1,(500.,2500.+index*25,15.))
        return server, pads[1]

    def test_jobs_have_distinct_goals_and_opposite_flanking_routes(self):
        server, objective = self.arena(32)
        for bot in server.bots.bots:
            server.bots._plan(bot,100,[objective])
        bots = server.bots.bots
        self.assertEqual(Counter(bot.role for bot in bots),
                         {'assault':12,'flank':8,'guard':8,'interceptor':4})
        self.assertGreaterEqual(len({bot.goal for bot in bots}),8)
        self.assertLess(bots[1].goal[1],2000)
        self.assertGreater(bots[5].goal[1],3000)
        self.assertLess(math.dist(bots[2].goal,(500,2500)),500)
        bots[1].entity.pos = (*bots[1].goal,15.)
        server.bots._plan(bots[1],103,[objective])
        self.assertTrue(bots[1].approach_done)
        self.assertGreater(bots[1].goal[0],4000)

    def test_guard_intercepts_an_incursion_then_resumes_patrol(self):
        server, objective = self.arena()
        guard = server.bots.bots[2]
        intruder = server.entities.create_entity(0,2,(800.,2600.,15.))
        server.bots._plan(guard,100,[objective,intruder])
        self.assertEqual(guard.order,'intercept')
        self.assertLess(math.dist(guard.goal,intruder.pos[:2]),250)
        server.bots._plan(guard,103,[objective])
        self.assertEqual(guard.order,'guard')

    def test_bot_can_engage_visible_enemy_when_nearest_is_blocked(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        blocked = server.entities.create_entity(0,2,(600.,2500.,15.))
        exposed = server.entities.create_entity(0,2,(700.,2500.,15.))
        server.physics.trace_segment.side_effect = lambda origin,end,**kw: {
            'hit':end==exposed.pos,'entity_id':exposed.net_id if end==exposed.pos else 0}
        server.bots._decide(bot,100)
        self.assertEqual(bot.target_id,exposed.net_id)
        self.assertNotEqual(bot.target_id,blocked.net_id)
        self.assertEqual(bot.entity.actions[8],1.)

    def test_nearby_route_waypoint_does_not_count_as_objective_arrival(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        bot.next_plan_at = 200
        bot.goal = (4500.,2500.)
        server.bots.navigation.waypoint = Mock(return_value=(510.,2500.))
        server.bots._decide(bot,100)
        self.assertTrue(bot.wants_move)
        self.assertGreater(bot.entity.actions[2],0.)
        bot.progress_check_at = 101
        bot.progress_position = bot.entity.pos
        server.bots._decide(bot,104)
        self.assertGreater(bot.recovery_until,104)
        self.assertLess(bot.entity.actions[2],0.)


if __name__ == '__main__': unittest.main()
