"""Copy supported terrain from authorized server content into a native client."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil


def validate_land(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Terrain file is too large')
    lines = path.read_text(encoding='utf-8').splitlines()
    width, height = map(int, lines[0].split('x'))
    extents = list(map(float, lines[1].split('x')))
    if not (2 <= width <= 512 and 2 <= height <= 512 and len(lines) == width*height+2
            and len(extents) == 2 and all(math.isfinite(v) and 0 < v <= 8192 for v in extents)):
        raise ValueError('Unsupported terrain dimensions')
    for row in lines[2:]:
        texture, altitude = row.split()
        if not (0 <= int(texture) <= 65535 and math.isfinite(float(altitude)) and abs(float(altitude)) <= 8192):
            raise ValueError('Invalid terrain cell')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--content-root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    maps = []
    for name in ('crossroads', 'mayhem', 'frontier'):
        choices = [root/'shared/data/maps'/name/'land' for root in args.content_root]
        source = next((path for path in choices if path.is_file()), None)
        if source is None:
            raise SystemExit(f'Missing authorized terrain for {name}; provide its content root.')
        validate_land(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        maps.append((name, source, digest))
        if not source.with_name('tagmap2').is_file():
            raise SystemExit(f'Missing original terrain texture table for {name}.')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 1, 'maps': []}
    for name, source, digest in maps:
        target = args.output/(name+'.land')
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise SystemExit(f'Refusing to replace different terrain: {target}')
        shutil.copyfile(source, target)
        manifest['maps'].append({'name': name, 'file': target.name, 'sha256': digest, 'bytes': target.stat().st_size})
        tags = source.with_name('tagmap2')
        tag_target = args.output/(name+'.tagmap2')
        shutil.copyfile(tags, tag_target)
        manifest['maps'][-1]['tagmap2_sha256'] = hashlib.sha256(tags.read_bytes()).hexdigest()
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('MODERN_MAPS=PASS maps=3')


if __name__ == '__main__':
    main()
