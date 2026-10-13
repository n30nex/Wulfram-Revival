"""Measure one exact staging server for up to 24 hours, including real sessions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read_sample(path, revision, pid=None):
    sample = json.loads(path.read_text())
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(sample['updated_utc'])).total_seconds()
    if sample['git_commit'] != revision or (pid is not None and sample['process_id'] != pid):
        raise ValueError('candidate changed or server restarted')
    if not -5 <= age <= 25:
        raise ValueError('simulation heartbeat is stale')
    if sample['bots'] != 64 or not 64 <= sample['sessions'] <= 80:
        raise ValueError('64 bots plus 16 human places were not preserved')
    if sample['route_fields'] > 128:
        raise ValueError('route cache exceeded its bound')
    return sample


def assess(samples, elapsed, journeys):
    first, last = samples[0], samples[-1]
    ticks = last['physics_ticks']-first['physics_ticks']
    dropped = last['dropped_ticks']-first['dropped_ticks']
    maps = sorted({sample['map'] for sample in samples if not sample['changing_map']})
    peak_live = {name:max(s['live_bots'] for s in samples if s['map']==name) for name in maps}
    spawned = {name:max(s['spawned_bots'] for s in samples if s['map']==name) for name in maps}
    memory = [sample['rss_bytes'] for sample in samples if sample['rss_bytes'] is not None]
    # Compare after the first five minutes to allow initial spawns/cache warming.
    warm = [s['rss_bytes'] for s in samples if 300 <= s['elapsed_seconds'] <= 600 and s['rss_bytes'] is not None]
    tail = [s['rss_bytes'] for s in samples if s['elapsed_seconds'] >= elapsed-300 and s['rss_bytes'] is not None]
    checks = {
        'full_24_hours': elapsed >= 86400,
        'all_rotation_maps': set(maps) >= {'crossroads','mayhem','frontier'},
        'all_bots_spawn_on_each_map': bool(spawned) and all(count == 64 for count in spawned.values()),
        'simulation_rate': ticks >= .95*elapsed*25,
        'dropped_ticks_below_one_percent': 0 <= dropped < max(1,(ticks+dropped)*.01),
        'memory_within_budget': bool(memory) and max(memory) < 384*1024*1024,
        'memory_growth_bounded': bool(warm and tail) and sum(tail)/len(tail) <= sum(warm)/len(warm)*1.25+32*1024*1024,
        'repeated_16_player_churn': journeys >= 32,
    }
    return {'checks':checks,'passed':all(checks.values()),'physics_ticks':ticks,'dropped_ticks':dropped,
            'maps_seen':maps,'peak_live_by_map':peak_live,'spawned_by_map':spawned,'peak_rss_bytes':max(memory,default=None),
            'successful_journeys':journeys,'elapsed_seconds':round(elapsed,2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-directory',type=Path,required=True)
    parser.add_argument('--expected-revision',required=True)
    parser.add_argument('--host',required=True)
    parser.add_argument('--expected-ip',required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--seconds',type=int,default=86400,choices=range(15,86401),metavar='15..86400')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}',args.expected_revision):
        parser.error('expected revision must be a complete commit SHA')
    runtime = json.loads((args.state_directory/'runtime.json').read_text())
    if (runtime['environment'] != 'staging' or runtime['status'] != 'ready'
            or runtime['git_commit'] != args.expected_revision
            or runtime['tcp_port'] != args.port or runtime['udp_port'] != args.port):
        parser.error('load qualification requires the exact ready staging server and port')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    trace = args.output.with_suffix('.jsonl')
    if args.output.exists() or trace.exists():
        parser.error('refusing to overwrite an earlier qualification run')
    samples, journeys = [], 0
    started = time.monotonic()
    report = {'status':'running','git_commit':args.expected_revision,'passed':False}

    def save():
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        temporary.replace(args.output)

    def probe(index):
        command = [sys.executable,str(ROOT/'scripts/check-online.py'),'--host',args.host,
                   '--expected-ip',args.expected_ip,'--port',str(args.port),'--team',str(1+index%2),
                   '--bots','64','--seconds','35','--drive']
        result = subprocess.run(command,capture_output=True,text=True,timeout=75)
        document = json.loads(result.stdout)
        document['journey_passed'] = not result.returncode and document.get('passed') and document.get('clean_disconnect')
        return document

    save()
    try:
        next_churn = started
        with trace.open('x',encoding='utf-8') as stream:
            while True:
                now = time.monotonic()
                sample = read_sample(args.state_directory/'qualification.json',args.expected_revision,runtime['process_id'])
                sample['elapsed_seconds'] = round(now-started,3)
                if samples and (sample['physics_ticks'] < samples[-1]['physics_ticks']
                                or sample['dropped_ticks'] < samples[-1]['dropped_ticks']):
                    raise ValueError('cumulative simulation counters reset')
                samples.append(sample)  # At most 8641 small samples (24h / 10s).
                stream.write(json.dumps(sample)+'\n'); stream.flush()
                report.update(assess(samples,now-started,journeys))
                save()
                if now-started >= args.seconds:
                    break
                if now >= next_churn and not sample['changing_map']:
                    with ThreadPoolExecutor(max_workers=16) as workers:
                        results = list(workers.map(probe,range(16)))
                    journeys += sum(bool(result['journey_passed']) for result in results)
                    failures = [result for result in results if not result['journey_passed']]
                    if failures:
                        report['failed_journeys'] = [{key:result.get(key) for key in (
                            'phase','error_type','spawn_received','spawn_health','movement_inputs_sent',
                            'updates_missing_vitals','clean_disconnect')} for result in failures]
                        report['successful_journeys'] = journeys
                        raise ValueError('real login/spawn/disconnect journey failed')
                    next_churn = time.monotonic()+300
                time.sleep(min(10,max(0,started+args.seconds-time.monotonic())))
        report['status'] = 'completed'
    except Exception as error:
        report.update(status='failed',passed=False,error_type=type(error).__name__,error=str(error))
    save()
    print(json.dumps(report,indent=2))
    # A short smoke run can complete successfully, but never passes the 24h gate.
    return 0 if report['status']=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
