"""Copy exact original graphics archives; never redraw, upscale or rewrite them."""
import argparse
import hashlib
import json
from pathlib import Path
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
    for name, relative in FILES.items():
        source = args.client/'data'/relative
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if name.endswith('.zip'):
            with zipfile.ZipFile(source) as archive:
                if archive.testzip() is not None:
                    raise ValueError('Damaged original archive: '+name)
        sources.append((name, source, digest))
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'schema': 1, 'mode': 'verbatim-original-archives', 'files': []}
    for name, source, digest in sources:
        target = args.output/name
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Refusing to replace different original assets: '+str(target))
        shutil.copyfile(source, target)
        manifest['files'].append({'file': name, 'sha256': digest, 'bytes': source.stat().st_size})
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('ORIGINAL_ASSETS_COPIED='+str(len(sources)))


if __name__ == '__main__':
    main()
