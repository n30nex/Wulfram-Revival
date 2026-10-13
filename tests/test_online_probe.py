"""Independent retail wire fixtures for the deployment/lifecycle probe."""
from pathlib import Path
import runpy
import unittest

PROBE = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/check-online.py'))
TANK = bytes.fromhex('180000007b821e9eac48000000000810182010000000000000000000000000000000000000000000000000')
SCOUT = bytes.fromhex('180000007b8401007ff000000010000002a010000000000000000000000000000000000000000000000000')


class OnlineProbeTests(unittest.TestCase):
    def test_vehicle_specific_weapon_tail_preserves_identity_and_vitals(self):
        tank = PROBE['spawn_state'](TANK)
        self.assertEqual((tank['entity'], tank['team'], tank['vehicle']), (0x01020304, 2, 0))
        self.assertAlmostEqual(tank['health'], .47, delta=.001)
        self.assertAlmostEqual(tank['fuel'], .38, delta=.001)
        self.assertEqual(PROBE['spawn_state'](SCOUT),
                         {'entity': 42, 'team': 1, 'vehicle': 1, 'health': 1.0, 'fuel': 1.0})

    def test_incomplete_or_wrong_packets_cannot_count_as_spawn_evidence(self):
        missing_vitals = bytearray(TANK)
        missing_vitals[5] &= 0x7f
        wrong_table = bytearray(TANK)
        wrong_table[5] |= 0x7c
        for packet in (b'', b'\x0e'+TANK[1:], TANK[:14], SCOUT[:14], missing_vitals, wrong_table):
            with self.subTest(packet=bytes(packet).hex()), self.assertRaises(ValueError):
                PROBE['spawn_state'](packet)


if __name__ == '__main__':
    unittest.main()
