"""Isolated retail-client lab with a test-only in-engine menu event bridge.

Prepare from the verified client archive; start a known display helper; inspect
the actual child process and save its F12 images beside a reproducible run record.
No global display settings, user game profiles, or other processes are changed.
"""
from pathlib import Path
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import time
import zipfile

RETAIL = '94990864ab1db2ddbe2652cfdbca726356b19dd3fb7597945e297a43973d99d4'
ARCHIVE = 'eb8a70bffaa4370c6b311cdbf438e67700da563625285ce93d4a0dcfa75dbf4e'
NAV_CALLBACKS = (0x4934f0,0x43dda0,0x474d20,0x483850,0x45aa20,0x4a0220,0x41e190)
NAV_SCENES = dict(zip(NAV_CALLBACKS,('teams','map','your-stats','team-stats','ranks','units','credits')))
MENU_CALLBACKS = (*NAV_CALLBACKS,0x4622e0,0x484a90)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def prepare(root, archive, expected=ARCHIVE):
    if not re.fullmatch('[a-fA-F0-9]{64}',expected) or root.exists() or digest(archive) != expected.lower():
        raise ValueError('Choose a new lab directory and the verified Canadaverse archive.')
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if not (root / name).resolve().is_relative_to(root):
                raise ValueError('Archive path leaves the lab.')
        source.extractall(root)
    client = root / 'Wulfram-Canadaverse'
    if digest(client / 'wulfram2.exe') != RETAIL:
        raise ValueError('Unexpected retail executable.')
    save(root / 'lab.json', {'client': str(client), 'archive_sha256': expected.lower()})


def lab_client(root):
    marker = json.loads((root / 'lab.json').read_text())
    client = Path(marker['client']).resolve()
    if not client.is_relative_to(root) or digest(client / 'wulfram2.exe') != RETAIL:
        raise ValueError('The lab marker or executable does not match this lab.')
    return client


