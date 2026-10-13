"""Build a clean, verifiable portable client from the preserved baseline archive."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASELINE='eb8a70bffaa4370c6b311cdbf438e67700da563625285ce93d4a0dcfa75dbf4e'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--helper',type=Path,required=True)
    parser.add_argument('--helper-sha256',required=True)
    parser.add_argument('--actions-run',type=int,required=True)
    parser.add_argument('--helper-revision',required=True,help='exact source revision of that Actions build')
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',type=Path,required=True,help='new directory for the extracted package and ZIP')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9.-]{1,40}',args.version):
        raise ValueError('Invalid version')
    if digest(args.baseline)!=BASELINE or digest(args.helper)!=args.helper_sha256.lower():
        raise ValueError('Baseline or exact Actions helper digest does not match')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not re.fullmatch('[a-f0-9]{40}',args.helper_revision):
        raise ValueError('Supply the full Actions source revision')
    if subprocess.check_output(['git','diff',args.helper_revision,'HEAD','--',
                                'client/windows/wulfram-display.c','client/windows/CMakeLists.txt'],cwd=ROOT,text=True):
        raise ValueError('The display helper source changed since its Actions build')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip():
        raise ValueError('Commit the source before packaging')
    output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    client=output/'Wulfram-Canadaverse'
    with zipfile.ZipFile(args.baseline) as archive:
        for entry in archive.infolist():
            destination=(output/entry.filename).resolve()
            if not destination.is_relative_to(client):
                raise ValueError('Archive entry leaves the client directory')
            if Path(entry.filename).name in ('Uninstall.exe','bwau.exe','package-manifest.json'):
                continue
            archive.extract(entry,output)
    for name in ('Play Canadaverse.cmd','Settings.cmd','START HERE.txt','DDrawCompat-License.txt'):
        text=(ROOT/'client/windows'/name).read_text()
        (client/name).write_bytes(text.replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))
    shutil.copy2(args.helper,client/'wulfram-display.exe')
    subprocess.run([str(client/'wulfram-display.exe'),'--self-test'],check=True)
    powershell=shutil.which('pwsh') or shutil.which('powershell.exe')
    if powershell is None: raise RuntimeError('PowerShell is required to prepare the client')
    environment=dict(os.environ)
    environment.pop('PSModulePath',None)  # Do not mix PowerShell 7 and Windows PowerShell module paths.
    for script,extra in (('prepare-windows-client.ps1',['-CompatibilityDll',str(client/'w2reg.dll')]),
                         ('prepare-controls.ps1',[])):
        subprocess.run([powershell,'-NoProfile','-File',str(ROOT/'scripts'/script),'-ClientDir',str(client),*extra],check=True,env=environment)
    runpy.run_path(str(ROOT/'scripts/build-frontier-map.py'))['generate'](client/'data/maps/frontier')
    graphics=client/'canadaverse/graphics'
    graphics.mkdir(parents=True)
    high=(client/'DDrawCompat-wulfram2.ini').read_text()
    (graphics/'high.ini').write_text(high,encoding='ascii')
    balanced=high.replace('TextureFilter = af16x','TextureFilter = af4x').replace('Antialiasing = msaa4x(0)','Antialiasing = off')
    (graphics/'balanced.ini').write_text(balanced,encoding='ascii')
    files={str(path.relative_to(client)).replace('\\','/'):digest(path)
           for path in sorted(client.rglob('*')) if path.is_file()}
    manifest={'schema':1,'version':args.version,'source_revision':revision,'actions_run':args.actions_run,
              'helper_build_revision':args.helper_revision,
              'baseline_sha256':BASELINE,'helper_sha256':args.helper_sha256.lower(),'files':files}
    (client/'package-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    archive_path=output/f'Wulfram-Canadaverse-Windows-{args.version}-{revision[:7]}.zip'
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sorted(client.rglob('*')):
            if path.is_file(): archive.write(path,path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for name,expected in files.items():
            assert hashlib.sha256(archive.read('Wulfram-Canadaverse/'+name)).hexdigest()==expected,name
    sha256=digest(archive_path)
    archive_path.with_suffix('.zip.sha256').write_text(f'{sha256}  {archive_path.name}\n',encoding='ascii')
    release={'ready':False,'version':args.version,'revision':revision,'actions_run':args.actions_run,
             'url':'/downloads/wulfram/'+archive_path.name,'bytes':archive_path.stat().st_size,'sha256':sha256}
    (output/'release.json').write_text(json.dumps(release,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'archive':str(archive_path),'client':str(client),'sha256':sha256,'files_verified':len(files),'ready':False}))


if __name__=='__main__': main()
