"""Bounded real native-client lifecycle check with targeted private-server loss."""
import argparse
import contextlib
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'server'))
from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.core.entity import UpdateMask
from wulfram_server.hooks import ProductionHooks, NullTrace
from wulfram_server import admin_commands
from wulfram_server.network.packets.packet_config import PacketConfig


def scoped_body(payload):
    # Independent inspection of the documented native header, for fault injection.
    if payload[:1] == b'\x50' and len(payload) >= 24:
        _, connection, epoch, owner, sequence, size = struct.unpack_from('>BQIIIH', payload)
        if len(payload) == 23+size:
            return connection, epoch, owner, sequence, payload[23:]
    return 0, 0, 0, 0, payload


class LifecycleTrace(NullTrace):
    def __init__(self, hooks): self.hooks = hooks
    def packet(self, direction, transport, payload, *, addr=None, **_options):
        h = self.hooks
        if h.target is None:
            return
        connection, epoch, owner, sequence, body = scoped_body(payload)
        if not body:
            return
        if direction == 'client_to_server' and transport == 'UDP' and addr == h.target.udp_addr and body[0] == 0x0A:
            if owner == h.spawned[0] and h.old_input is None:
                h.old_input = payload
            elif len(h.spawned) >= 2 and owner == h.spawned[1] and h.second_input is None:
                h.second_input = payload
        if direction != 'server_to_client':
            return
        if transport == 'TCP' and addr == h.target.address:
            if body[0] == 0x18 and owner == h.spawned[0] and h.old_tank is None:
                h.old_tank = payload
            if body[0] == 0x15 and len(body) >= 11 and struct.unpack_from('>I', body, 6)[0] == h.killed:
                h.tcp_deletes += 1
                h.old_delete = payload
        if transport == 'UDP' and addr == h.target.udp_addr and body[0] == 0x0F:
            if epoch == 1 and owner == h.spawned[0] and h.old_world is None:
                h.old_world = payload
            elif len(h.spawned) >= 3 and owner == h.spawned[2] and h.previous_connection is None:
                h.previous_connection = payload


