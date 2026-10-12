"""Retail decoder layout (0047d4b0), independent of the server PacketReader."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from wulfram_server.core.entity import GameEntity, UpdateMask
from wulfram_server.network.packets.behavior import BehaviorPacket
from wulfram_server.network.packets.packet_config import PacketConfig
from wulfram_server.network.packets.tank import TankPacket
from wulfram_server.network.packets.update_array import UpdateArrayPacket


class RetailBits:
    def __init__(self, data):
        self.bits = "".join(f"{byte:08b}" for byte in data)
        self.offset = 0

    def take(self, width):
        value = self.bits[self.offset:self.offset + width]
        assert len(value) == width
        self.offset += width
        return int(value or "0", 2)

    def finish(self):
        padding = self.bits[self.offset:]
        assert len(padding) < 8 and "1" not in padding


class ScoutWireTests(unittest.TestCase):
    def test_scout_spawn_and_snapshot_match_announced_weapon_flags(self):
        cfg = PacketConfig.load(str(ROOT / "server/wulfram_server/content/packets.toml"))
        behavior = BehaviorPacket(cfg.behavior, cfg.combat, cfg.jet_layout_profile).serialize()
        # The retail BEHAVIOR loader reads a 95-byte header and 13 fixed
        # 45-byte records per table. Table 1 is Scout: all five flags are zero.
        for slot in range(13):
            offset = 96 + (13 + slot) * 45
            self.assertEqual(behavior[offset:offset + 5], bytes(5))

        def read_scout_vitals(bits):
            self.assertEqual(bits.take(1), 1)
            self.assertEqual(bits.take(5), 1)
            self.assertEqual(bits.take(10), 1)  # Full health.
            self.assertEqual(bits.take(10), 1)  # Full fuel.
            # The executable consumes zero active bits and no optional scalars
            # for the all-disabled table above; the next field starts HERE.

        spawn = TankPacket(net_id=0x12345678, sequence_id=123, tank_cfg=cfg.tank,
                           unit_type=1, team_id=2, weapon_table_id=1,
                           pos=(10.0, 20.0, 30.0), rot=(0.0, 0.0, 0.0)).serialize()
        self.assertEqual(spawn[0], 0x18)
        bits = RetailBits(spawn[1:])
        self.assertEqual(bits.take(32), 123)
        read_scout_vitals(bits)
        self.assertEqual(bits.take(32), 1)
        self.assertEqual(bits.take(32), 0x12345678)
        self.assertEqual(bits.take(8), 2)
        self.assertEqual([bits.take(32) for _ in range(6)], [10 << 16, 20 << 16, 30 << 16, 0, 0, 0])
        bits.finish()

        snapshot = UpdateArrayPacket(sequence_id=123, is_view_update=True)
        snapshot.set_local_stats(1.0, 1.0, weapon_table_id=1)
        entity = GameEntity(net_id=0x12345678, unit_type=1, team_id=2)
        snapshot.add_entity(entity, forced_mask=UpdateMask.DEFINITION)
        bits = RetailBits(snapshot.get_bytes())
        bits.take(32)  # Timestamp.
        self.assertEqual(bits.take(32), 123)
        read_scout_vitals(bits)
        self.assertEqual(bits.take(8), 1)  # One entity, immediately after vitals.
        self.assertEqual(bits.take(32), entity.net_id)
        self.assertEqual(bits.take(1), 1)
        self.assertEqual(bits.take(10), UpdateMask.DEFINITION)
        self.assertEqual(bits.take(16), 0)
        self.assertEqual([bits.take(8) for _ in range(3)], [1, 2, 2])
        self.assertEqual(bits.take(1), 1)
        bits.finish()


if __name__ == "__main__":
    unittest.main()
