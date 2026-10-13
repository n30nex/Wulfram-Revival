"""Deterministic packet faults plus a real loopback TCP/UDP relay journey."""
import json
from pathlib import Path
import runpy
import socket
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

LAB = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/network-lab.py'))


def frame(payload):
    return struct.pack('>H',len(payload)+2)+payload


def hello(port):
    host = b'127.0.0.1\0'
    return frame(b'\x13\x01'+struct.pack('>HHH',port,1,len(host))+host)


class NetworkLabTests(unittest.TestCase):
    def test_fragmented_tcp_preserves_unrelated_payloads_and_checks_endpoint(self):
        rewrite = LAB['rewrite_server_frames']
        original = hello(2628)+frame(b'\x13\x02private-test-key')
        buffer = bytearray()
        output = []
        for byte in original:
            buffer.append(byte)
            output.extend(rewrite(buffer,('127.0.0.1',2628),2631))
        self.assertFalse(buffer)
        self.assertEqual(b''.join(output),hello(2631)+frame(b'\x13\x02private-test-key'))
        with self.assertRaises(ValueError):
            rewrite(bytearray(hello(9999)),('127.0.0.1',2628),2631)
        with self.assertRaises(ValueError):
            rewrite(bytearray(b'\xff\xff'),('127.0.0.1',2628),2631)

    def test_first_spawn_loss_is_single_shot_and_diagnostics_omit_payloads(self):
        schedule = LAB['DatagramSchedule'](LAB['PROFILES']['spawn-loss'],2627)
        schedule.add('server',b'\x18private-payload',0)
        schedule.add('server',b'\x18private-payload',0)
        self.assertEqual(list(schedule.due(0)),[('server',b'\x18private-payload')])
        self.assertEqual(schedule.counts['server:dropped:18'],1)
        self.assertNotIn('private',json.dumps(dict(schedule.counts)))
        self.assertEqual(schedule.bytes,0)

    def test_seeded_jitter_reorders_and_duplicates_without_growing_unbounded(self):
        outcomes = []
        for _ in range(2):
            schedule = LAB['DatagramSchedule'](LAB['PROFILES']['reorder'],2627)
            for index in range(100): schedule.add('client',b'\x09'+struct.pack('>H',index),0)
            self.assertFalse(list(schedule.due(0)))
            delivered = list(schedule.due(1))
            outcomes.append(delivered)
            self.assertGreater(len(delivered),100)
            self.assertGreater(schedule.counts['client:delivered_out_of_order'],0)
            self.assertEqual(schedule.bytes,0)
        self.assertEqual(*outcomes)
        schedule = LAB['DatagramSchedule'](LAB['PROFILES']['clean'],2627)
        with self.assertRaises(BufferError):
            for _ in range(100): schedule.add('server',b'x'*4096,0)
        self.assertLessEqual(schedule.bytes,LAB['MAX_BUFFER'])

    def test_datagram_delivery_is_counted_only_after_successful_send(self):
        schedule = LAB['DatagramSchedule'](LAB['PROFILES']['clean'],2627)
        schedule.add('server',b'\x0ctest-pong',0)
        pending = schedule.due(0)
        self.assertEqual(next(pending),('server',b'\x0ctest-pong'))
        self.assertEqual(schedule.delivered['server'],0)
        pending.close()  # A missing peer or failed send aborts the relay here.
        self.assertEqual(schedule.delivered['server'],0)

    def test_delayed_tcp_preserves_final_frames_in_both_half_close_directions(self):
        errors = []
        with tempfile.TemporaryDirectory() as folder, \
                socket.socket(socket.AF_INET,socket.SOCK_STREAM) as upstream_tcp:
            upstream_tcp.bind(('127.0.0.1',0)); upstream_tcp.listen(1); upstream_tcp.settimeout(5)
            target = upstream_tcp.getsockname()
            final_response = frame(b'\x22final-response')
            def upstream():
                try:
                    connection,_ = upstream_tcp.accept()
                    with connection:
                        connection.settimeout(5)
                        connection.sendall(hello(target[1]))
                        incoming = bytearray()
                        while len(incoming) < 5:
                            data = connection.recv(5-len(incoming))
                            if not data: raise EOFError('client FIN overtook its final frame')
                            incoming.extend(data)
                        self.assertEqual(incoming,b'\0\5\x21hi')
                        self.assertEqual(connection.recv(1),b'')
                        connection.sendall(final_response)
                        connection.shutdown(socket.SHUT_WR)
                except Exception as error: errors.append(error)
            upstream_thread = threading.Thread(target=upstream,daemon=True)
            upstream_thread.start()
            report = Path(folder)/'report.json'
            args = SimpleNamespace(upstream_ip=target[0],upstream_port=target[1],listen_port=0,
                                   profile='latency',seed=2627,seconds=10,report=report)
            result = []
            relay_thread = threading.Thread(target=lambda:result.append(LAB['run'](args)),daemon=True)
            relay_thread.start()
            deadline = time.monotonic()+5
            while not report.exists() and time.monotonic() < deadline: time.sleep(.01)
            destination = ('127.0.0.1',json.loads(report.read_text())['listen_port'])
            with socket.create_connection(destination,timeout=5) as client:
                client.settimeout(5)
                expected = hello(destination[1]); actual = bytearray()
                while len(actual) < len(expected):
                    data = client.recv(len(expected)-len(actual))
                    if not data: raise EOFError('server FIN overtook its HELLO')
                    actual.extend(data)
                self.assertEqual(actual,expected)
                client.sendall(b'\0\5\x21hi')
                client.shutdown(socket.SHUT_WR)
                actual = bytearray()
                while data := client.recv(4096): actual.extend(data)
                self.assertEqual(actual,final_response)
            relay_thread.join(5); upstream_thread.join(5)
            self.assertFalse(relay_thread.is_alive() or upstream_thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(result,[0])
            document = json.loads(report.read_text())
            self.assertEqual(document['status'],'complete')
            self.assertEqual(document['closed_by'],'client')
            self.assertEqual(document['tcp_bytes']['client'],5)
            self.assertEqual(document['pending_udp_datagrams'],0)

    def test_loopback_relay_carries_tcp_and_udp_and_rejects_a_second_udp_peer(self):
        errors = []
        with tempfile.TemporaryDirectory() as folder, \
                socket.socket(socket.AF_INET,socket.SOCK_STREAM) as upstream_tcp, \
                socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as upstream_udp:
            upstream_tcp.bind(('127.0.0.1',0)); upstream_tcp.listen(1); upstream_tcp.settimeout(5)
            target = upstream_tcp.getsockname()
            upstream_udp.bind(target); upstream_udp.settimeout(5)
            def upstream():
                try:
                    connection,_ = upstream_tcp.accept()
                    with connection:
                        connection.settimeout(5)
                        connection.sendall(hello(target[1]))
                        incoming = bytearray()
                        while len(incoming) < 5: incoming.extend(connection.recv(5-len(incoming)))
                        self.assertEqual(incoming,b'\0\5\x21hi')
                        for _ in range(2):
                            data,peer = upstream_udp.recvfrom(4096)
                            self.assertEqual(data,b'\x0btest-ping')
                            upstream_udp.sendto(b'\x0ctest-pong',peer)
                        connection.recv(1)  # Wait for the relay's clean close.
                except Exception as error: errors.append(error)
            upstream_thread = threading.Thread(target=upstream,daemon=True)
            upstream_thread.start()
            report = Path(folder)/'report.json'
            args = SimpleNamespace(upstream_ip=target[0],upstream_port=target[1],listen_port=0,
                                   profile='clean',seed=2627,seconds=10,report=report)
            result = []
            relay_thread = threading.Thread(target=lambda:result.append(LAB['run'](args)),daemon=True)
            relay_thread.start()
            deadline = time.monotonic()+5
            while not report.exists() and time.monotonic() < deadline: time.sleep(.01)
            destination = ('127.0.0.1',json.loads(report.read_text())['listen_port'])
            with socket.create_connection(destination,timeout=5) as client, \
                    socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp, \
                    socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as unexpected:
                client.settimeout(5); udp.settimeout(5)
                expected = hello(destination[1]); actual = bytearray()
                while len(actual) < len(expected): actual.extend(client.recv(len(expected)-len(actual)))
                self.assertEqual(actual,expected)
                client.sendall(b'\0\5\x21hi')
                udp.sendto(b'\x0btest-ping',destination)
                self.assertEqual(udp.recv(4096),b'\x0ctest-pong')
                unexpected.sendto(b'not-this-client',destination)
                udp.sendto(b'\x0btest-ping',destination)
                self.assertEqual(udp.recv(4096),b'\x0ctest-pong')
            relay_thread.join(5); upstream_thread.join(5)
            self.assertFalse(relay_thread.is_alive() or upstream_thread.is_alive())
            self.assertFalse(errors)
            self.assertEqual(result,[0])
            document = json.loads(report.read_text())
            self.assertEqual(document['status'],'complete')
            self.assertEqual(document.get('ignored_udp_peers'),1)
            self.assertNotIn('test-ping',report.read_text())


if __name__ == '__main__': unittest.main()
