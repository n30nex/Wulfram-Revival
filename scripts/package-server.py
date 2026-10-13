"""Seal source, exact Actions physics and content for startup integrity checks."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import struct
import subprocess
import sys
import sysconfig

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--native-sha256',required=True)
    parser.add_argument('--content-root',type=Path,required=True)
    parser.add_argument('--actions-run',type=int,required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9.-]{1,40}',args.version): raise ValueError('Invalid version')
    if digest(args.native)!=args.native_sha256.lower(): raise ValueError('Native Actions artifact differs')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise ValueError('Package only a clean committed tree')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    spec=importlib.util.spec_from_file_location('_wulfram_physics',args.native)
    native=importlib.util.module_from_spec(spec); spec.loader.exec_module(native)
    if native.api_version()!=13: raise ValueError('Unexpected physics API')
    world=native.create_world(count_x=2,count_y=2,spacing_x=1.0,spacing_y=1.0,
                             heights_x_major=[0.0]*4,terrain_identity='release-probe',configuration={})
    physics_version=native.write_snapshot(world)['physics_version']
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    for name in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'):
        if not name or not name.startswith(('server/','config/','scripts/','site/')): continue
        target=output/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/name,target)
    shutil.copytree(args.content_root,output/'content')
    # Configuration comes from this source revision; original map/model assets
    # remain private and are bound into the same content digest.
    for name in ('gameplay.toml','packets.toml'):
        shutil.copy2(ROOT/'server/wulfram_server/content'/name,output/'content'/name)
    (output/'bin').mkdir()
    shutil.copy2(args.native,output/'bin'/('_wulfram_physics'+sysconfig.get_config_var('EXT_SUFFIX')))
    entries=[{'path':p.relative_to(output).as_posix(),'size':p.stat().st_size,'sha256':digest(p)}
             for p in sorted(output.rglob('*')) if p.is_file()]
    content_entries=[entry for entry in entries if entry['path'].startswith('content/')]
    identity=hashlib.sha256(json.dumps(content_entries,sort_keys=True).encode()).hexdigest()
    manifest={'schema_version':1,'release_version':args.version,'git_commit':revision,
              'actions_run':args.actions_run,'files':entries,'content':{'identity':identity},
              'physics':{'semantic_version':physics_version,'api':native.api_version()},
              'python_runtime':{'implementation':sys.implementation.name,
                                'version':'.'.join(str(v) for v in sys.version_info[:3]),
                                'abi_tag':sys.implementation.cache_tag,'pointer_bits':struct.calcsize('P')*8}}
    (output/'release.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'revision':revision,'output':str(output),'files_verified':len(entries),
                      'content_identity':identity,'physics_version':physics_version}))


if __name__=='__main__': main()
