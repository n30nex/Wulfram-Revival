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

    def test_boundary_patrol_cannot_arrive_while_still_blocking_a_spawn_pad(self):
        # Match Mayhem's cell size and near-boundary repair pads. A patrol
        # clamped to the first safe column used to leave a guard on its pad.
        for team,position,slot in ((1,(100.,3380.,4.),10),(2,(5474.,3315.,4.),6)):
            for phase in range(2):
                with self.subTest(team=team,phase=phase):
                    server,_ = self.arena(0)
                    pad = next(unit for unit in server.entities.get_all() if unit.team_id==team)
                    pad.pos = position
                    server.land = SimpleNamespace(loaded=True,identity='edge',revision=1,width=129,height=129,
                        cell_size_x=43.75,cell_size_y=43.75,heights=[[0.]*129 for _ in range(129)])
                    server.bots.prepare_navigation()
                    guard = server.bots.add(team=team,loadout='scout')
                    guard.role,guard.tactical_slot = 'guard',slot
                    guard.entity.pos = position
                    now = 18*phase
                    server.bots._decide(guard,now)
                    self.assertIsNotNone(guard.goal)
                    self.assertGreaterEqual(math.dist(guard.goal,pad.pos[:2]),80)
                    self.assertTrue(guard.wants_move)
                    self.assertTrue(server.bots.navigation.safe[server.bots.navigation.cell(guard.goal)])
                    # Even the nearest accepted arrival point leaves a clear pad.
                    self.assertGreater(math.dist(guard.goal,pad.pos[:2])-35,20)

    def test_guard_rejects_a_patrol_point_that_would_block_another_friendly_pad(self):
        server,_ = self.arena(3)
        guard = server.bots.bots[2]
        home = next(unit for unit in server.entities.get_all() if unit.unit_type==27 and unit.team_id==1)
        now = 0
        server.bots._plan(guard,now,[])
        old_goal = guard.goal
        second = server.entities.create_entity(27,1,(*old_goal,0.))
        server.bots._plan(guard,now,[])
        for pad in (home,second):
            self.assertGreaterEqual(math.dist(guard.goal,pad.pos[:2]),80)

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
        self.assertEqual(bot.entity.actions[8],0.)
        server.bots._decide(bot,101)
        self.assertEqual(bot.entity.actions[8],1.)

    def test_reacquiring_a_target_requires_another_reaction_delay(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        enemy = server.entities.create_entity(0,2,(600.,2500.,15.))
        server.physics.trace_segment.return_value = {'hit':True,'entity_id':enemy.net_id}
        server.bots._decide(bot,100)
        self.assertEqual(bot.entity.actions[8],0.)
        server.bots._decide(bot,101)
        self.assertEqual(bot.entity.actions[8],1.)
        server.physics.trace_segment.return_value = {'hit':False,'entity_id':0}
        server.bots._decide(bot,102)
        server.physics.trace_segment.return_value = {'hit':True,'entity_id':enemy.net_id}
        server.bots._decide(bot,103)
        self.assertEqual(bot.entity.actions[8],0.)
        server.bots._decide(bot,104)
        self.assertEqual(bot.entity.actions[8],1.)

    def test_outnumbered_bot_regroups_then_resumes_its_job(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        bot.entity.pos = (1000.,2500.,15.)
        bot.entity.rot = (0.,0.,math.pi)
        enemies = [server.entities.create_entity(0,2,(1300.,2500.+i*20,15.)) for i in range(3)]
        server.physics.trace_segment.side_effect = lambda origin,end,**kw: {
            'hit':True,'entity_id':next(unit.net_id for unit in enemies if unit.pos==end)}
        server.bots._decide(bot,100)
        self.assertEqual(bot.order,'regroup')
        self.assertLess(bot.goal[0],1000)
        self.assertTrue(bot.wants_move)
        self.assertGreater(bot.entity.actions[2],0)
        self.assertEqual(bot.entity.actions[8],0.)
        server.physics.trace_segment.side_effect = None
        server.physics.trace_segment.return_value = {'hit':False,'entity_id':0}
        server.bots._decide(bot,101)
        self.assertEqual(bot.order,'regroup')
        server.bots._decide(bot,105)
        self.assertEqual(bot.order,'assault')

    def test_hidden_opponents_do_not_trigger_a_retreat(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        enemies = [server.entities.create_entity(0,2,(700.,2500.+i*20,15.)) for i in range(3)]
        server.physics.trace_segment.return_value = {'hit':True,'entity_id':enemies[0].net_id}
        server.bots._decide(bot,100)
        self.assertEqual(bot.order,'assault')
        self.assertEqual(bot.regroup_until,0)

    def test_nearby_route_waypoint_does_not_count_as_objective_arrival(self):
        server, _ = self.arena(1)
        bot = server.bots.bots[0]
        bot.next_plan_at = 200
        bot.progress_check_at = 101
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

    def test_repeated_stall_tries_the_opposite_escape_direction(self):
        server,_ = self.arena(1)
        bot = server.bots.bots[0]
        bot.next_plan_at = 200
        bot.goal = (4500.,2500.)
        bot.progress_position = bot.entity.pos
        bot.progress_check_at = 100
        server.bots._decide(bot,100)
        first = bot.entity.actions[3]
        self.assertEqual(bot.entity.actions[5],0.)
        self.assertLess(bot.entity.actions[2],0)
        server.bots._decide(bot,101.3)
        self.assertEqual(bot.entity.actions[5],1.)
        server.bots._decide(bot,103)
        self.assertEqual(bot.entity.actions[3],-first)
        self.assertLess(bot.entity.actions[2],0)
        self.assertEqual(bot.entity.actions[5],0.)
        self.assertGreater(bot.next_jump_at,103)


if __name__ == '__main__': unittest.main()
