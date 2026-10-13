from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wulfram_server.network.packets.packet_logger import PacketLogger


class PacketRedactionTests(unittest.TestCase):
    def test_authentication_never_enters_text_or_hex_logs(self):
        secret = b"private-example-credential"
        logger = PacketLogger()
        for opcode in (0x13, 0x21):
            for old_api in (False, True):
                with self.subTest(opcode=opcode, old_api=old_api):
                    output = StringIO()
                    with redirect_stdout(output):
                        if old_api:
                            logger.log("test", opcode, secret)
                        else:
                            logger.log_packet("test", bytes([opcode]) + secret)
                    text = output.getvalue()
                    self.assertIn("authentication data redacted", text)
                    self.assertNotIn(secret.decode(), text)
                    self.assertNotIn(secret.hex(), text.lower())


if __name__ == "__main__":
    unittest.main()
