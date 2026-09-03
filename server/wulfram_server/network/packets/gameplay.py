from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
from wulfram_server.network.streams import PacketWriter
from wulfram_server.network.translation_config import get_config_by_index
from .packet_config import TankPacketConfig
from wulfram_server.core.config import get_ticks
from wulfram_server.network.packets.base import Packet

# TODO: Add loop to delete more than 1 object at a time
@dataclass
class DeleteObjectPacket(Packet):
    net_id: int
    explosion: bool = True

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_byte(1) # 1 Object
        pkt.write_int32(self.net_id)
        pkt.write_byte(1 if self.explosion else 0)
        return b'\x15' + pkt.get_bytes()


@dataclass(frozen=True, slots=True)
class PositionalTransient:
    event_type: int
    position: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class EntityTransient:
    event_type: int
    entity_id: int


@dataclass(frozen=True, slots=True)
class ExplosionTransient:
    """Type 0x27 positional explosion with an entity type sound selector.

    The stock client routes this through its type-specific explosion sound and
    particle dispatch without creating the delete packet's dynamic light.
    """

    position: tuple[float, float, float]
    entity_type: int
    event_type: int = 0x27


@dataclass(frozen=True, slots=True)
class TransientArrayPacket(Packet):
    """Packet 0x0D carrying accepted one-shot client presentation events.

    ProcessTransientArrayPacket at 0x0046CA60 reads an eight-bit count. For a
    normal vehicle event, UpdateLocalVehicleContactSounds at 0x0046AF00 writes
    the transient type and then either an explicit compressed XYZ or a 32-bit
    entity reference. Unlike update-array vectors, explicit positions carry no
    precision header: the reader selects a fixed midpoint precision from
    translation slot 16.
    """

    events: Sequence[PositionalTransient | EntityTransient | ExplosionTransient]

    def serialize(self) -> bytes:
        if len(self.events) > 0xFF:
            raise ValueError("TRANSIENT_ARRAY supports at most 255 events")

        pkt = PacketWriter()
        pkt.write_byte(len(self.events))
        event_type_config = get_config_by_index(12)
        if event_type_config.max_total_bits > 0:
            raise ValueError("transient event types require a fixed-width translation slot")
        event_type_bits = event_type_config.precision_base_bits

        position_config = get_config_by_index(16)
        maximum_position_bits = (
            position_config.max_total_bits
            if position_config.max_total_bits > 0
            else position_config.precision_base_bits
        )
        # ProcessTransientArrayPacket (0x0046CA60) interpolates halfway from
        # the configured base to maximum precision using the executable's 0.5
        # constant, then CVTTSD2SI truncates the result. With the current
        # translation packet this is eight bits per component. Crucially, no
        # per-vector or per-component precision header appears on the wire.
        position_bits = int(
            position_config.precision_base_bits
            + (maximum_position_bits - position_config.precision_base_bits) * 0.5
        )
        position_priority = position_bits - position_config.precision_base_bits

        for event in self.events:
            if event.event_type < 0 or event.event_type >= (1 << event_type_bits):
                raise ValueError(f"transient event type {event.event_type} is out of range")
            pkt.write_bits(event.event_type, event_type_bits)
            if isinstance(event, ExplosionTransient):
                if event.entity_type < 0 or event.entity_type > 0xFFFFFFFF:
                    raise ValueError(
                        f"explosion entity type {event.entity_type} is out of range"
                    )
                # ProcessTransientArrayPacket special-cases type 0x27 and
                # consumes this selector before its explicit XYZ.
                pkt.write_bool(True)
                pkt.write_int32(event.entity_type)
                for component in event.position:
                    _, compressed, bit_count = position_config.compress(
                        float(component),
                        priority=position_priority,
                    )
                    if bit_count != position_bits:
                        raise ValueError("transient position precision is inconsistent")
                    pkt.write_bits(compressed, bit_count)
            elif isinstance(event, PositionalTransient):
                pkt.write_bool(True)  # Explicit position rather than an entity ID.
                for component in event.position:
                    _, compressed, bit_count = position_config.compress(
                        float(component),
                        priority=position_priority,
                    )
                    if bit_count != position_bits:
                        raise ValueError("transient position precision is inconsistent")
                    pkt.write_bits(compressed, bit_count)
            elif isinstance(event, EntityTransient):
                if event.entity_id < 0 or event.entity_id > 0xFFFFFFFF:
                    raise ValueError(f"transient entity ID {event.entity_id} is out of range")
                pkt.write_bool(False)
                pkt.write_int32(event.entity_id)
            else:
                raise TypeError(f"unsupported transient event {type(event).__name__}")
            pkt.write_bool(False)  # No optional secondary entity/reference.

        return b'\x0D' + pkt.get_bytes()

@dataclass
class DockingPacket(Packet):
    # Client lookup target for repair/refuel behavior. A missing entity (the
    # server uses 0xFFFFFFFF) means ordinary ground docking with no pad UI.
    entity_id: int
    is_docked: bool
    # Barrier compared with the local entity's UPDATE_ARRAY sequence. A newer
    # soft update clears docking; a hard update does not.
    sequence_id: int | None = None

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks() if self.sequence_id is None else self.sequence_id)
        pkt.write_int32(self.entity_id)
        pkt.write_byte(1 if self.is_docked else 0)
        return b'\x38' + pkt.get_bytes()

@dataclass
class CarryingInfoPacket(Packet):
    player_id: int
    has_cargo: bool
    unk_v2: int
    item_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_byte(1 if self.has_cargo else 0)
        pkt.write_byte(self.unk_v2)
        pkt.write_byte(self.item_id)
        return b'\x29' + pkt.get_bytes()
    
@dataclass
class ResetGamePacket(Packet):
    # 0x3F - RESET_GAME
    def serialize(self) -> bytes:
        return b'\x3F'
