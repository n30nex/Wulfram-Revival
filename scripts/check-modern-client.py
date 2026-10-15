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
    report = {'passed': False, 'checks': [], 'physical_display_qualified': False}
    def save_report():
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    save_report()
    subprocess.run([sys.executable, str(root / 'scripts/modern-client-fixtures.py'),
                    str(project / 'test-fixtures.json')], check=True)
    results = report['checks']
    cases = [('import', ['--editor', '--import'], None),
             ('wire', ['--quit-after', '2', '--script', 'res://check.gd'], 'MODERN_WIRE=PASS'),
             ('original_formats', ['--quit-after', '2', '--script', 'res://check_original_formats.gd'], 'MODERN_ORIGINAL_FORMATS=PASS'),
             ('original_sky', ['--quit-after', '2', '--script', 'res://check_original_sky.gd'], 'MODERN_ORIGINAL_SKY=PASS'),
             ('audio', ['--script', 'res://check_audio.gd'], 'MODERN_AUDIO=PASS'),
             ('layout', ['--', '--ui-check'], 'MODERN_UI_LAYOUT=PASS'),
             ('input', ['--script', 'res://check_input.gd'], 'MODERN_INPUT=PASS')]
    cases.append(('comms', ['--script', 'res://check_comms.gd'], 'MODERN_COMMS=PASS'))
    for name, options, marker in cases:
        started = time.monotonic()
        try:
            run = subprocess.run([str(args.godot.resolve()), '--headless', '--path', str(project),
                                  *options], capture_output=True, text=True, timeout=45)
        except subprocess.TimeoutExpired as error:
            for output in (error.stdout, error.stderr):
                if output:
                    print(output.decode(errors='replace') if isinstance(output, bytes) else output)
            results.append({'name': name, 'passed': False, 'timeout': True})
            save_report()
            raise SystemExit(f'Modern client {name} check timed out.') from None
        log = run.stdout + run.stderr
        passed = (run.returncode == 0 and 'ERROR:' not in log and 'ObjectDB instances were leaked' not in log
                  and (marker is None or marker in log))
        results.append({'name': name, 'passed': passed, 'seconds': round(time.monotonic()-started, 3)})
        save_report()
        print(log.strip())
        if not passed:
            raise SystemExit(f'Modern client {name} check failed.')
    report.update(passed=True, godot_sha256=hashlib.file_digest(args.godot.open('rb'), 'sha256').hexdigest())
    save_report()
    print('MODERN_CLIENT_CHECKS=PASS')


if __name__ == '__main__':
    main()
