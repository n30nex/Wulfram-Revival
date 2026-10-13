"""One-client loopback relay for reproducible retail TCP/UDP network tests.

Packets and credentials stay in memory. The report contains profile parameters,
opcode counters and queue bounds; pair it with client-lab gameplay evidence.
"""
import argparse
from collections import Counter, deque
from contextlib import ExitStack
import heapq
import ipaddress
import json
from pathlib import Path
import random
import select
import socket
import struct
import time

PROFILES = {
    'clean': dict(delay_ms=0, jitter_ms=0, loss=0, duplicate=0, drop_first=()),
    'latency': dict(delay_ms=80, jitter_ms=30, loss=0, duplicate=0, drop_first=()),
    'reorder': dict(delay_ms=60, jitter_ms=60, loss=0, duplicate=.1, drop_first=()),
    'loss': dict(delay_ms=50, jitter_ms=30, loss=.05, duplicate=.02, drop_first=()),
    'bootstrap-loss': dict(delay_ms=0, jitter_ms=0, loss=0, duplicate=0, drop_first=('1303','03')),
    'spawn-loss': dict(delay_ms=0, jitter_ms=0, loss=0, duplicate=0, drop_first=('18',)),
}
MAX_BUFFER = 128*1024
MAX_DATAGRAM = 4096
MAX_QUEUED_DATAGRAMS = 512


def packet_kind(data):
    if len(data) >= 3 and struct.unpack_from('>H',data)[0] == len(data):
        data = data[2:]
    return data[:2].hex() if data[:1] == b'\x13' else data[:1].hex()


def rewrite_server_frames(buffer, upstream, port):
    """Preserve framing and all payloads except the advertised UDP endpoint."""
    result = []
    while len(buffer) >= 2:
        length = struct.unpack_from('>H',buffer)[0]
        if not 3 <= length <= 10240:
            raise ValueError('TCP frame outside retail bounds')
        if len(buffer) < length:
            break
        payload = bytes(buffer[2:length])
        del buffer[:length]
        if payload[:2] == b'\x13\x01':
            if len(payload) < 9:
                raise ValueError('short advertised endpoint')
            actual_port, count, size = struct.unpack_from('>HHH',payload,2)
            if count != 1 or size == 0 or len(payload) != 8+size or payload[-1] != 0:
                raise ValueError('invalid advertised endpoint')
            if (payload[8:-1].decode('ascii'),actual_port) != upstream:
                raise ValueError('upstream advertised a different endpoint')
            host = b'127.0.0.1\0'
            payload = b'\x13\x01'+struct.pack('>HHH',port,1,len(host))+host
        result.append(struct.pack('>H',len(payload)+2)+payload)
    return result


class DatagramSchedule:
    def __init__(self, profile, seed):
        self.profile = profile
        self.random = {side:random.Random(seed+index) for index,side in enumerate(('client','server'))}
        self.queue = []
        self.bytes = 0
        self.serial = 0
        self.seen = Counter()
        self.delivered = Counter()
        self.last_delivered = Counter()
        self.counts = Counter()
        self.dropped_once = set()

    def add(self, side, data, now):
        if not data or len(data) > MAX_DATAGRAM:
            raise ValueError('datagram outside lab bounds')
        self.seen[side] += 1
        ordinal = self.seen[side]
        kind = packet_kind(data)
        self.counts[f'{side}:received:{kind}'] += 1
        rng = self.random[side]
        forced = side == 'server' and kind in self.profile['drop_first'] and kind not in self.dropped_once
        if forced:
            self.dropped_once.add(kind)
        if forced or rng.random() < self.profile['loss']:
            self.counts[f'{side}:dropped:{kind}'] += 1
            return
        copies = 2 if rng.random() < self.profile['duplicate'] else 1
        if copies == 2:
            self.counts[f'{side}:duplicated'] += 1
        for _ in range(copies):
            if len(self.queue) >= MAX_QUEUED_DATAGRAMS or self.bytes+len(data) > MAX_BUFFER:
                raise BufferError('datagram schedule exceeded its bound')
            delay = max(0,self.profile['delay_ms']+rng.uniform(-self.profile['jitter_ms'],self.profile['jitter_ms']))/1000
            self.serial += 1
            heapq.heappush(self.queue,(now+delay,self.serial,side,ordinal,data))
            self.bytes += len(data)
        self.counts['peak_queued_bytes'] = max(self.counts['peak_queued_bytes'],self.bytes)
        self.counts['peak_queued_datagrams'] = max(self.counts['peak_queued_datagrams'],len(self.queue))

    def due(self, now):
        while self.queue and self.queue[0][0] <= now:
            _,_,side,ordinal,data = heapq.heappop(self.queue)
            self.bytes -= len(data)
            self.delivered[side] += 1
            if ordinal < self.last_delivered[side]:
                self.counts[f'{side}:delivered_out_of_order'] += 1
            self.last_delivered[side] = max(ordinal,self.last_delivered[side])
            yield side,data


