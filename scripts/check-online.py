"""Bounded external Wulfram check; stdout contains no credentials or packet bodies."""
import collections
import argparse
import datetime
import json
import select
import socket
import struct
import time
import secrets
import os

HOST = "wulfram.canadaverse.org"
EXPECTED_IP = "66.11.160.214"
PORT = 2627


def snapshot_pads(packet, team):
    """Decode full API13 snapshots independently of the server's serializer."""
    bits=''.join(f'{byte:08b}' for byte in packet[1:])
    cursor=0
    def take(count):
        nonlocal cursor
        if cursor+count>len(bits): raise ValueError('truncated snapshot')
        value=int(bits[cursor:cursor+count],2) if count else 0
        cursor+=count
        return value
    take(64)
    if take(1)!=1: raise ValueError('missing owner vitals')
    table=take(5); take(20)
    ready={0:3,1:2,2:0,3:1}
    take(ready[table])
    if table in (0,1): take(8)
    pads=[]
    for _ in range(take(8)):
        net_id=take(32); take(1); mask=take(10); bank=take(16)
        if not mask&1 or bank>2: raise ValueError('not a complete snapshot')
        unit=take(8); side=take(8); take(8)
        if unit==37: take(64)
        if unit==19: take(8)
        take(1)
        for flag in (2,4,8,16):
            if mask&flag: take(3*(13+take(2)))
        health=take(10) if mask&32 else 0
        if mask&64: take(ready[take(5)])
        if mask&128: take(10)
        if mask&256: take(32)
        if unit==27 and side==team and health: pads.append(net_id)
    return pads


def string(value):
    data = value.encode("ascii") + b"\0"
    return struct.pack(">H", len(data)) + data


def read_string(data, offset):
    size = struct.unpack_from(">H", data, offset)[0]
    end = offset + 2 + size
    if not 0 < size <= 4096 or end > len(data) or data[end - 1] != 0:
        raise ValueError("invalid protocol string")
    return data[offset + 2:end - 1].decode("ascii"), end


def drive_packet(stamp):
    # Stock Translation slots 10/11/15 are fixed 16-bit scalars. +1 uses
    # floor((1000-1)*65534/2000)+1 == 32735; action IDs are unscaled 16-bit.
    # Keep the probe independent of the server's writer/quantizer.
    return b'\x0a\x02'+struct.pack('>iiHHHH',stamp,0,2,32735,5,32735)


def spawn_state(packet):
    """Read the retail TANK identity and vitals without the server serializer."""
    if packet[:1] != b'\x18':
        raise ValueError('not a TANK packet')
    bits = ''.join(f'{value:08b}' for value in packet[1:])
    cursor = 32  # Server timestamp.
    def take(count):
        nonlocal cursor
        if cursor+count > len(bits):
            raise ValueError('truncated TANK')
        value = int(bits[cursor:cursor+count], 2)
        cursor += count
        return value
    if take(1) != 1:
        raise ValueError('missing TANK vitals')
    table = take(5)
    if table not in (0, 1):
        raise ValueError('unexpected player weapon table')
    health, fuel = take(10), take(10)
    take(3 if table == 0 else 2)
    take(8)
    unit, entity, team = take(32), take(32), take(8)
    if unit != table:
        raise ValueError('vehicle and weapon table differ')
    return {'entity': entity, 'team': team, 'vehicle': unit,
            'health': 0 if health == 0 else 1-(health-1)/1022,
            'fuel': 0 if fuel == 0 else 1-(fuel-1)/1022}


