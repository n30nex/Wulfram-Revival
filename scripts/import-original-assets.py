"""Copy exact original graphics archives; never redraw, upscale or rewrite them."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import zipfile


FILES = {
    'shapes.zip': 'shapes.zip', 'palette0': 'palette0', 'palette1': 'palette1',
    **{name+'.zip': 'bitmaps/'+name+'.zip' for name in ('base', 'landscape', 'skies', 'res_640x480')},
    'stripmaps2.zip': 'stripmaps2.zip',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sources = []
    members = []
    for name, relative in FILES.items():
        source = args.client/'data'/relative
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if name.endswith('.zip'):
            with zipfile.ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise ValueError('Damaged original archive: '+name)
                entries = {}
                for entry in archive.infolist():
                    if not entry.is_dir():
                        entries.setdefault(entry.filename.lower(), []).append(entry)
                for key, versions in entries.items():
                    if len(versions) < 2:
                        continue
                    relative = PurePosixPath(key)
                    if relative.is_absolute() or '..' in relative.parts or ':' in key or '\\' in key:
                        raise ValueError('Unsafe original archive member')
                    final = versions[-1]
                    raw = archive.read(final)
                    members.append((f'resolved/{Path(name).stem}/{key}', raw, name, final.filename))
        sources.append((name, source, digest))
    audio = args.client/'data/base_sound'
    for raw in (audio/'index.wgn').read_text().splitlines():
        fields = raw.split()
        if not fields or fields[0].startswith('#'):
            continue
        if len(fields) < 9 or not re.fullmatch(r'[A-Za-z0-9_-]+', fields[1]):
            raise ValueError('Invalid original sound catalogue')
        if not (audio/(fields[1]+'.ogg')).is_file():
            raise ValueError('Missing original sound: '+fields[0])
    for source in [audio/'index.wgn', *sorted(audio.glob('*.ogg'))]:
        sources.append(('audio/'+source.name, source, hashlib.sha256(source.read_bytes()).hexdigest()))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 2, 'mode': 'verbatim-original-archives-and-last-members', 'files': []}
    for name, source, digest in sources:
        target = args.output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Refusing to replace different original assets: '+str(target))
        shutil.copyfile(source, target)
        manifest['files'].append({'file': name, 'sha256': digest, 'bytes': source.stat().st_size})
    for name, raw, archive, member in members:
        target = args.output/name
        digest = hashlib.sha256(raw).hexdigest()
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Refusing to replace different original member: '+str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        manifest['files'].append({'file': name, 'sha256': digest, 'bytes': len(raw),
                                  'source_archive': archive, 'source_member': member, 'selection': 'last'})
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('ORIGINAL_ASSETS_COPIED='+str(len(manifest['files'])))


if __name__ == '__main__':
    main()
