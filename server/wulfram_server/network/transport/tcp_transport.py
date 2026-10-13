# network/transport/tcp_transport.py
from __future__ import annotations
import socket
import select
import threading
import time
import queue
from typing import Optional
from .envelope import TcpEnvelope

def recv_exact(sock: socket.socket, n: int, deadline: float | None = None) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("TCP frame deadline expired")
        if not select.select([sock], [], [], remaining)[0]:
            raise TimeoutError("TCP frame deadline expired")
        try:
            chunk = sock.recv(n - len(buf))
        except BlockingIOError:
            continue
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)

class TcpTransport:
    def __init__(self, sock: socket.socket, *, on_error=None):
        self.sock = sock
        self.read_timeout = sock.gettimeout()
        self.sock.setblocking(False)
        self.send_lock = threading.Lock()
        self.closed = threading.Event()
        self.outbox = queue.Queue(maxsize=128) if on_error is not None else None
        self.writer = None
        if self.outbox is not None:
            self.writer = threading.Thread(target=self._write_loop, args=(on_error,),
                                           name="wulfram-tcp-writer", daemon=True)
            self.writer.start()

    def send_payload(self, payload: bytes) -> None:
        if self.closed.is_set():
            raise ConnectionError("TCP transport is closed")
        if self.outbox is not None:
            if not 1 <= len(payload) <= 8190:
                raise ValueError("Invalid outbound TCP frame length")
            try:
                self.outbox.put_nowait(bytes(payload))
            except queue.Full as error:
                raise ConnectionError("TCP peer is not keeping up") from error
        else:
            self._write_payload(payload)

    def _write_loop(self, on_error) -> None:
        try:
            while not self.closed.is_set():
                payload = self.outbox.get()
                if payload is None:
                    return
                self._write_payload(payload)
        except (OSError, ValueError):
            on_error()
        finally:
            self.closed.set()

    def close(self) -> None:
        self.closed.set()
        if self.outbox is not None:
            try:
                self.outbox.put_nowait(None)
            except queue.Full:
                pass

    def _write_payload(self, payload: bytes) -> None:
        framed = TcpEnvelope.encode(payload)
        if not self.send_lock.acquire(timeout=2.0):
            raise TimeoutError("TCP writer stalled")
        try:
            deadline = time.monotonic() + 2.0
            pending = memoryview(framed)
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.sock], [], remaining)[1]:
                    raise TimeoutError("TCP writer stalled")
                try:
                    sent = self.sock.send(pending)
                except BlockingIOError:
                    continue
                if not sent:
                    raise ConnectionError("TCP peer closed")
                pending = pending[sent:]
        finally:
            self.send_lock.release()

    def recv_payload(self, *, deadline: float | None = None) -> Optional[bytes]:
        if deadline is None and self.read_timeout:
            deadline = time.monotonic() + self.read_timeout
        first = recv_exact(self.sock, 1, deadline)
        if first is None:
            return None
        # Idle authenticated clients may use UDP only. Once a frame starts,
        # all of it must arrive within five seconds, including a partial header.
        deadline = min(deadline, time.monotonic() + 5.0) if deadline else time.monotonic() + 5.0
        rest = recv_exact(self.sock, 1, deadline)
        if rest is None:
            return None
        hdr = first + rest
        total_len = TcpEnvelope.decode_header(hdr)
        if not 3 <= total_len <= 8192:
            raise ValueError("Invalid inbound TCP frame length")
        body = recv_exact(self.sock, total_len - 2, deadline)
        return body
