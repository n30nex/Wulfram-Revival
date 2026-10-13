"""Replay bounded native deployment scenarios without a window or listening port.

The simulation clock advances at loop waits. This checks decisions/physics;
it deliberately cannot qualify real-time performance, network clients or uptime.
"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import argparse
import contextlib
import hashlib
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.hooks import ProductionHooks
from wulfram_server.network.packets.packet_config import PacketConfig


class ScenarioClock:
    """The game loop's stop event advances a process-local test clock."""
    def __init__(self, phase, seconds, sample):
        self.now, self.end = float(phase), phase+seconds
        self.sample = sample
        self.next_sample = self.now
        self.done = False
        self.iterations = 0

    def is_set(self):
        return self.done or self.now >= self.end

    def set(self):
        self.done = True

    def wait(self, seconds):
        self.iterations += 1
        if self.iterations > 30000:
            raise RuntimeError('scenario loop exceeded its work bound')
        self.now += max(1e-6,seconds)
        if self.now >= self.next_sample:
            self.next_sample = self.now+1
            self.sample(self.now)
        return self.is_set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--map',choices=('crossroads','mayhem','frontier'),default='mayhem')
    parser.add_argument('--phase',type=int,default=1000)
    parser.add_argument('--seconds',type=int,choices=range(10,121),default=75,metavar='10..120')
    args = parser.parse_args()
    if args.output.suffix != '.json':
        parser.error('output must be a new .json report')
    if not 0 <= args.phase <= 86400:
        parser.error('phase must be between 0 and 86400')
    log_path = args.output.with_suffix('.log')
    if any(path.exists() or path.is_symlink() for path in (args.output,log_path)):
        raise ValueError('refusing to overwrite scenario evidence')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    samples = []
    def sample(now):
        terrain = (server.land.identity,server.land.revision)
        samples.append({'seconds':round(now-args.phase,3),
            'waiting_first_by_team':{str(team):sum(bot.is_bot and bot.team==team
                and (bot.spawn_position is None or bot.spawned_terrain != terrain)
                for bot in server.bots.bots) for team in (1,2)}})
    clock = ScenarioClock(args.phase,args.seconds,sample)
    began = time.perf_counter()
    report = {'mode':'simulation_clock','timing_qualified':False,'passed':False,
              'map':args.map,'phase':args.phase,'requested_simulated_seconds':args.seconds,
              'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix='wulfram-deployment-') as temporary, \
            log_path.open('x') as log,contextlib.redirect_stdout(log), \
            patch.object(time,'monotonic',side_effect=lambda:clock.now):
        cfg = Config()
        cfg = replace(cfg,game=replace(cfg.game,map_name=args.map,map_rotation=(args.map,),bots_per_team=32,player_limit=80),
            runtime=replace(cfg.runtime,state_directory=Path(temporary)/'state',log_directory=Path(temporary)/'logs'))
        hooks = ProductionHooks(cfg,{'WULFRAM_SERVER_PASSWORD':'benchmark-player',
                                    'WULFRAM_SERVER_ADMIN_PASSWORD':'benchmark-admin'})
        server = app.WulframServerContext(cfg,PacketConfig.load(str(args.content_root/'packets.toml'),strict=True),
                                         content_root=args.content_root,hooks=hooks)
        try:
            server.stop_update_event = clock
            hooks.start(server)
            for index in range(16):
                client = server.bots.add(name=f'LoadClient{index+1}')
                client.is_bot = False
                client.udp_context = SimpleNamespace(send=lambda packet:None)
            app.global_game_loop(server)
            complete = [row['seconds'] for row in samples if not any(row['waiting_first_by_team'].values())]
            report.update(simulated_seconds=round(clock.now-args.phase,3),
                physics_ticks=server.physics.metrics.ticks,bots=sum(bot.is_bot for bot in server.bots.bots),
                simulated_clients=16,first_all_deployed_seconds=next(iter(complete),None),samples=samples,
                native_sha256=hashlib.sha256(Path(server.physics._native.__file__).read_bytes()).hexdigest())
            report['passed'] = (clock.now >= clock.end and not server.fatal_error
                                and report['bots']==64 and bool(complete))
        except Exception as error:
            report.update(error_type=type(error).__name__)
            raise
        finally:
            clock.set()
            server.tcp_sock.close()
            server.udp_sock.close()
            report['wall_seconds'] = round(time.perf_counter()-began,3)
            args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='samples'},indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
