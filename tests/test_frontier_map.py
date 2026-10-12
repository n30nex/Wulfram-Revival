import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

from test_bots import ROOT
from wulfram_server.core.land import LandMap
from wulfram_server.core.map_loader import MapLoader
from wulfram_server.core.entity_manager import EntityManager

spec = importlib.util.spec_from_file_location("frontier", ROOT / "scripts/build-frontier-map.py")
frontier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontier)


class FrontierMapTests(unittest.TestCase):
    def test_generated_map_is_balanced_and_all_pads_are_on_level_terrain(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = frontier.generate(Path(temporary) / "frontier")
            land, entities = LandMap(), EntityManager()
            with contextlib.redirect_stdout(io.StringIO()):
                land.load(folder / "land")
                MapLoader(entities).load_from_string((folder / "state").read_text())
            self.assertTrue(land.loaded)
            self.assertEqual((land.width, land.height), (129, 129))
            for row in land.heights:
                self.assertEqual(row, list(reversed(row)))
            for team in (1, 2):
                pads = [entity for entity in entities.get_all() if entity.unit_type == 27 and entity.team_id == team]
                self.assertEqual(len(pads), 8)
                for pad in pads:
                    self.assertEqual(pad.pos[2], 25)
                    self.assertEqual(land.get_height(*pad.pos[:2]), 25)
            self.assertEqual(sum(entity.unit_type == 19 for entity in entities.get_all()), 6)
            self.assertEqual(len((folder / "tagmap2").read_text().splitlines()), 3)
            with self.assertRaises(FileExistsError):
                frontier.generate(folder)


if __name__ == "__main__":
    unittest.main()
