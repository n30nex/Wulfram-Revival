"""Bounded real TCP/UDP journeys against native physics on loopback only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import argparse
import contextlib
import hashlib
import json
import os
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clients', type=int, choices=range(1, 17), default=8)
    parser.add_argument('--seconds', type=int, choices=range(5, 16), default=8)
    parser.add_argument('--switch-team', action='store_true')
    args = parser.parse_args()
    if args.switch_team and args.clients > 8:
        parser.error('team-switch checks need free places; use at most eight clients')
    log_path = args.output.with_suffix('.log')
    if args.output.suffix != '.json' or any(path.exists() or path.is_symlink() for path in (args.output, log_path)):
        parser.error('output and companion log must be fresh paths, with .json output')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve both protocols until immediately before the private server binds.
    tcp, udp = socket.socket(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        tcp.bind(('127.0.0.1', 0))
        port = tcp.getsockname()[1]
        udp.bind(('127.0.0.1', port))
    finally:
        tcp.close()
        udp.close()
    began = time.monotonic()
    report = {'passed': False, 'timing_qualified': False, 'mode': 'loopback_native', 'clients': args.clients,
              'switch_team': args.switch_team, 'world_sample_seconds': args.seconds,
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'source_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'probe_sha256': hashlib.sha256((ROOT/'scripts/check-online.py').read_bytes()).hexdigest(),
              'peak_sessions': 0, 'journeys': []}
    with tempfile.TemporaryDirectory(prefix='wulfram-network-') as temporary, \
            log_path.open('x', encoding='utf-8') as log, contextlib.redirect_stdout(log):
        cfg = Config()
        cfg = replace(cfg,
            game=replace(cfg.game, map_name='crossroads', map_rotation=('crossroads',), bots_per_team=32, player_limit=80),
            network=replace(cfg.network, host='127.0.0.1', server_ip='127.0.0.1', tcp_port=port, udp_port=port),
            runtime=replace(cfg.runtime, state_directory=Path(temporary)/'state', log_directory=Path(temporary)/'logs'))
        hooks = ProductionHooks(cfg, {'WULFRAM_SERVER_PASSWORD': 'background-player',
                                      'WULFRAM_SERVER_ADMIN_PASSWORD': 'background-admin'})
        server = app.WulframServerContext(cfg, PacketConfig.load(str(args.content_root/'packets.toml'), strict=True),
                                         content_root=args.content_root, hooks=hooks)
        startup_errors = []
        def serve():
            try:
                server.run()
            except Exception as error:
                startup_errors.append(type(error).__name__)
        worker = threading.Thread(target=serve, daemon=True)
        environment = dict(os.environ, WULFRAM_PROBE_PASSWORD='background-player')
        def probe(index):
            time.sleep(index*.4)  # Respect the four unauthenticated peers/IP limit.
            command = [sys.executable, str(ROOT/'scripts/check-online.py'), '--host', '127.0.0.1',
                       '--expected-ip', '127.0.0.1', '--port', str(port), '--bots', '64',
                       '--team-capacity', '40', '--team', str(1+index%2), '--seconds', str(args.seconds), '--drive']
            if args.switch_team:
                command.append('--switch-team')
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60+args.seconds*2)
            document = json.loads(result.stdout)
            document['exit_code'] = result.returncode
            return document
        try:
            worker.start()
            deadline = time.monotonic()+20
            runtime = cfg.runtime.state_directory/'runtime.json'
            while not runtime.exists() or json.loads(runtime.read_text())['status'] != 'ready':
                if startup_errors or not worker.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError('private server did not become ready')
                time.sleep(.1)
            report['native_sha256'] = hashlib.sha256(Path(server.physics._native.__file__).read_bytes()).hexdigest()
            entries = [{'path': 'content/'+path.relative_to(args.content_root).as_posix(),
                        'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in sorted(args.content_root.rglob('*'), key=lambda p: p.relative_to(args.content_root).as_posix()) if path.is_file()]
            report['content_identity'] = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
            with ThreadPoolExecutor(max_workers=args.clients) as pool:
                futures = [pool.submit(probe, index) for index in range(args.clients)]
                while not all(future.done() for future in futures):
                    report['peak_sessions'] = max(report['peak_sessions'], len(server.sessions))
                    time.sleep(.1)
                report['journeys'] = [future.result() for future in futures]
            deadline = time.monotonic()+3
            while any(not getattr(s, 'is_bot', False) for s in server.sessions) and time.monotonic() < deadline:
                time.sleep(.05)
            report.update(bots=len(server.bots.bots), remaining_sessions=len(server.sessions),
                          remaining_udp_peers=len(server.udp_sessions), physics_ticks=server.physics.metrics.ticks,
                          dropped_ticks=server.physics.metrics.dropped_catch_up_ticks)
            report['passed'] = (not server.fatal_error and not startup_errors and report['bots'] == 64
                and report['peak_sessions'] == 64+args.clients and report['remaining_sessions'] == 64
                and report['remaining_udp_peers'] == 0
                and all(row['passed'] and row['clean_disconnect'] and row['exit_code'] == 0 for row in report['journeys']))
        except Exception as error:
            report['error_type'] = type(error).__name__
            raise
        finally:
            server.shutdown()
            worker.join(timeout=5)
            report['server_stopped'] = not worker.is_alive()
            report['passed'] &= report['server_stopped']
            report['elapsed_seconds'] = round(time.monotonic()-began, 3)
            args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'journeys'}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
