from __future__ import annotations
from dataclasses import dataclass, field
from wulfram_server.network.streams import PacketWriter
from wulfram_server.network.translation_config import GLOBAL_CONFIGS, PRECISE_ACTION_TRANSLATION
from wulfram_server.core.config import get_ticks
from wulfram_server.network.packets.base import Packet 

@dataclass
class TranslationPacket(Packet):
    """
    Packet 0x32: TRANSLATION (Configuration)
    Configures the floating-point quantization table.
    """
    precise_actions: bool = False

    def serialize(self) -> bytes:
        pkt = PacketWriter()

        # Iterate through the Source of Truth
        for i, cfg in enumerate(GLOBAL_CONFIGS):
            if self.precise_actions and i in (10, 11):
                cfg = PRECISE_ACTION_TRANSLATION
            print(f"[DEBUG] {i}: Max={cfg['max']} Range={cfg['range']}")
            # 1. Fixed ID / Header Bits
            pkt.write_int32(cfg['head'])
            
            # 2. Padding (Ignored by client)
            pkt.write_int32(0)
            
            # 3. Max Total Bits (Resolution)
            pkt.write_int32(cfg['total'])
            
            # 4. Max Value (String)
            pkt.write_string(cfg['max'])
            
            # 5. Range Value (String)
            pkt.write_string(cfg['range'])
        
        # The client code calls Weapon_Slot_Constructor here
        # Then sends ACK2 (Command 0x33, Subcommand 2).
        
        return b'\x32' + pkt.get_bytes()