class LifecycleHooks(ProductionHooks):
    def __init__(self, cfg, environment, next_map=None):
        super().__init__(cfg, environment)
        self.spawned_at = 0.0
        self.killed = 0
        self.dropped_deletes = 0
        self.tcp_deletes = 0
        self.target = None
        self.spawned = []
        self.next_map = next_map
        self.old_input = self.second_input = self.old_tank = self.old_delete = None
        self.old_world = self.previous_connection = None
        self.second_released = False
        self.replayed_inputs = self.replayed_map = self.replayed_connection = False
        self.bad_input_applied = False
        self.raw_send = None

    def create_trace(self): return LifecycleTrace(self)

    def entity_spawned(self, session, entity, source):
        if session.name == 'ModernLifecycleCheck':
            self.target = session
            self.spawned.append(entity.net_id)
            if not self.spawned_at:
                self.spawned_at = time.monotonic()

    def process_system_command(self, context, message):
        if message == '/s lifecycle-map' and context.session.name == 'ModernLifecycleCheck' and self.next_map:
            context.server.admin_command_queue.put_nowait(admin_commands.MapChangeRequest(None, self.next_map, 'native lifecycle check'))
            return True
        return super().process_system_command(context, message)

    def action_packet(self, context, packet_name, opcode, decoded_actions):
        if len(self.spawned) < 2 or context.session is not self.target or self.target.entity is None:
            return
        if self.target.entity.net_id == self.spawned[1]:
            forward = next((new for channel, _old, new in decoded_actions if channel == 2), 0)
            if forward > .5:
                self.second_released = True
            elif self.second_released and forward <= 0:
                self.bad_input_applied = True

    def before_game_loop_iteration(self, server):
        super().before_game_loop_iteration(server)
        session = self.target
        if (not self.killed and self.spawned_at and time.monotonic() >= self.spawned_at+.5
                and session is not None and session.entity is not None):
            entity = session.entity
            self.killed = entity.net_id
            entity.health_points = 0.0
            entity.health = 0.0
            entity.mark_dirty(UpdateMask.HEALTH)
            app._destroy_authoritative_entity(server, entity, explosion=True)
        if not self.next_map or session is None or session.stop_ping_event.is_set():
            return
        if self.second_released and not self.replayed_inputs and self.old_input and self.second_input:
            self.replayed_inputs = True
            server._receive_datagram(self.old_input, session.udp_addr)
            server._receive_datagram(self.second_input, session.udp_addr)
        if len(self.spawned) >= 3 and not self.replayed_map and self.old_tank and self.old_delete and self.old_world:
            self.replayed_map = True
            for packet in (self.old_tank, self.old_delete, self.old_world):
                self.raw_send(packet, session.udp_addr)
        if len(self.spawned) >= 4 and not self.replayed_connection and self.previous_connection:
            self.replayed_connection = True
            self.raw_send(self.previous_connection, session.udp_addr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', type=Path, required=True)
    parser.add_argument('--content-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map-content-root', type=Path)
    parser.add_argument('--next-map', choices=('mayhem', 'frontier'), default='mayhem')
    args = parser.parse_args()
    log_path = args.output.with_suffix('.log')
    if args.output.exists() or log_path.exists():
        parser.error('use fresh report/log paths')
    with socket.socket() as tcp, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        tcp.bind(('127.0.0.1', 0)); port = tcp.getsockname()[1]
        udp.bind(('127.0.0.1', port))
    report = {'passed': False}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='wulfram-lifecycle-') as temporary, \
            log_path.open('x', encoding='utf-8') as log, contextlib.redirect_stdout(log):
        temporary_root = Path(temporary).resolve()
        assert temporary_root.is_relative_to(Path(tempfile.gettempdir()).resolve()) and temporary_root.name.startswith('wulfram-lifecycle-')
        content = args.content_root
        if args.map_content_root:
            content = temporary_root/'content'
            shutil.copytree(args.content_root, content)
            shutil.copytree(args.map_content_root/'shared/data/maps'/args.next_map, content/'shared/data/maps'/args.next_map)
        cfg = Config()
        cfg = replace(cfg,
            game=replace(cfg.game, map_name='crossroads', map_rotation=('crossroads',), bots_per_team=32, player_limit=80),
            network=replace(cfg.network, host='127.0.0.1', server_ip='127.0.0.1', tcp_port=port, udp_port=port),
            runtime=replace(cfg.runtime, state_directory=Path(temporary)/'state', log_directory=Path(temporary)/'logs'))
        hooks = LifecycleHooks(cfg, {'WULFRAM_SERVER_PASSWORD': 'private-client-test',
                                    'WULFRAM_SERVER_ADMIN_PASSWORD': 'private-unused-admin'}, args.next_map if args.map_content_root else None)
        server = app.WulframServerContext(cfg, PacketConfig.load(str(content/'packets.toml'), strict=True),
                                         content_root=content, hooks=hooks)
        def lose_owner_delete(payload, address):
            target = next((s for s in tuple(server.sessions) if s.name == 'ModernLifecycleCheck'), None)
            body = scoped_body(payload)[4]
            if (target and address == target.udp_addr and body[:1] == b'\x15'
                    and len(body) >= 11 and struct.unpack_from('>I', body, 6)[0] == hooks.killed):
                hooks.dropped_deletes += 1
                return
            send(payload, address)
        worker = threading.Thread(target=server.run, daemon=True)
        try:
            worker.start()
            deadline = time.monotonic()+20
            runtime = cfg.runtime.state_directory/'runtime.json'
            while not runtime.exists() or json.loads(runtime.read_text())['status'] != 'ready':
                if not worker.is_alive() or time.monotonic() >= deadline:
                    raise RuntimeError('private server did not start')
                time.sleep(.05)
            send = server.udp_transport.send
            hooks.raw_send = send
            server.udp_transport.send = lose_owner_delete
            env = dict(os.environ, WULFRAM_TEST_PORT=str(port), WULFRAM_TEST_JOIN_CODE='private-client-test',
                       WULFRAM_TEST_NEXT_MAP=args.next_map if args.map_content_root else '')
            result = subprocess.run([str(args.godot.resolve()), '--headless', '--path', str(ROOT/'client/modern'),
                                     '--script', 'res://check_lifecycle.gd'], env=env, capture_output=True, text=True, timeout=50)
            log.write(result.stdout+result.stderr)
            rows = [line for line in result.stdout.splitlines() if line.startswith('MODERN_LIFECYCLE ')]
            report['client'] = json.loads(rows[-1].split(' ',1)[1]) if rows else {'passed': False}
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                with server.physics._lock:
                    remaining_bodies = sum(id in server.physics._tracked_entities for id in hooks.spawned)
                if not remaining_bodies and not any(not getattr(s, 'is_bot', False) for s in server.sessions):
                    break
                time.sleep(.02)
            report.update(killed=hooks.killed, dropped_owner_deletes=hooks.dropped_deletes,
                          reliable_owner_deletes=hooks.tcp_deletes, replayed_old_inputs=hooks.replayed_inputs,
                          replayed_old_map=hooks.replayed_map, replayed_old_connection=hooks.replayed_connection,
                          stale_input_applied=hooks.bad_input_applied,
                          remaining_player_entities=sum(server.entities.get_entity(id) is not None for id in hooks.spawned),
                          remaining_player_bodies=remaining_bodies,
                          remaining_sessions=len(server.sessions), remaining_udp_peers=len(server.udp_sessions),
                          dropped_catch_up_ticks=server.physics.metrics.dropped_catch_up_ticks)
            report['passed'] = (result.returncode == 0 and 'ERROR:' not in result.stderr and report['client']['passed']
                                and hooks.killed != 0 and len(server.sessions) == 64 and not server.udp_sessions)
            report['passed'] &= report['remaining_player_entities'] == 0 and remaining_bodies == 0 and not server.fatal_error
            if args.map_content_root:
                report['passed'] &= (hooks.tcp_deletes > 0 and hooks.replayed_inputs and hooks.replayed_map
                                     and hooks.replayed_connection and not hooks.bad_input_applied)
        finally:
            server.shutdown(); worker.join(timeout=5)
            report['server_stopped'] = not worker.is_alive()
            report['passed'] &= report['server_stopped']
            report['seconds'] = round(time.monotonic()-started,3)
            args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
