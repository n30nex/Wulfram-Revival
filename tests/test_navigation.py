from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from wulfram_server.navigation import TerrainRoutes


def ridge(with_gap=True):
    heights = [[0.0]*9 for _ in range(9)]
    for y in range(6 if with_gap else 9): heights[y][4] = 100.0
    return SimpleNamespace(width=9,height=9,cell_size_x=10.,cell_size_y=10.,heights=heights)


class NavigationTests(unittest.TestCase):
    def test_tactical_goals_keep_clearance_from_the_world_boundary(self):
        routes = TerrainRoutes(ridge())
        goal = routes.reachable_near((15.,65.),(-200.,65.))
        self.assertGreaterEqual(goal[0],15.)
        self.assertFalse(routes.clear_line((15.,65.),(-200.,65.)))

    def test_route_goes_around_ridge_without_cutting_corners(self):
        routes = TerrainRoutes(ridge())
        position,goal = (15.,15.),(65.,15.)
        self.assertFalse(routes.clear_line(position,goal))
        visited = [position]
        for _ in range(30):
            next_point = routes.waypoint(position,[goal])
            self.assertIsNotNone(next_point)
            self.assertTrue(routes.clear_line(position,next_point))
            visited.append(next_point)
            position = next_point
            if position == goal: break
        self.assertEqual(position,goal)
        self.assertGreaterEqual(max(point[1] for point in visited),65)

    def test_unreachable_goal_does_not_send_bot_into_the_ridge(self):
        routes = TerrainRoutes(ridge(False))
        self.assertIsNone(routes.waypoint((15.,15.),[(65.,15.)]))

    def test_final_approach_reaches_pad_instead_of_cell_centre(self):
        routes = TerrainRoutes(ridge())
        self.assertEqual(routes.waypoint((12.,12.),[(18.,18.)]),(18.,18.))

    def test_teammates_share_fields_and_can_exit_an_unsafe_cell(self):
        routes = TerrainRoutes(ridge())
        goals = [(65.,15.),(65.,25.)]
        self.assertIs(routes.field(goals),routes.field(list(reversed(goals))))
        self.assertEqual(len(routes.fields),1)
        point = routes.waypoint((39.,20.),goals)
        self.assertIsNotNone(point)
        self.assertTrue(routes.safe[routes.cell(point)])


if __name__ == '__main__': unittest.main()
