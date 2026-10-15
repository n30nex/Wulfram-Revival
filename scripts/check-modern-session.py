"""Bounded native-client and legacy-probe coexistence with 64 bots on loopback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server'))
from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.hooks import ProductionHooks
from wulfram_server.network.packets.packet_config import PacketConfig


class TestHooks(ProductionHooks):
    def __init__(self, cfg, environment):
        super().__init__(cfg, environment)
        self.observed = set()
        self.precise_values = []
        self.formats = set()
        self.combat_formats = set()

    def action_packet(self, context, packet_name, opcode, decoded_actions):
        self.formats.add(context.session.precise_actions)
        self.combat_formats.add(context.session.combat_events)
        if context.session.name != 'ModernCombatCheck':
            return
        for channel, _old, value in decoded_actions:
            if value:
                self.observed.add(channel)
            if channel == 6 and 0 < value < .002:
                self.precise_values.append(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', type=Path, required=True)
    parser.add_argument('--content-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--journey', choices=('combat', 'communications', 'capacity'), default='combat')
    args = parser.parse_args()
    log_path = args.output.with_suffix('.log')
    if any(p.exists() for p in (args.output, log_path)):
        parser.error('report and log must be fresh files')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with socket.socket() as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        tcp.bind(('127.0.0.1', 0))
        port = tcp.getsockname()[1]
        udp.bind(('127.0.0.1', port))
    report = {'passed': False, 'physical_display_qualified': False, 'journey': args.journey,
              'peak_sessions': 0, 'peak_human_vehicles': 0}
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='wulfram-modern-') as temporary, \
            log_path.open('x', encoding='utf-8') as log, contextlib.redirect_stdout(log):
        cfg = Config()
        cfg = replace(cfg,
            game=replace(cfg.game, map_name='crossroads', map_rotation=('crossroads',), bots_per_team=32, player_limit=80),
            network=replace(cfg.network, host='127.0.0.1', server_ip='127.0.0.1', tcp_port=port, udp_port=port),
            runtime=replace(cfg.runtime, state_directory=Path(temporary)/'state', log_directory=Path(temporary)/'logs'))
        hooks = TestHooks(cfg, {'WULFRAM_SERVER_PASSWORD': 'private-client-test',
                                'WULFRAM_SERVER_ADMIN_PASSWORD': 'private-unused-admin'})
        server = app.WulframServerContext(cfg, PacketConfig.load(str(args.content_root/'packets.toml'), strict=True),
                                         content_root=args.content_root, hooks=hooks)
        worker = threading.Thread(target=server.run, daemon=True)
        environment = dict(os.environ, WULFRAM_TEST_PORT=str(port), WULFRAM_TEST_JOIN_CODE='private-client-test',
                           WULFRAM_PROBE_PASSWORD='private-client-test')
        def modern():
            script = {'communications': 'check_comms_session.gd', 'capacity': 'check_capacity.gd'}.get(args.journey, 'check_session.gd')
            run = subprocess.run([str(args.godot.resolve()), '--headless', '--path', str(ROOT/'client/modern'),
                                  '--script', 'res://'+script], env=environment,
                                 capture_output=True, text=True, timeout=40)
            log.write(run.stdout + run.stderr)
            rows = [line for line in run.stdout.splitlines() if line.startswith('MODERN_SESSION ')]
            result = json.loads(rows[-1].split(' ', 1)[1]) if rows else {'passed': False}
            result['exit_code'] = run.returncode
            result['passed'] &= run.returncode == 0 and 'ERROR:' not in run.stderr
            return result
        def legacy():
            run = subprocess.run([sys.executable, str(ROOT/'scripts/check-online.py'), '--host', '127.0.0.1',
                '--expected-ip', '127.0.0.1', '--port', str(port), '--bots', '64', '--team-capacity', '40',
                '--team', '1', '--seconds', '30' if args.journey == 'capacity' else '8', '--drive', '--callsign', 'LegacyCoexistence'],
                env=environment, capture_output=True, text=True, timeout=55 if args.journey == 'capacity' else 40)
            result = json.loads(run.stdout)
            result['exit_code'] = run.returncode
            return result
        try:
            worker.start()
            deadline = time.monotonic() + 20
            runtime = cfg.runtime.state_directory/'runtime.json'
            while not runtime.exists() or json.loads(runtime.read_text())['status'] != 'ready':
                if not worker.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError('private server startup failed')
                time.sleep(.1)
            report['native_sha256'] = hashlib.sha256(Path(server.physics._native.__file__).read_bytes()).hexdigest()
            projectiles, projectile_ids = set(), set()
            with ThreadPoolExecutor(max_workers=2) as pool:
                modern_result, legacy_result = pool.submit(modern), pool.submit(legacy)
                while not (modern_result.done() and legacy_result.done()):
                    sessions = tuple(server.sessions)
                    report['peak_sessions'] = max(report['peak_sessions'], len(sessions))
                    report['peak_human_vehicles'] = max(report['peak_human_vehicles'], sum(
                        not getattr(s, 'is_bot', False) and (live_entity := s.entity) is not None and live_entity.is_manned and live_entity.health_points > 0
                        for s in sessions))
                    players = [s for s in tuple(server.sessions) if s.name == 'ModernCombatCheck']
                    for session in players:
                        for entity in server.entities.get_all():
                            if entity.unit_type == 6 and entity.score_owner_id == session.player_id:
                                projectiles.add(entity.projectile_kind)
                                projectile_ids.add(entity.net_id)
                    time.sleep(.02)
                report['modern'], report['legacy'] = modern_result.result(), legacy_result.result()
            deadline = time.monotonic() + 3
            while any(not getattr(s, 'is_bot', False) for s in server.sessions) and time.monotonic() < deadline:
                time.sleep(.05)
            report.update(observed_actions=sorted(hooks.observed), action_formats=sorted(hooks.formats),
                          combat_formats=sorted(hooks.combat_formats),
                          fine_aim_samples=len(hooks.precise_values), projectile_kinds=sorted(projectiles),
                          remaining_sessions=len(server.sessions), remaining_udp_peers=len(server.udp_sessions),
                          dropped_catch_up_ticks=server.physics.metrics.dropped_catch_up_ticks)
            report['passed'] = (report['modern']['passed'] and report['legacy']['passed']
                and report['legacy']['clean_disconnect'] and report['legacy']['exit_code'] == 0
                and len(server.sessions) == 64
                and len(server.udp_sessions) == 0 and not server.fatal_error)
            if args.journey == 'combat':
                report['passed'] &= (hooks.formats == {False, True} and hooks.combat_formats == {False, True}
                    and len(hooks.precise_values) > 5 and {1, 2, 3, 4, 5, 6, 8, 9, 12, 13} <= hooks.observed
                    and projectiles == {'pulse', 'piercer'}
                    and projectile_ids <= set(report['modern'].get('projectile_event_ids', [])))
            elif args.journey == 'capacity':
                report['passed'] &= report['peak_sessions'] == 80 and report['peak_human_vehicles'] == 16
        finally:
            server.shutdown()
            worker.join(timeout=5)
            report['server_stopped'] = not worker.is_alive()
            report['passed'] &= report['server_stopped']
            report['seconds'] = round(time.monotonic() - began, 3)
            args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'legacy'}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
