"""Exercise real bot spawning, native physics and combat without listening on a port."""
from dataclasses import replace
from collections import deque
from pathlib import Path
import argparse
import contextlib
import json
import math
import statistics
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from wulfram_server import application as app
from wulfram_server.core.config import Config
from wulfram_server.hooks import ProductionHooks
from wulfram_server.network.packets.packet_config import PacketConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=120, choices=range(10, 601), metavar="10..600")
    parser.add_argument("--bots", type=int, default=64, choices=(4, 16, 32, 64))
    parser.add_argument("--clients", type=int, default=0, choices=range(17), metavar="0..16",
                        help="additional bot-driven players with real snapshot serialization and an in-memory transport")
    parser.add_argument("--map", default="crossroads")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wulfram-benchmark-") as temporary:
        root = Path(temporary)
        cfg = Config()
        cfg = replace(cfg,
            game=replace(cfg.game, map_name=args.map, map_rotation=(args.map,),
                         player_limit=80, bots_per_team=args.bots // 2),
            runtime=replace(cfg.runtime, state_directory=root / "state", log_directory=root / "logs"))
        hooks = ProductionHooks(cfg, {"WULFRAM_SERVER_PASSWORD": "benchmark-player",
                                     "WULFRAM_SERVER_ADMIN_PASSWORD": "benchmark-admin"})
        samples, step_seconds = [], []
        traffic = {"datagrams": 0, "bytes": 0, "max_update_bytes": 0}

        def receive_packet(packet):
            payload = packet if isinstance(packet, bytes) else packet.serialize()
            traffic["datagrams"] += 1
            traffic["bytes"] += len(payload)
            if payload and payload[0] in (0x0E, 0x0F):
                traffic["max_update_bytes"] = max(traffic["max_update_bytes"], len(payload))
        with args.output.with_suffix(".log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
            server = app.WulframServerContext(cfg, PacketConfig.load(
                str(args.content_root / "packets.toml"), strict=True), content_root=args.content_root, hooks=hooks)
            try:
                hooks.start(server)
                for index in range(args.clients):
                    client = server.bots.add(name=f"LoadClient{index+1}")
                    client.is_bot = False
                    client.udp_context = SimpleNamespace(send=receive_packet)
                original_step = server.physics.step

                def measured_step(land):
                    started = time.perf_counter()
                    result = original_step(land)
                    step_seconds.append(time.perf_counter() - started)
                    return result

                server.physics.step = measured_step
                started, cpu_started = time.monotonic(), time.process_time()

                def monitor():
                    histories = {}
                    while time.monotonic() - started < args.seconds and not server.stop_update_event.wait(1):
                        live = sum(bot.is_bot and bot.entity is not None and bot.entity.is_manned for bot in server.bots.bots)
                        stalled, engaging = 0, 0
                        for bot in server.bots.bots:
                            if not bot.is_bot: continue
                            history = histories.setdefault(bot.player_id,deque(maxlen=11))
                            entity = bot.entity
                            if entity is None or not entity.is_manned:
                                history.clear(); continue
                            if history and history[-1][0] != entity.net_id: history.clear()
                            history.append((entity.net_id,entity.pos[:2]))
                            engaging += bot.engaging
                            if len(history)==11 and not bot.engaging and math.dist(history[0][1],history[-1][1])<10:
                                stalled += 1
                        samples.append({"seconds": round(time.monotonic() - started, 1), "live_bots": live,
                                        "entities": len(server.entities.get_all()), "ticks": server.physics.metrics.ticks,
                                        "stalled_bots":stalled,"engaging_bots":engaging})
                    server.stop_update_event.set()

                observer = threading.Thread(target=monitor, daemon=True)
                observer.start()
                app.global_game_loop(server)
                observer.join(timeout=2)
                elapsed, cpu_seconds = time.monotonic() - started, time.process_time() - cpu_started
                metrics = server.physics.metrics
                ordered = sorted(step_seconds)
                report = {"bots": sum(bot.is_bot for bot in server.bots.bots), "simulated_clients": args.clients,
                          "traffic": traffic, "map": args.map, "elapsed_seconds": round(elapsed, 3),
                          "cpu_percent_one_core": round(100 * cpu_seconds / elapsed, 2),
                          "physics_ticks": metrics.ticks, "dropped_ticks": metrics.dropped_catch_up_ticks,
                          "peak_live_bots": max((sample["live_bots"] for sample in samples), default=0),
                          "physics_step_p95_ms": round(1000 * ordered[int(.95 * (len(ordered)-1))], 3) if ordered else None,
                          "physics_step_mean_ms": round(1000 * statistics.mean(ordered), 3) if ordered else None,
                          "samples": samples}
                report["passed"] = (report["bots"] == args.bots and metrics.ticks >= .95 * args.seconds * 25
                                    and report["peak_live_bots"] == args.bots
                                    and metrics.dropped_catch_up_ticks <= max(1, metrics.ticks // 100)
                                    and traffic["max_update_bytes"] <= 1200
                                    and (not args.clients or traffic["datagrams"] > 0))
                travel = [bot.furthest_travel for bot in server.bots.bots if bot.is_bot]
                report["navigation"] = {
                    "bots_past_1km":sum(distance >= 1000 for distance in travel),
                    "median_travel":round(statistics.median(travel),1),
                    "maximum_travel":round(max(travel),1),
                    "minimum_travel":round(min(travel),1),
                    "late_peak_stalled":max((s['stalled_bots'] for s in samples if s['seconds']>=60),default=0),
                    "final_stalled":samples[-1]['stalled_bots'] if samples else None,
                    "peak_engaging":max((s['engaging_bots'] for s in samples),default=0),
                    "by_team": {str(team):[round(bot.furthest_travel,1) for bot in server.bots.bots
                                           if bot.is_bot and bot.team==team] for team in (1,2)}}
            finally:
                server.stop_update_event.set()
                server.tcp_sock.close()
                server.udp_sock.close()
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}, indent=2))
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
