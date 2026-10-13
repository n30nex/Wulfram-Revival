from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest

from test_bots import make_server
from wulfram_server.operations import write_qualification_status

SOAK = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/qualify-soak.py'))


class SoakTests(unittest.TestCase):
    def sample(self, seconds=0, **overrides):
        return dict({'git_commit':'a'*40,'process_id':10,'updated_utc':datetime.now(timezone.utc).isoformat(),
                     'bots':64,'sessions':64,'live_bots':62,'spawned_bots':64,'route_fields':80,'map':'crossroads',
                     'changing_map':False,'physics_ticks':int(seconds*25),'dropped_ticks':0,
                     'rss_bytes':100*1024*1024,'elapsed_seconds':seconds},**overrides)

    def test_restarts_and_stale_snapshots_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'sample.json'
            path.write_text(json.dumps(self.sample()))
            self.assertEqual(SOAK['read_sample'](path,'a'*40,10)['bots'],64)
            with self.assertRaises(ValueError): SOAK['read_sample'](path,'b'*40,10)
            with self.assertRaises(ValueError): SOAK['read_sample'](path,'a'*40,11)
            old = (datetime.now(timezone.utc)-timedelta(seconds=30)).isoformat()
            path.write_text(json.dumps(self.sample(updated_utc=old)))
            with self.assertRaises(ValueError): SOAK['read_sample'](path,'a'*40,10)

    def test_short_runs_and_memory_growth_cannot_pass(self):
        samples = [self.sample(),self.sample(300,map='mayhem'),self.sample(600,map='frontier')]
        self.assertFalse(SOAK['assess'](samples,600,32)['passed'])
        samples.append(self.sample(86400))
        self.assertTrue(SOAK['assess'](samples,86400,32)['passed'])
        samples[1]['spawned_bots'] = 63
        self.assertFalse(SOAK['assess'](samples,86400,32)['passed'])
        samples[1]['spawned_bots'] = 64
        samples[-1]['rss_bytes'] *= 3
        self.assertFalse(SOAK['assess'](samples,86400,32)['passed'])

    def test_private_export_is_bounded_and_omits_player_identity(self):
        server = make_server()
        server.bots.add('Private Callsign',1)
        server.release_identity = SimpleNamespace(git_commit='a'*40)
        server.current_map_name = 'crossroads'
        server.physics.metrics = SimpleNamespace(ticks=55,dropped_catch_up_ticks=1)
        with tempfile.TemporaryDirectory() as directory:
            server.cfg = SimpleNamespace(runtime=SimpleNamespace(state_directory=Path(directory)))
            for _ in range(3): write_qualification_status(server)
            self.assertEqual(len(list(Path(directory).iterdir())),1)
            raw = (Path(directory)/'qualification.json').read_text()
            self.assertNotIn('Private Callsign',raw)
            self.assertNotIn('address',raw)
            self.assertEqual(json.loads(raw)['physics_ticks'],55)


if __name__ == '__main__': unittest.main()
