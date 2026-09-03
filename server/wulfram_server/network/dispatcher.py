# network/dispatcher.py
from __future__ import annotations
from typing import Callable, Any

from .streams import PacketDecodeError, PacketReader


class PacketDispatcher:
    def __init__(self, on_unknown: Callable[[Any, bytes], None] | None = None):
        # TCP delivers one already-framed payload. UDP delivers a byte stream
        # containing one or more byte-aligned protocol records, so it has a
        # separate set of handlers that advance a shared PacketReader.
        self._handlers: dict[int, Callable] = {}
        self._datagram_handlers: dict[int, Callable] = {}
        self.on_unknown = on_unknown

    def route(self, opcode: int):
        """
        Decorator to register a handler for a specific opcode.
        Usage: @dispatcher.route(0x13)
        """
        def decorator(func):
            if opcode in self._handlers:
                print(f"[WARN] Overwriting handler for opcode 0x{opcode:02X}")
            self._handlers[opcode] = func
            return func
        return decorator

    def datagram_route(self, opcode: int):
        """
        Registers a UDP protocol-record handler.

        The dispatcher consumes the opcode. The handler receives the shared
        PacketReader positioned at the first body bit and must consume its own
        body. This matches the original protocol loop and keeps packet framing
        out of the UDP transport.
        """
        def decorator(func):
            if opcode in self._datagram_handlers:
                print(f"[WARN] Overwriting UDP handler for opcode 0x{opcode:02X}")
            self._datagram_handlers[opcode] = func
            return func
        return decorator

    def dispatch_payload(self, ctx: Any, payload: bytes):
        if not payload:
            return

        server = getattr(ctx, "server", None)
        trace = getattr(server, "trace", None)
        if trace is not None:
            addr = getattr(ctx, "addr", None)
            if addr is None:
                session = getattr(ctx, "session", None)
                addr = getattr(session, "address", None)
            trace.packet(
                "client_to_server",
                getattr(ctx, "transport_name", "UNKNOWN"),
                payload,
                addr=addr,
            )

        opcode = payload[0]
        handler = self._handlers.get(opcode)

        if handler:
            # Call the handler found via the decorator
            handler(ctx, payload)
        elif self.on_unknown:
            self.on_unknown(ctx, payload)
        else:
            print(f"[TCP] Unhandled opcode 0x{opcode:02X}")

    def dispatch_datagram(self, ctx: Any, payload: bytes) -> list[bytes]:
        """Dispatch every byte-aligned protocol record in one UDP payload."""
        reader = PacketReader(payload)
        dispatched: list[bytes] = []

        while reader.remaining_bits:
            if reader.remaining_bits < 8:
                padding = reader.read_bits(reader.remaining_bits)
                if padding:
                    raise PacketDecodeError("non-zero trailing UDP padding")
                break

            packet_start = reader.position_bits
            opcode = reader.read_byte()
            handler = self._datagram_handlers.get(opcode)

            if handler is None:
                # An unknown raw record has no generic length field. Preserve
                # the undecoded tail as one packet and stop rather than guessing
                # where a following opcode might begin.
                unknown_payload = payload[packet_start // 8 :]
                dispatched.append(unknown_payload)
                if self.on_unknown:
                    self.on_unknown(ctx, unknown_payload)
                else:
                    print(f"[UDP] Unhandled opcode 0x{opcode:02X}")
                break

            try:
                handler(ctx, reader)
                reader.align_to_byte(require_zero_padding=True)
            except PacketDecodeError as exc:
                raise PacketDecodeError(
                    f"malformed UDP opcode 0x{opcode:02X} at byte "
                    f"{packet_start // 8}: {exc}"
                ) from exc

            packet_end = reader.position_bits
            dispatched.append(reader.byte_slice(packet_start, packet_end))

        return dispatched