class ClientProcess:
    def __init__(self, pid, client, terminate=False, write=False):
        if os.name != 'nt':
            raise RuntimeError('The retail client lab requires Windows.')
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        self.k.WriteProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        self.k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)]
        self.k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        self.k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        self.k.WaitForSingleObject.restype = w.DWORD
        self.handle = self.k.OpenProcess(0x100410 | int(terminate) | (0x28 if write else 0), False, pid)
        if not self.handle:
            raise ProcessLookupError(f'Test child {pid} is not running or readable.')
        self.pid = pid
        if self.k.WaitForSingleObject(self.handle,0) == 0:
            self.close()
            raise ProcessLookupError(f'Test child {pid} has exited.')
        name = c.create_unicode_buffer(32768)
        size = w.DWORD(len(name))
        if not self.k.QueryFullProcessImageNameW(self.handle, 0, name, c.byref(size)):
            raise OSError(c.get_last_error())
        if Path(name.value).resolve() != client / 'wulfram2.exe':
            self.close()
            raise ProcessLookupError('Recorded PID now belongs to another executable; no action taken.')
        stamps = [w.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(self.handle, *[c.byref(item) for item in stamps]):
            raise OSError(c.get_last_error())
        self.created = stamps[0].dwHighDateTime << 32 | stamps[0].dwLowDateTime

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def read(self, address, length):
        buffer, actual = c.create_string_buffer(length), c.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, address, buffer, length, c.byref(actual)) or actual.value != length:
            raise OSError(f'Cannot read client diagnostic address {address:#x}.')
        return buffer.raw

    def uint(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def write(self, address, data):
        buffer, actual = c.create_string_buffer(data), c.c_size_t()
        if not self.k.WriteProcessMemory(self.handle,address,buffer,len(data),c.byref(actual)) or actual.value != len(data):
            raise OSError('Cannot write the isolated client test mailbox.')

    def menu_command(self, mailbox, x=0, y=0, capture=False):
        if not mailbox or self.uint(mailbox) != 0x574c4142:
            raise ValueError('This run has no verified test-only input mailbox.')
        request, response = struct.unpack('<2I',self.read(mailbox+4,8))
        if request != response:
            raise RuntimeError('The previous menu command is still pending; do not repeat it.')
        request = (request+1) & 0xffffffff
        self.write(mailbox+12,struct.pack('<iiI',x,y,0))
        self.write(mailbox+24,struct.pack('<I',int(capture)))
        self.write(mailbox+4,struct.pack('<I',request))
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if self.uint(mailbox+8) == request:
                if self.uint(mailbox+20) != 1:
                    raise ValueError('The client rejected the test command or screenshot capture failed.')
                return request
            time.sleep(.02)
        raise TimeoutError('Menu command outcome is unknown; inspect the same run before retrying.')

    def viewport(self, address):
        pointer = self.uint(address)
        if not pointer:
            return None
        values = struct.unpack('<15i', self.read(pointer, 60))
        return {'pointer': hex(pointer), 'size': list(values[:2]),
                'origin': list(values[4:6]), 'clip': list(values[7:11]),
                'allocation': list(values[13:15])}

    def windows(self):
        user = c.WinDLL('user32', use_last_error=True)
        user.SetProcessDpiAwarenessContext.argtypes = [c.c_void_p]
        user.SetProcessDpiAwarenessContext(c.c_void_p(-4))
        user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        user.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
        user.GetDpiForWindow.argtypes = [w.HWND]
        user.IsWindowVisible.argtypes = [w.HWND]
        result = []
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        def visit(window, _):
            pid = w.DWORD()
            user.GetWindowThreadProcessId(window, c.byref(pid))
            if pid.value == self.pid and user.IsWindowVisible(window):
                frame, client = w.RECT(), w.RECT()
                user.GetWindowRect(window, c.byref(frame)); user.GetClientRect(window, c.byref(client))
                result.append({'frame': [frame.left, frame.top, frame.right, frame.bottom],
                               'client_size': [client.right, client.bottom], 'dpi': user.GetDpiForWindow(window)})
            return True
        user.EnumWindows.argtypes = [callback_type, w.LPARAM]
        user.EnumWindows(callback_type(visit), 0)
        return result

    def inspect(self, expected):
        driver = self.uint(0x677e54)
        size = list(struct.unpack('<ii', self.read(driver + 0xdc, 8))) if driver else [0, 0]
        viewer = self.uint(0x677f70)
        callback = self.uint(viewer + 0xc) if viewer else 0
        scene = (NAV_SCENES[callback] if callback in NAV_SCENES else
                 'world' if callback == 0x441c50 else
                 'login' if callback == 0x4622e0 else 'other')
        views = {name: self.viewport(address) for name, address in (
            ('root', 0x5f56ac), ('world', 0x5f567c), ('chat', 0x5f5698),
            ('current', 0x677fa4), ('entry_map',0x684210), ('vehicle_preview', 0x684220),
            ('units_left',0x66ebc0), ('units_right',0x66ebb8))}
        problems = []
        if not callback:
            problems.append('The client UI is not ready yet.')
        if size != expected:
            problems.append(f'Renderer {size} differs from requested logical resolution {expected}.')
        menu = callback in MENU_CALLBACKS
        origin = [(expected[0]-640)//2, (expected[1]-480)//2] if menu else [0, 0]
        if views['root'] and (views['root']['origin'] != origin or views['root']['size'] != ([640,480] if menu else expected)):
            problems.append('The active root canvas has the wrong size or origin.')
        current = views['entry_map']
        if menu and current and current['size'] == [343,344] and current['origin'] != [291+origin[0],4+origin[1]]:
            problems.append('The entry-map texture viewport is detached from its frame.')
        if scene=='units':
            for name,x,y,width,height in (('units_left',55,69,233,154),('units_right',330,66,254,161)):
                pane=views[name]
                if not pane or pane['origin']!=[x+origin[0],y+origin[1]] or pane['size']!=[width,height]:
                    problems.append('A Units Info model viewport is detached from its frame.')
        widgets, seen = [], set()
        node = self.uint(viewer+0x28) if viewer else 0
        while node and node not in seen and len(seen) < 200:
            seen.add(node)
            try:
                item = self.uint(node+8)
                x, y, width, height = struct.unpack('<4i', self.read(item+4,16))
                parent = self.uint(item+0x18)
                if parent and 0 < width <= 8000 and 0 < height <= 8000:
                    ox, oy = struct.unpack('<2i',self.read(parent+0x10,8))
                    widgets.append({'widget':hex(item),'vtable':hex(self.uint(item)),
                                    'logical_rect':[x+ox,y+oy,width,height]})
                node = self.uint(node)
            except OSError:
                break
        tank = self.uint(0x677f2c)
        return {'utc':datetime.now(timezone.utc).isoformat(), 'pid':self.pid,
                'renderer':size, 'scene':scene, 'active_viewer':hex(viewer),
                'team':self.uint(0x677f30), 'screen_mode':self.uint(0x5de09c), 'draw_callback':hex(callback),
                'viewports':views, 'windows':self.windows(), 'widgets':widgets,
                  'cursor_position':[self.uint(0x677d18),self.uint(0x677104)],
                'hull':struct.unpack('<f',self.read(tank+0xd0,4))[0] if tank else None,
                'tint_mode':self.uint(0x577e98), 'layout_problems':problems}


def logical_size(width, height):
    logical_height = 480 if height < 720 else 540
    logical_width = (width*logical_height+height//2)//height
    if logical_width < 640:
        logical_width,logical_height = 640,(height*640+width//2)//width
    logical_width = (logical_width+3)&~3
    return [logical_width,logical_height]


def check_map_image(path, state):
    """Catch a clipped Crossroads terrain preview independently of UI geometry."""
    if state['scene'] != 'map' or not state['viewports']['entry_map']:
        return
    data = path.read_bytes()
    offset = struct.unpack_from('<I',data,10)[0]
    width, height = struct.unpack_from('<ii',data,18)
    bits = struct.unpack_from('<H',data,28)[0]
    if data[:2] != b'BM' or bits != 24 or height <= 0:
        raise ValueError('Unexpected game screenshot format.')
    stride = (width*3+3) & ~3
    pane = state['viewports']['entry_map']
    ox, oy = pane['origin']; pw, ph = pane['size']
    visible = total = 0
    for y in range(oy+8,oy+ph-8,4):
        for x in range(ox+8,ox+pw-8,4):
            if not 0 <= x < width or not 0 <= y < height:
                raise ValueError('Entry-map pixels leave the screenshot.')
            at = offset+(height-1-y)*stride+x*3
            visible += max(data[at:at+3]) > 8
            total += 1
    coverage = visible/total
    state['entry_map_pixel_coverage'] = round(coverage,4)
    if coverage < .85:
        state['layout_problems'].append('The entry-map image is mostly blank or clipped.')


def check_cursor_image(path, state):
    """Use on a dark menu control: verify the drawn arrow reaches its input point."""
    data=path.read_bytes()
    offset=struct.unpack_from('<I',data,10)[0]
    width,height=struct.unpack_from('<ii',data,18)
    if data[:2]!=b'BM' or struct.unpack_from('<H',data,28)[0]!=24 or height<=0:
        raise ValueError('Unexpected cursor screenshot format')
    stride=(width*3+3)&~3
    cx,cy=state['cursor_position']
    bright=0
    for y in range(max(0,cy-2),min(height,cy+16)):
        for x in range(max(0,cx-2),min(width,cx+16)):
            at=offset+(height-1-y)*stride+x*3
            bright+=min(data[at:at+3])>=224
    state['cursor_bright_pixels_at_input']=bright
    if bright<5: state['layout_problems'].append('The software cursor is not drawn at the input coordinates.')


def start(args, root, client):
    for record in (root/'runs').glob('*/run.json'):
        old = json.loads(record.read_text())
        try:
            process = ClientProcess(old['pid'],client)
        except ProcessLookupError:
            continue
        try:
            if process.created == old['created']:
                raise RuntimeError('Stop the existing lab run before starting another.')
        finally:
            process.close()
    width, height = map(int,args.resolution.split('x'))
    if not 800 <= width <= 7680 or not 600 <= height <= 4320:
        raise ValueError('Resolution is outside the display helper bounds.')
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',args.server):
        raise ValueError('Invalid server hostname.')
    logical = logical_size(width,height)
    # Exercise the shipped profile. Rewriting it here would hide a broken
    # package or a missing display mode in the real launcher's configuration.
    profile_hash = digest(client/'DDrawCompat-wulfram2.ini')
    extra = ['--lab-view']
    if args.scene != 'login':
        password = os.environ.get('WULFRAM_LAB_PASSWORD','')
        if not password or any(ch.isspace() or ch in '\"\x00' for ch in password):
            raise ValueError('Set WULFRAM_LAB_PASSWORD for the isolated test account.')
        extra = ['--lab']
    run = root/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(parents=True)
    launcher = run/'wulfram-display.exe'
    shutil.copy2(args.launcher.resolve(),launcher)
    environment = dict(os.environ,WULFRAM_LAB_PORT=str(args.port))
    result = subprocess.run([str(launcher),str(client),str(width),str(height),args.server,*extra],
                            capture_output=True,text=True,timeout=30,env=environment)
    (run/'launch.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    match = re.search(r'DISPLAY_PATCH pid=(\d+)',result.stdout)
    if result.returncode or not match:
        raise RuntimeError(f'Launch failed; inspect {run / "launch.log"}.')
    process = ClientProcess(int(match[1]),client,write=args.scene=='map')
    try:
        record = {'pid':process.pid,'created':process.created,'client':str(client),'output':[width,height],
                  'logical':logical,'scene':args.scene,'server':args.server,
                  'port':args.port,
                  'initial_profile_sha256':profile_hash,
                  'launcher':str(launcher),'launcher_sha256':digest(launcher),'retail_sha256':RETAIL}
        mailbox = re.search(r'CLIENT_LAB_MAILBOX=(\d+)',result.stdout)
        record['mailbox'] = int(mailbox[1]) if mailbox else None
        save(run/'run.json',record)
        initial_scene = 'teams' if args.scene == 'map' else args.scene
        state, stable = wait_for_state(process, logical,
                                      lambda current: current['scene'] == initial_scene, timeout=25)
        if args.scene == 'map' and stable:
            # Exercise the normal team/map controls after they are ready.
            # The legacy -side shortcut can race roster layout during login.
            x,y = state['viewports']['root']['origin']
            process.menu_command(record['mailbox'],x+150,y+100)
            state, stable = wait_for_state(process, logical, lambda current: current['team'] == 1)
            if stable:
                process.menu_command(record['mailbox'],x+50,y+470)
                state, stable = wait_for_state(process, logical, lambda current: current['scene'] == 'map')
        save(run/'initial-state.json',state)
        if not stable or state['scene'] != args.scene:
            raise TimeoutError(f'The recorded child is still awaiting scene {args.scene}; inspect {run}.')
    finally:
        process.close()
    print(run)


def wait_for_state(process, logical, expected, timeout=5, settle=.75):
    """A one-frame transition followed by a crash/error is not a passing click."""
    deadline, stable_since = time.monotonic()+timeout, None
    while True:
        state = process.inspect(logical)
        now = time.monotonic()
        if expected(state):
            if stable_since is None:
                stable_since = now
            if now-stable_since >= settle:
                return state, True
        else:
            stable_since = None
        if now >= deadline:
            return state, False
        time.sleep(.05)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    sub = parser.add_subparsers(dest='action',required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--archive',type=Path,required=True)
    prep.add_argument('--sha256',default=ARCHIVE,help='verified checksum of the exact release archive')
    launch = sub.add_parser('start'); launch.add_argument('--launcher',type=Path,required=True)
    launch.add_argument('--resolution',default='1920x1080'); launch.add_argument('--server',default='wulfram.canadaverse.org')
    launch.add_argument('--port',type=int,choices=range(1,65536),default=2627,metavar='1..65535')
    launch.add_argument('--scene',choices=('login','teams','map'),default='login')
    for name in ('inspect','capture','stop','click'):
        command = sub.add_parser(name); command.add_argument('--run',type=Path,required=True)
        if name == 'capture':
            command.add_argument('--label',required=True)
            command.add_argument('--verify-cursor',action='store_true')
            command.add_argument('--expect-scene',choices=('login',*NAV_SCENES.values(),'world'))
        if name == 'click':
            command.add_argument('--x',type=int,required=True); command.add_argument('--y',type=int,required=True)
            command.add_argument('--expect-scene',choices=(*NAV_SCENES.values(),'world'))
            command.add_argument('--expect-team',type=int,choices=(1,2))
    args = parser.parse_args(); root=args.root.resolve()
    if args.action == 'prepare': prepare(root,args.archive,args.sha256); return
    client = lab_client(root)
    if args.action == 'start': start(args,root,client); return
    run = args.run.resolve()
    if not run.is_relative_to(root/'runs'): raise ValueError('Run is outside this lab.')
    record = json.loads((run/'run.json').read_text())
    process = ClientProcess(record['pid'],client,terminate=args.action=='stop',write=args.action in ('click','capture'))
    try:
        if process.created != record['created']: raise ValueError('PID was reused; refusing access.')
        if args.action == 'stop':
            if not process.k.TerminateProcess(process.handle,0): raise OSError(c.get_last_error())
            if process.k.WaitForSingleObject(process.handle,5000) != 0:
                raise TimeoutError('The lab child has not confirmed exit; inspect this same run again.')
            print('Stopped only the recorded lab child.'); return
        state = process.inspect(record['logical'])
        if args.action == 'click':
            if args.expect_scene is None and args.expect_team is None:
                raise ValueError('A click test needs an expected scene or team change.')
            if int(state['draw_callback'],16) not in NAV_CALLBACKS:
                raise ValueError('Clicks are restricted to the non-authentication team/deployment menus.')
            sequence = process.menu_command(record.get('mailbox'),args.x,args.y)
            def expected(after):
                return ((args.expect_scene is None or after['scene'] == args.expect_scene)
                        and (args.expect_team is None or after['team'] == args.expect_team))
            after, stable = wait_for_state(process, record['logical'], expected)
            cursor_matches = after['cursor_position']==[args.x,args.y]
            # Gameplay captures/recenters the pointer after the pad is clicked.
            # Menu-to-menu transitions must still retain the clicked position.
            pointer_captured = after['scene'] == 'world'
            passed = stable and (cursor_matches or pointer_captured) and not after['layout_problems']
            save(run/f'click-{sequence:03}.json',{'point':[args.x,args.y], 'expected_scene':args.expect_scene,
                 'expected_team':args.expect_team,'passed':passed,'cursor_matches':cursor_matches,
                 'pointer_captured':pointer_captured,'before':state,'after':after})
            print(json.dumps({'sequence':sequence,'scene':after['scene'],'team':after['team'],'passed':passed}))
            if not passed: raise AssertionError('The clicked control did not produce the expected client state.')
            return
        if args.action == 'capture':
            if not re.fullmatch(r'[a-z0-9-]{1,60}',args.label): raise ValueError('Use a simple capture label.')
            state, stable = wait_for_state(process, record['logical'],
                lambda current: current['scene'] == (args.expect_scene or state['scene']))
            if not stable:
                save(run/(args.label+'-unstable.json'),state)
                raise AssertionError('The client did not remain in the expected scene before capture.')
            before = max((p.stat().st_mtime_ns for p in client.glob('shot*.bmp')),default=0)
            process.menu_command(record.get('mailbox'),capture=True)
            # Retail F12 reads the previous presented frame. Capture a second
            # frame so a just-completed menu transition cannot masquerade as
            # a screenshot of the requested world/page.
            time.sleep(.05)
            process.menu_command(record.get('mailbox'),capture=True)
            latest = max(client.glob('shot*.bmp'),key=lambda p:p.stat().st_mtime,default=None)
            if latest is None or latest.stat().st_mtime_ns <= before:
                raise ValueError('The screenshot command did not produce a new image.')
            shutil.copy2(latest,run/(args.label+'.bmp'))
            after = process.inspect(record['logical'])
            if after['scene'] != state['scene']:
                save(run/(args.label+'-unstable.json'),after)
                raise AssertionError('The client changed scene while its screenshot was captured.')
            check_map_image(latest,state)
            if args.verify_cursor: check_cursor_image(latest,state)
            save(run/(args.label+'.json'),state)
            if state['layout_problems']:
                raise AssertionError('; '.join(state['layout_problems']))
        print(json.dumps(state,indent=2))
    finally:
        process.close()


if __name__ == '__main__':
    main()
