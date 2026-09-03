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
        self.sock.sendto(payload, addr)
