"""Fixed-size pre-authentication reachability query for the game ports."""

from __future__ import annotations

import socket
import uuid
from collections.abc import Callable


NONCE_SIZE = 16
TCP_QUERY_MAGIC = b"\x00\x01WQ1"  # 0x0001 is not a valid legacy TCP frame length.
TCP_REPLY_MAGIC = b"\x00\x01WR1"
UDP_QUERY_MAGIC = b"\xffWQ1"       # 0xff is not a registered legacy UDP opcode.
UDP_REPLY_MAGIC = b"\xffWR1"
TCP_QUERY_SIZE = len(TCP_QUERY_MAGIC) + (NONCE_SIZE * 2)
UDP_QUERY_SIZE = len(UDP_QUERY_MAGIC) + (NONCE_SIZE * 2)


def instance_bytes(instance_id: str) -> bytes:
    return uuid.UUID(instance_id).bytes


def try_udp_query(payload: bytes, instance_id: str) -> bytes | None:
    if len(payload) != UDP_QUERY_SIZE or not payload.startswith(UDP_QUERY_MAGIC):
        return None
    nonce = payload[len(UDP_QUERY_MAGIC) : len(UDP_QUERY_MAGIC) + NONCE_SIZE]
    if payload[-NONCE_SIZE:] != bytes(NONCE_SIZE):
        return None
    # The reply is exactly the request size: this path cannot amplify UDP traffic.
    return UDP_REPLY_MAGIC + nonce + instance_bytes(instance_id)


def try_tcp_query(
    sock: socket.socket,
    instance_id: str,
    timeout: float = 0.15,
    allow_reply: Callable[[], bool] | None = None,
) -> bool:
    """Handle an immediately supplied directory query, or leave a legacy peer alone."""

    previous_timeout = sock.gettimeout()
    try:
        sock.settimeout(timeout)
        try:
            prefix = sock.recv(len(TCP_QUERY_MAGIC), socket.MSG_PEEK)
        except (BlockingIOError, TimeoutError, socket.timeout):
            return False
        if prefix != TCP_QUERY_MAGIC:
            return False
        request = bytearray()
        while len(request) < TCP_QUERY_SIZE:
            chunk = sock.recv(TCP_QUERY_SIZE - len(request))
            if not chunk:
                return True
            request.extend(chunk)
        nonce_start = len(TCP_QUERY_MAGIC)
        nonce_end = nonce_start + NONCE_SIZE
        if (
            bytes(request[:nonce_start]) == TCP_QUERY_MAGIC
            and bytes(request[nonce_end:]) == bytes(NONCE_SIZE)
            and (allow_reply is None or allow_reply())
        ):
            sock.sendall(
                TCP_REPLY_MAGIC
                + bytes(request[nonce_start:nonce_end])
                + instance_bytes(instance_id)
            )
        return True
    finally:
        sock.settimeout(previous_timeout)
