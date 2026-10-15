"""Precision is negotiated per authenticated session, never process-wide."""
import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from wulfram_server import application as app
from wulfram_server.network.streams import PacketReader, PacketWriter
from wulfram_server.network.packets.translation import TranslationPacket
from wulfram_server.network.translation_config import GLOBAL_CONFIGS, PRECISE_ACTION_CONFIG, PRECISE_ACTION_HELLO, COMBAT_EVENT_HELLO


class PreciseActionsTests(unittest.TestCase):
    def test_small_and_full_range_actions_round_trip_with_legacy_unchanged(self):
        with contextlib.redirect_stdout(io.StringIO()):
            before = TranslationPacket().serialize()
            precise = TranslationPacket(precise_actions=True).serialize()
            after = TranslationPacket().serialize()
        self.assertEqual(before, after)
        self.assertNotEqual(before, precise)
        self.assertEqual(GLOBAL_CONFIGS[11]['max'], '1000.0')
        for channel in (1, 2, 3, 5, 6, 7):
            for value in (-1, -.01, -.001, 0, .001, .01, 1):
                with self.subTest(channel=channel, value=value):
                    writer = PacketWriter()
                    _, encoded, width = PRECISE_ACTION_CONFIG.compress(value)
                    writer.write_bits(encoded, width)
                    actual = app._read_action_value(PacketReader(writer.get_bytes()), channel, True)
                    self.assertAlmostEqual(actual, value, delta=2 / 65534)

    def test_unauthenticated_and_unlinked_greetings_do_not_negotiate(self):
        for greeting in (PRECISE_ACTION_HELLO, COMBAT_EVENT_HELLO):
            writer = PacketWriter()
            writer.write_string(greeting)
            for session in (None, SimpleNamespace(is_logged_in=False, requested_precise_actions=False, requested_combat_events=False)):
                context = SimpleNamespace(session=session, server=SimpleNamespace(logger=Mock()))
                # The route is normally called with the opcode already consumed.
                reader = PacketReader(b'\x08' + writer.get_bytes())
                reader.read_byte()
                app.on_root_hello(context, reader)
                if session is not None:
                    self.assertFalse(session.requested_precise_actions)
                    self.assertFalse(session.requested_combat_events)


if __name__ == '__main__':
    unittest.main()
