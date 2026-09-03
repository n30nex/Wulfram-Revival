from __future__ import annotations
from dataclasses import dataclass, field
from wulfram_server.network.streams import PacketWriter
from .packet_config import TankPacketConfig
from wulfram_server.core.config import get_ticks
from wulfram_server.network.packets.base import Packet 
from wulfram_server.network.translation_config import get_config_by_index

@dataclass
class TankPacket(Packet):
    net_id: int
    sequence_id: int
    tank_cfg: TankPacketConfig = field(repr=False) # specific config for this packet type
    
    # Optional overrides (default to None so we can fallback to config)
    unit_type: int | None = None
    team_id: int | None = None
    pos: tuple[float, float, float] | None = None
    rot: tuple[float, float, float] | None = None
    weapon_table_id: int = 0
    weapon_ready_mask: int = 0
    pulse_charge: float = 1.0

    def serialize(self) -> bytes:
        # 1. Resolve Defaults
        # We prefer the instance value; if None, fallback to the config object
        _unit_type = self.unit_type if self.unit_type is not None else self.tank_cfg.unit_type
        _team_id = self.team_id if self.team_id is not None else self.tank_cfg.team_id
        _pos = self.pos if self.pos is not None else self.tank_cfg.default_pos
        _rot = self.rot if self.rot is not None else self.tank_cfg.default_rot

        # 2. Build the Payload
        pkt = PacketWriter()
        pkt.write_int32(self.sequence_id if self.sequence_id is not None else get_ticks())

        stats = self.tank_cfg.stats
        pkt.write_bits(1 if stats.include_vitals else 0, 1)

        if stats.include_vitals:
            pkt.write_bits(self.weapon_table_id, 5)
            pkt.write_bits(stats.health_mult_bits, 10)
            pkt.write_bits(stats.energy_mult_bits, 10)
            if self.weapon_table_id == 0:
                # Behavior enables ready/active channels for Tank slots 0 and
                # 4, followed by the configured pulse-charge scalar.
                pkt.write_bits(self.weapon_ready_mask & 0b11, 2)
                pulse_config = get_config_by_index(13)
                _, pulse_value, pulse_bits = pulse_config.compress(self.pulse_charge)
                pkt.write_bits(pulse_value, pulse_bits)
            elif self.weapon_table_id == 1:
                # Scout enables machine-gun and repair firing-state channels.
                # Its available repair slot also requires translation scalar 14.
                pkt.write_bits(self.weapon_ready_mask & 0b11, 2)
                repair_config = get_config_by_index(14)
                _, repair_value, repair_bits = repair_config.compress(1.0)
                pkt.write_bits(repair_value, repair_bits)

        pkt.write_int32(_unit_type)
        pkt.write_int32(self.net_id)
        pkt.write_byte(_team_id)
        pkt.write_vector3(_pos[0], _pos[1], _pos[2])
        pkt.write_vector3(_rot[0], _rot[1], _rot[2])

        # 3. Return with Opcode (0x18)
        return b"\x18" + pkt.get_bytes()