def run(args):
    upstream = (str(ipaddress.IPv4Address(args.upstream_ip)),args.upstream_port)
    if args.report.exists() or args.report.is_symlink():
        raise ValueError('refusing to overwrite a lab report')
    profile = PROFILES[args.profile]
    schedule = DatagramSchedule(profile,args.seed)
    report = {'status':'starting','profile':args.profile,'parameters':profile,'seed':args.seed,
              'tcp_bytes':{'client':0,'server':0},'peak_tcp_queued_bytes':0}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    started = time.monotonic()
    def save():
        report.update(elapsed_seconds=round(time.monotonic()-started,3),
                      udp=dict(schedule.counts),udp_delivered=dict(schedule.delivered))
        temporary = args.report.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        temporary.replace(args.report)

    try:
        with ExitStack() as sockets:
            def new_socket(kind):
                sock = sockets.enter_context(socket.socket(socket.AF_INET,kind))
                return sock
            listener = new_socket(socket.SOCK_STREAM)
            listener.bind(('127.0.0.1',args.listen_port)); listener.listen(1)
            port = listener.getsockname()[1]
            down_udp = new_socket(socket.SOCK_DGRAM)
            down_udp.bind(('127.0.0.1',port))
            report.update(status='ready',listen_port=port)
            save()
            listener.settimeout(args.seconds)
            client, address = listener.accept()
            sockets.enter_context(client)
            listener.close()  # A second client cannot share this session/key.
            server = sockets.enter_context(socket.create_connection(upstream,timeout=8))
            up_udp = new_socket(socket.SOCK_DGRAM)
            up_udp.connect(upstream)
            for sock in (client,server,down_udp,up_udp): sock.setblocking(False)
            report['status'] = 'connected'
            udp_peer = None
            server_input = bytearray()
            outputs = {client:deque(),server:deque()}
            queued_bytes = Counter()
            last_due = Counter()
            next_report = 0
            def enqueue(destination, data, now):
                queued_bytes[destination] += len(data)
                if queued_bytes[destination] > MAX_BUFFER:
                    raise BufferError('TCP output exceeded its bound')
                due = max(last_due[destination],now+profile['delay_ms']/1000)
                last_due[destination] = due
                outputs[destination].append((due,data))
                report['peak_tcp_queued_bytes'] = max(report['peak_tcp_queued_bytes'],queued_bytes[destination])
            while time.monotonic()-started < args.seconds:
                now = time.monotonic()
                for side,data in schedule.due(now):
                    try:
                        if side == 'client': up_udp.send(data)
                        elif udp_peer is not None: down_udp.sendto(data,udp_peer)
                    except BlockingIOError:
                        raise BufferError('host could not deliver the selected profile')
                writable = [sock for sock,queue in outputs.items() if queue and queue[0][0] <= now]
                readable, writable, _ = select.select([client,server,down_udp,up_udp],writable,[],.005)
                for sock in writable:
                    due,data = outputs[sock][0]
                    try: sent = sock.send(data)
                    except BlockingIOError: continue
                    if not sent: raise ConnectionError('TCP write closed')
                    queued_bytes[sock] -= sent
                    if sent == len(data): outputs[sock].popleft()
                    else: outputs[sock][0] = (due,data[sent:])
                for sock in readable:
                    if sock in (client,server):
                        data = sock.recv(65536)
                        if not data:
                            report.update(status='complete',closed_by='client' if sock is client else 'server')
                            save()
                            return 0
                        side = 'client' if sock is client else 'server'
                        report['tcp_bytes'][side] += len(data)
                        if sock is client:
                            enqueue(server,data,now)
                        else:
                            server_input.extend(data)
                            if len(server_input) > MAX_BUFFER: raise BufferError('TCP input exceeded its bound')
                            for frame in rewrite_server_frames(server_input,upstream,port): enqueue(client,frame,now)
                    elif sock is down_udp:
                        data, peer = down_udp.recvfrom(MAX_DATAGRAM+1)
                        if peer[0] != address[0] or (udp_peer is not None and peer != udp_peer):
                            report['ignored_udp_peers'] = report.get('ignored_udp_peers',0)+1
                            continue
                        udp_peer = peer
                        schedule.add('client',data,now)
                    else:
                        schedule.add('server',up_udp.recv(MAX_DATAGRAM+1),now)
                if now >= next_report:
                    save(); next_report = now+1
            raise TimeoutError('lab duration ended before the client disconnected')
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__,error=str(error))
        save()
        return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream-ip',required=True)
    parser.add_argument('--upstream-port',type=int,choices=range(1,65536),required=True)
    parser.add_argument('--listen-port',type=int,choices=range(1024,65536),default=2631)
    parser.add_argument('--profile',choices=PROFILES,default='clean')
    parser.add_argument('--seed',type=int,default=2627)
    parser.add_argument('--seconds',type=int,choices=range(10,601),default=240,metavar='10..600')
    parser.add_argument('--report',type=Path,required=True)
    raise SystemExit(run(parser.parse_args()))
