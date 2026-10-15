"""Opt-in native world scope; retail packet bodies remain unchanged."""
from contextvars import ContextVar
import struct
from .streams import PacketDecodeError

OPCODE = 0x50
HELLO = 'WulframRevival:actions-v1,combat-v1,lifecycle-v1'
HEADER = struct.Struct('>BQIIIH')
MAX_BODY = 8192 - HEADER.size - 2
UPDATE_LIMIT = 1200 - HEADER.size - 1
SERVER_UNSCOPED = frozenset((0x02, 0x1A, 0x1B, 0x1C, 0x1F))
SERVER_WORLD = frozenset((0x0D, 0x0E, 0x0F, 0x15, 0x16, 0x18, 0x1D, 0x1E, 0x25, 0x29, 0x38))
SERVER_RELIABLE = (SERVER_WORLD - {0x0D, 0x0E, 0x0F, 0x16}) | SERVER_UNSCOPED
CLIENT_WORLD = frozenset((0x09, 0x0A, 0x19, 0x20, 0x25, 0x2B, 0x39, 0x3A))
CLIENT_OWNER = frozenset((0x09, 0x0A, 0x2B, 0x3A))
ACTION_OPS = frozenset((0x09, 0x0A))
# Dispatch authorization is local to the executing thread/context, never a
# flag on a UdpContext concurrently shared by receive and simulation threads.
dispatch_session = ContextVar('native_world_session', default=None)
dispatch_epoch = ContextVar('native_world_epoch', default=None)


def newer(sequence: int, previous: int | None) -> bool:
    return previous is None or 0 < ((sequence-previous) & 0xFFFFFFFF) < 0x80000000


def encode(payload: bytes, epoch: int, owner: int = 0, sequence: int = 0, *, connection: int) -> bytes:
    if not 0 < connection < (1 << 63) or not 1 <= len(payload) <= MAX_BODY or payload[0] == OPCODE:
        raise ValueError('invalid native world body')
    return HEADER.pack(OPCODE, connection, epoch, owner, sequence, len(payload)) + payload


def decode(payload: bytes) -> tuple[int, int, int, int, bytes]:
    if len(payload) < HEADER.size+1:
        raise PacketDecodeError('truncated native world scope')
    opcode, connection, epoch, owner, sequence, size = HEADER.unpack_from(payload)
    if (opcode != OPCODE or not 0 < connection < (1 << 63) or not 1 <= size <= MAX_BODY
            or len(payload) != HEADER.size+size or payload[HEADER.size] == OPCODE):
        raise PacketDecodeError('invalid native world scope')
    return connection, epoch, owner, sequence, payload[HEADER.size:]


def validate_request_body(body: bytes) -> None:
    """One envelope is one command, never a concatenated legacy datagram."""
    opcode = body[0]
    if opcode in ACTION_OPS:
        return  # The action decoder checks EOF before applying any inputs.
    if opcode == 0x39:
        valid = body == b'\x39\x01'
    elif opcode == 0x19:
        valid = len(body) == 3
    else:
        valid = len(body) >= 5 and struct.unpack_from('>H', body, 3)[0] == len(body)
        if opcode in (0x2B, 0x3A):
            valid &= len(body) == 9
        elif opcode == 0x25:
            valid &= len(body) in (14, 22)
        elif opcode == 0x20:
            valid &= len(body) >= 12 and len(body) == 11+struct.unpack_from('>H', body, 9)[0]
    if not valid:
        raise PacketDecodeError('native request must contain exactly one complete body')
