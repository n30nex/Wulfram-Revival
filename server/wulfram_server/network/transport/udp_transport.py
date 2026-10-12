# network/transport/udp_transport.py
from __future__ import annotations
import socket


class UdpTransport:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def send(self, payload: bytes, addr: tuple[str, int]) -> None:
        """
        Sends a packet payload (Opcode + Body) to the specified address.
        """
        try:
            self.sock.sendto(payload, addr)
        except BlockingIOError:
            # A saturated interface drops a datagram instead of freezing the
            # authoritative game loop. The following snapshot repairs state.
            pass
