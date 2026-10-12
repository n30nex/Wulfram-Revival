from __future__ import annotations
from wulfram_server.network.streams import PacketWriter
from dataclasses import dataclass, field
from wulfram_server.network.packets.base import Packet
from wulfram_server.core.config import get_ticks

@dataclass
class ReincarnatePacket(Packet):
    """
    Packet 0x25: REINCARNATE
    """
    code: int
    message: str = ""

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_byte(self.code)
        pkt.write_string(self.message)
        return b'\x25' + pkt.get_bytes()

@dataclass
class BirthNoticePacket(Packet):
    """
    Packet 0x1E: BIRTH

    Associates a roster player with their current live vehicle.  The client
    uses entity_id to resolve targeted vehicles back to player names.
    """
    player_id: int
    entity_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_int32(self.entity_id)
        return b'\x1E' + pkt.get_bytes()

@dataclass
class DeathNoticePacket(Packet):
    """
    Packet 0x1D: DEATH_NOTICE
    """
    player_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        return b'\x1D' + pkt.get_bytes()

@dataclass
class RemoveFromRosterPacket(Packet):
    """
    Packet 0x1B: REMOVE_FROM_ROSTER
    """
    account_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.account_id)
        return b'\x1B' + pkt.get_bytes()

@dataclass
class AddToRosterPacket(Packet):
    """
    Packet 0x1A: ADD_TO_ROSTER
    """
    account_id: int
    team: int
    name: str
    nametag: str
    total_kills: int = 0
    total_deaths: int = 0

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.account_id)
        pkt.write_int32(0)   # unknown
        pkt.write_int16(self.team)    # team
        pkt.write_int16(2)            # Preserve the legacy non-stat field.
        pkt.write_string(self.name)
        pkt.write_string(self.nametag)
        pkt.write_int16(min(65535, self.total_kills))
        pkt.write_int16(min(65535, self.total_deaths))
        pkt.write_fixed1616(0.0)      # Kudos are not fabricated.
        pkt.write_int32(2)            # Preserve the legacy trailing field.

        return b'\x1A' + pkt.get_bytes()

@dataclass
class CommMessagePacket(Packet):
    """
    Packet 0x1F: COMM_MESSAGE
    """
    message_type: int
    source_player_id: int
    chat_scope_id: int
    recepient_id: int
    message: str

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int16(self.message_type) # Message Class/Type
        pkt.write_int32(self.source_player_id) # Source Player ID
        pkt.write_int16(self.chat_scope_id) # Chat Channel/Scope (0 = Global, 4 = Team, 5 = Command/Console)
        pkt.write_int32(self.recepient_id) # Recipient ID (only used for whispers i believe)
        pkt.write_string(self.message)
        
        return b'\x1F' + pkt.get_bytes()

@dataclass
class UpdateStatsPacket(Packet):
    """
    Packet 0x1C: UPDATE_STATS
        [Type 0x1C]
        [Int32] Account ID
        [Int32] Team ID
        [Int16] Stat 1
        [Int16] Stat 2
        [Int16] Stat 3
        [Int16] Stat 4
        [Int16] Stat 5
        [Double] Value 1
        [Double] Value 2
        [Int32] Extra / Flags
    """
    player_id: int
    team_id: int
    total_kills: int = 0
    total_deaths: int = 0
    round_kills: int = 0

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        
        pkt.write_int32(self.player_id)
        pkt.write_int32(6)              # Preserve the legacy non-stat field.
        pkt.write_int16(self.team_id)   # Team ID
        pkt.write_int16(33)             # Preserve the legacy non-stat field.
        
        # 3 Stats (Shorts)
        # Retail roster +0x18/+0x1c form the displayed kill/death ratio;
        # +0x20 is the current match's Kills counter (decoder 0x0046d730).
        pkt.write_int16(min(65535, self.total_kills))
        pkt.write_int16(min(65535, self.total_deaths))
        pkt.write_int16(min(65535, self.round_kills))
        
        # Fixed Point values
        pkt.write_fixed1616(0.0)
        pkt.write_fixed1616(0.0)
        
        pkt.write_int32(10)          # Preserve the legacy trailing field.
        return b'\x1C' + pkt.get_bytes()
