"""Bounded native-client checks; generated fixtures contain synthetic data only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = root / 'client/modern'
    subprocess.run([sys.executable, str(root / 'scripts/modern-client-fixtures.py'),
                    str(project / 'test-fixtures.json')], check=True)
    results = []
    cases = [('import', ['--editor', '--import'], None),
             ('wire', ['--script', 'res://check.gd'], 'MODERN_WIRE=PASS'),
             ('layout', ['--', '--ui-check'], 'MODERN_UI_LAYOUT=PASS')]
    for name, options, marker in cases:
        started = time.monotonic()
        run = subprocess.run([str(args.godot.resolve()), '--headless', '--path', str(project),
                              *options], capture_output=True, text=True, timeout=45)
        log = run.stdout + run.stderr
        passed = run.returncode == 0 and 'ERROR:' not in log and (marker is None or marker in log)
        results.append({'name': name, 'passed': passed, 'seconds': round(time.monotonic()-started, 3)})
        print(log.strip())
        if not passed:
            raise SystemExit(f'Modern client {name} check failed.')
    report = {'godot_sha256': hashlib.file_digest(args.godot.open('rb'), 'sha256').hexdigest(),
              'checks': results, 'physical_display_qualified': False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print('MODERN_CLIENT_CHECKS=PASS')


if __name__ == '__main__':
    main()