def main(args):
    global HOST, EXPECTED_IP, PORT
    HOST, EXPECTED_IP, PORT = args.host, args.expected_ip, args.port
    started = time.monotonic()
    result = {name: False for name in (
        "dns_matches", "tcp_connected", "server_hello", "advertised_public_endpoint",
        "udp_key_identified", "login_verified_udp", "udp_handshake_received",
        "login_status_accepted", "player_info_received", "world_metadata_received",
        "udp_ping_echo", "clean_disconnect", "passed")}
    result["started_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result["source_host"] = socket.gethostname()
    result["team"] = args.team
    result["phase"] = "dns"
    result["bots_by_team"] = {"1": 0, "2": 0}
    tcp = udp = None
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(HOST, PORT, socket.AF_INET)}
        result["dns_matches"] = addresses == {EXPECTED_IP}
        if not result["dns_matches"]:
            raise ValueError("unexpected public DNS address")
        result["phase"] = "tcp_connect"
        tcp = socket.create_connection((HOST, PORT), timeout=8)
        result["tcp_connected"] = True
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        pending = collections.deque()
        buffer = bytearray()

        def send_tcp(payload):
            tcp.sendall(struct.pack(">H", len(payload) + 2) + payload)

        def receive(deadline):
            while time.monotonic() < deadline:
                if pending:
                    return pending.popleft()
                readable, _, _ = select.select([tcp, udp], [], [], max(0, deadline - time.monotonic()))
                for sock in readable:
                    if sock is tcp:
                        chunk = tcp.recv(65535)
                        if not chunk:
                            raise ConnectionError("TCP closed")
                        buffer.extend(chunk)
                        while len(buffer) >= 2:
                            size = struct.unpack_from(">H", buffer)[0]
                            if size < 3:
                                raise ValueError("invalid TCP frame")
                            if len(buffer) < size:
                                break
                            pending.append(("tcp", bytes(buffer[2:size])))
                            del buffer[:size]
                    else:
                        data = udp.recv(65535)
                        if len(data) >= 3 and struct.unpack_from(">H", data)[0] == len(data):
                            data = data[2:]
                        pending.append(("udp", data))
            raise TimeoutError("protocol stage deadline")

        result["phase"] = "server_hello"
        key = endpoint = None
        deadline = time.monotonic() + 8
        while key is None or endpoint is None:
            transport, packet = receive(deadline)
            if transport == "tcp" and packet[:2] == b"\x13\x01":
                port, count = struct.unpack_from(">HH", packet, 2)
                host, end = read_string(packet, 6)
                if count != 1 or end != len(packet):
                    raise ValueError("unexpected advertised UDP configuration")
                endpoint = host, port
            elif transport == "tcp" and packet[:2] == b"\x13\x02":
                key, end = read_string(packet, 2)
                if end != len(packet):
                    raise ValueError("unexpected session key framing")
        result["server_hello"] = True
        result["advertised_public_endpoint"] = endpoint == (EXPECTED_IP, PORT)
        if not result["advertised_public_endpoint"]:
            raise ValueError("unexpected advertised UDP endpoint")
        udp.connect(endpoint)
        result["phase"] = "udp_key_echo"
        echo = b"\x13\x01" + string(key)
        for attempt in range(3):
            udp.send(echo)
            try:
                deadline = time.monotonic() + 2
                while not result["udp_key_identified"]:
                    transport, packet = receive(deadline)
                    result["udp_key_identified"] = transport == "udp" and packet == b"\x4d"
            except TimeoutError:
                continue
            break
        if not result["udp_key_identified"]:
            raise TimeoutError("UDP key identification")
        key = echo = None
        result["phase"] = "login_verification"
        send_tcp(b"\x21\x03" + string('Check'+secrets.token_hex(4)) + string(os.environ.get('WULFRAM_PROBE_PASSWORD','canadaverse')))
        deadline = time.monotonic() + 5
        while not result["login_verified_udp"]:
            transport, packet = receive(deadline)
            result["login_verified_udp"] = transport == "udp" and packet == b"\x13\x03"
        result["phase"] = "udp_handshake"
        stamp = int(time.monotonic() * 1000) & 0x7fffffff
        handshake = b"\x03" + struct.pack(">iii", stamp, 1, 4)
        for index, name in enumerate(("Unreliable", "Reliable", "Stream 2", "Game Data")):
            handshake += string(name) + struct.pack(">ii", 1, index)
        handshake += struct.pack(">i", 4) + b"".join(struct.pack(">ii", index, 1) for index in range(4))
        udp.send(b"\x08" + string("Hello There") + handshake)
        deadline = time.monotonic() + 5
        while not result["udp_handshake_received"]:
            transport, packet = receive(deadline)
            if transport == "udp" and packet[:1] == b"\x03":
                if len(packet) < 13 or struct.unpack_from(">i", packet, 9)[0] != 4:
                    raise ValueError("invalid server handshake")
                result["udp_handshake_received"] = True
        # The server marks its handshake sent after sending the stream records.
        time.sleep(0.05)
        udp.send(b"\x02\x00" + struct.pack(">i", stamp))
        result["phase"] = "login_bootstrap"
        udp.send(b"\x0b" + struct.pack(">ii", stamp, 0))
        deadline = time.monotonic() + 8
        needed = ("login_status_accepted", "player_info_received", "world_metadata_received", "udp_ping_echo", "team_capacity_received")
        while not all(result.get(name, False) for name in needed):
            transport, packet = receive(deadline)
            if transport == "tcp":
                if packet[:1] == b"\x24":
                    result["team_capacity"] = struct.unpack_from(">i", packet, 22)[0]
                    result["team_capacity_received"] = result["team_capacity"] == args.team_capacity
                if packet[:1] == b"\x1a":
                    team = str(struct.unpack_from(">H", packet, 9)[0])
                    name, _ = read_string(packet, 13)
                    if name.startswith("Bot") and name[3:].isdigit() and team in result["bots_by_team"]:
                        result["bots_by_team"][team] += 1
                if packet[:1] == b"\x22" and len(packet) >= 3:
                    result["login_status_accepted"] = packet[2] == 8
                result["player_info_received"] |= packet[:1] == b"\x17" and len(packet) == 6
                if packet[:1] == b"\x17" and len(packet) == 6:
                    player_id = struct.unpack_from('>i', packet, 1)[0]
                result["world_metadata_received"] |= packet[:1] == b"\x16"
                if packet[:1] == b"\x16": result['map']=read_string(packet,1)[0]
            elif packet == b"\x0c" + struct.pack(">i", stamp):
                result["udp_ping_echo"] = True
        result["phase"] = "world_snapshot"
        if result["bots_by_team"] != {"1": args.bots//2, "2": args.bots//2}:
            raise ValueError("bot roster is incomplete")
        send_tcp(b"\x39\x01")
        result["snapshot_chunks"] = 0
        result["snapshot_entities"] = 0
        result["largest_snapshot_bytes"] = 0
        pads_by_team = {1: [], 2: []}
        pads = pads_by_team[args.team]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                transport, packet = receive(deadline)
            except TimeoutError:
                break
            if transport == "tcp" and packet[:1] == b"\x0f":
                for team in pads_by_team:
                    pads_by_team[team].extend(snapshot_pads(packet, team))
                bits = "".join(f"{value:08b}" for value in packet[1:])
                # Retail tank vitals: present(1), table(5), health/fuel(10+10),
                # firing flags(3), pulse charge(8); preceded by two timestamps.
                if bits[64] != "1" or int(bits[65:70], 2) != 0:
                    raise ValueError("unexpected snapshot vitals")
                count = int(bits[101:109], 2)
                if count == 0 or len(packet) > 1200:
                    raise ValueError("invalid bounded snapshot")
                result["snapshot_chunks"] += 1
                result["snapshot_entities"] += count
                result["largest_snapshot_bytes"] = max(result["largest_snapshot_bytes"], len(packet))
        if not result["snapshot_chunks"] or not pads:
            raise ValueError("world snapshot missing")
        result["phase"] = "team_join"
        udp.send(b"\x25" + struct.pack(">HHBii", 1, 14, 1, args.team, 0))
        deadline = time.monotonic() + 4
        while True:
            transport, packet = receive(deadline)
            if packet[:2] == b"\x25\x11":
                result["team_joined"] = True
                break
        result["phase"] = "spawn"
        udp.send(b"\x25" + struct.pack(">HHBiiii", 2, 22, 0, pads[0], 0, 2000, 700))
        result['spawn_requests_sent'] = 1
        started_spawn = time.monotonic()
        deadline = started_spawn + 20
        retry_at=started_spawn+1
        drive_at=started_spawn
        sequence=2
        samples = []
        counts = collections.Counter()
        missing_vitals = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if getattr(args,'drive',False) and result.get('spawn_received') and now >= drive_at:
                drive_at = now+.2
                udp.send(drive_packet(int(now*1000)&0x7fffffff))
                result['movement_inputs_sent'] = result.get('movement_inputs_sent',0)+1
            if now >= retry_at:
                retry_at = now+1
                udp.send(b'\x0b'+struct.pack('>ii',stamp,0))
                if not result.get('spawn_received') and not getattr(args,'spawn_once',False):
                    sequence += 1
                    udp.send(b'\x25'+struct.pack('>HHBiiii',sequence,22,0,pads[(sequence-2)%len(pads)],0,2000,700))
                    result['spawn_requests_sent'] += 1
            wake_at = min(deadline, retry_at)
            if getattr(args,'drive',False) and result.get('spawn_received'):
                wake_at = min(wake_at, drive_at)
            try:
                transport, packet = receive(wake_at)
            except TimeoutError:
                continue
            counts[f'{transport}:{packet[0]:02x}'] += 1
            if packet[:1] == b'\x25' and len(packet) >= 2:
                codes = result.setdefault('spawn_reply_codes',{})
                code = str(packet[1])
                codes[code] = codes.get(code,0)+1
            if packet[:1] in (b"\x18", b"\x0e", b"\x0f"):
                bits = ''.join(f'{value:08b}' for value in packet[1:])
                offset = 64 if packet[0] == 0x0f else 32
                if bits[offset] != '1':
                    missing_vitals += 1
                    continue
                table = int(bits[offset+1:offset+6],2)
                raw_health = int(bits[offset+6:offset+16],2)
                health = 0 if raw_health == 0 else 1-(raw_health-1)/1022
                if packet[0] == 0x18:
                    state = spawn_state(packet)
                    if state['team'] != args.team or state['vehicle'] != 0:
                        raise ValueError('initial spawn identity differs')
                    if not result.get('spawn_received'):
                        result['spawn_received_seconds'] = round(time.monotonic()-started_spawn,3)
                        result['spawn_state'] = state
                        deadline = time.monotonic()+args.seconds
                    result['spawn_received'] = True
                    result['spawn_health'] = health
                    result['spawn_table'] = table
                if not samples or samples[-1]['health'] != round(health,4):
                    samples.append({'seconds':round(time.monotonic()-started_spawn,3), 'packet':hex(packet[0]), 'health':round(health,4)})
        result['health_changes'] = samples
        result['packet_counts_after_spawn'] = dict(counts)
        result['updates_missing_vitals'] = missing_vitals
        if not result.get('spawn_received'):
            raise ValueError('spawn missing')
        if result['spawn_health']!=1.0:
            raise ValueError('spawn did not have full health')
        if missing_vitals:
            raise ValueError('retail decoder would apply zero health from omitted vitals')
        if getattr(args, 'switch_team', False):
            result['phase'] = 'team_switch'
            target_team = 3-args.team
            switch = result['team_switch'] = {'team': target_team, 'joined': False,
                'old_entity_deleted': False, 'death_notice': False, 'spawn_requests_sent': 0,
                'movement_inputs_sent': 0}
            if not pads_by_team[target_team]:
                raise ValueError('opposite team has no pads')
            sequence += 1
            udp.send(b'\x25' + struct.pack('>HHBii', sequence, 14, 1, target_team, 0))
            switching_at = time.monotonic()
            deadline = switching_at+20
            retry_at = drive_at = switching_at
            deployed_at = None
            while time.monotonic() < deadline:
                now = time.monotonic()
                if switch['joined'] and deployed_at is None and now >= retry_at:
                    retry_at = now+1
                    sequence += 1
                    choices = pads_by_team[target_team]
                    pad = choices[switch['spawn_requests_sent'] % len(choices)]
                    udp.send(b'\x25' + struct.pack('>HHBiiii', sequence, 22, 0, pad, 1, 2000, 700))
                    switch['spawn_requests_sent'] += 1
                    udp.send(b'\x0b'+struct.pack('>ii', stamp, 0))
                if deployed_at is not None:
                    if now >= drive_at:
                        drive_at = now+.2
                        udp.send(drive_packet(int(now*1000)&0x7fffffff))
                        switch['movement_inputs_sent'] += 1
                    if now-deployed_at >= args.seconds:
                        break
                try:
                    transport, packet = receive(min(deadline, now+.2))
                except TimeoutError:
                    continue
                if packet[:2] == b'\x25\x11':
                    switch['joined'] = True
                elif packet[:1] == b'\x1d' and len(packet) == 5:
                    switch['death_notice'] |= struct.unpack_from('>i', packet, 1)[0] == player_id
                elif packet[:1] == b'\x15' and len(packet) == 11 and packet[5] == 1:
                    switch['old_entity_deleted'] |= struct.unpack_from('>i', packet, 6)[0] == result['spawn_state']['entity']
                elif packet[:1] == b'\x18':
                    state = spawn_state(packet)
                    if state['team'] != target_team:
                        continue  # A delayed TANK for the previous team is not deployment proof.
                    if state['entity'] == result['spawn_state']['entity'] or state['vehicle'] != 1:
                        raise ValueError('team switch did not create a new Scout')
                    if deployed_at is None:
                        if state['health'] != 1.0 or state['fuel'] != 1.0:
                            raise ValueError('Scout did not deploy at full health and fuel')
                        deployed_at = time.monotonic()
                        deadline = deployed_at+args.seconds
                        switch['spawn_state'] = state
                        switch['spawn_received_seconds'] = round(deployed_at-switching_at, 3)
            if not all((switch['joined'], switch['death_notice'], switch['old_entity_deleted'],
                        deployed_at is not None, switch['movement_inputs_sent'] >= 2)):
                raise ValueError('team switch lifecycle incomplete')
        result["phase"] = "complete"
        result["passed"] = True
    except Exception as error:
        result["error_type"] = type(error).__name__
    finally:
        if tcp is not None:
            try:
                # Let the server observe EOF, and drain its final bytes before
                # closing. SHUT_RDWR can turn delayed in-flight data into a RST.
                tcp.shutdown(socket.SHUT_WR)
                close_deadline = time.monotonic()+2
                while time.monotonic() < close_deadline:
                    tcp.settimeout(max(.01,close_deadline-time.monotonic()))
                    if not tcp.recv(65536):
                        result["clean_disconnect"] = True
                        break
            except OSError:
                pass
            tcp.close()
        if udp is not None:
            udp.close()
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    assert read_string(string("self-check"), 0) == ("self-check", 13)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=HOST)
    parser.add_argument('--expected-ip',default=EXPECTED_IP)
    parser.add_argument('--port',type=int,default=PORT)
    parser.add_argument('--bots',type=int,default=64)
    parser.add_argument('--team-capacity',type=int,default=40)
    parser.add_argument('--team',type=int,choices=(1,2),default=1)
    parser.add_argument('--seconds',type=int,choices=range(5,121),default=8,metavar='5..120')
    parser.add_argument('--drive',action='store_true',help='move off the repair pad during staging connection waves')
    parser.add_argument('--spawn-once',action='store_true',help='disable pad retries to isolate server TANK delivery recovery')
    parser.add_argument('--switch-team',action='store_true',help='after the Tank sample, change teams and verify deletion and a full-fuel Scout deployment')
    raise SystemExit(main(parser.parse_args()))
