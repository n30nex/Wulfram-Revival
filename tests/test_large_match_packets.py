"""Decode bounded updates independently, including worlds beyond the 8-bit count."""
import unittest
import random
from types import SimpleNamespace
from unittest.mock import Mock
from test_scout_wire import RetailBits
from wulfram_server.core.entity import GameEntity, UpdateMask
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.network.streams import PacketWriter
from wulfram_server import application as app


class LargeMatchPackets(unittest.TestCase):
    def test_shared_updates_preserve_team_secrecy_and_exclude_each_owner(self):
        manager = EntityManager()
        players = [GameEntity(net_id=i, unit_type=1, team_id=1 if i < 3 else 2,
                              weapon_table_id=1) for i in range(1, 4)]
        cargo = GameEntity(net_id=10, unit_type=19, team_id=1, cargo_item_id=7)
        for entity in [*players, cargo]:
            entity.pending_mask = UpdateMask.DEFINITION
            manager.register_entity(entity)
        sessions = [SimpleNamespace(entity=entity, team=entity.team_id, is_logged_in=True,
                                   is_ready_for_updates=True, udp_context=SimpleNamespace(send=Mock()))
                    for entity in players]
        server = SimpleNamespace(entities=manager, sessions=sessions, _last_hard_sync_log=0)
        app._broadcast_dirty_state(server, send_view_updates=False)
        wires = [[call.args[0] for call in session.udp_context.send.call_args_list] for session in sessions]
        self.assertEqual(wires[0][0], wires[1][0])
        self.assertNotEqual(wires[0][0], wires[2][0])
        for index, packets in enumerate(wires):
            received, cargo_items = [], []
            for packet in packets:
                self.assertEqual(packet[0], 0x0E)
                bits = RetailBits(packet[1:]); bits.take(32)
                if bits.take(1):
                    self.assertEqual(bits.take(5), 1)
                    bits.take(10); bits.take(10)
                for _ in range(bits.take(8)):
                    received.append(bits.take(32))
                    bits.take(1)
                    self.assertEqual(bits.take(10), UpdateMask.DEFINITION)
                    bits.take(16)
                    unit_type = bits.take(8); bits.take(8); bits.take(8)
                    if unit_type == 19:
                        cargo_items.append(bits.take(8))
                    bits.take(1)
                bits.finish()
            self.assertEqual(set(received), {1, 2, 3, 10} - {index+1})
            self.assertEqual(cargo_items, [7 if index < 2 else 13])

    def test_packing_matches_independent_bits_across_signed_and_unaligned_fields(self):
        rng = random.Random(64)
        writer = PacketWriter()
        expected = ""
        for _ in range(2000):
            width = rng.choice((0, 1, 2, 5, 7, 8, 10, 16, 24, 32, 64))
            value = rng.randrange(-(1 << 65), 1 << 65)
            writer.write_bits(value, width)
            if width:
                expected += f"{value & ((1 << width) - 1):0{width}b}"
            if rng.randrange(8) == 0:
                writer.align()
                expected += "0" * (-len(expected) % 8)
        expected += "0" * (-len(expected) % 8)
        self.assertEqual(writer.get_bytes(), bytes(int(expected[i:i+8], 2) for i in range(0, len(expected), 8)))

    def test_every_entity_arrives_once_without_fragmentation_or_count_wrap(self):
        manager = EntityManager()
        entities = [GameEntity(net_id=i, unit_type=1, team_id=1+i % 2) for i in range(1, 301)]
        for entity in entities:
            entity.pending_mask = UpdateMask.DEFINITION
        received = []
        chunks = list(manager.build_update_packets(entities, sequence_num=1234, is_view_update=False))
        self.assertGreater(len(chunks), 1)
        for packet in chunks:
            self.assertLessEqual(len(packet) + 1, 1200)
            bits = RetailBits(packet)
            self.assertEqual(bits.take(32), 1234)
            self.assertEqual(bits.take(1), 0)
            count = bits.take(8)
            self.assertGreater(count, 0)
            for _ in range(count):
                entity_id = bits.take(32)
                received.append(entity_id)
                self.assertEqual(bits.take(1), 1)
                self.assertEqual(bits.take(10), UpdateMask.DEFINITION)
                self.assertEqual(bits.take(16), 0)
                self.assertEqual([bits.take(8) for _ in range(3)], [1, 1+entity_id % 2, 1+entity_id % 2])
                self.assertEqual(bits.take(1), 1)
            bits.finish()
        self.assertEqual(received, list(range(1, 301)))
        with self.assertRaisesRegex(ValueError, "at most 255"):
            manager.build_update_packet(entities, sequence_num=1234, is_view_update=False)


if __name__ == "__main__":
    unittest.main()
