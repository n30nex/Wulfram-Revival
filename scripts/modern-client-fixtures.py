"""Create public synthetic wire fixtures using the authoritative serializer."""
import contextlib
import io
import json
import sys
import hashlib
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from wulfram_server.core.entity import GameEntity
from wulfram_server.network.packets.update_array import UpdateArrayPacket
from wulfram_server.network.packets.tank import TankPacket
from wulfram_server.network.packets.packet_config import TankPacketConfig, BehaviorConfig
from wulfram_server.network.packets.behavior import BehaviorPacket
from wulfram_server.network.packets.translation import TranslationPacket
from wulfram_server.network.packets.player import UpdateStatsPacket, CommMessagePacket
from wulfram_server.network.packets.gameplay import (DeleteObjectPacket, TransientArrayPacket,
    PositionalTransient, EntityTransient, ExplosionTransient)
from wulfram_server.network.streams import PacketWriter
from wulfram_server.network.translation_config import get_config_by_index, PRECISE_ACTION_CONFIG


def control_fixture(precise=False):
    controls = PacketWriter()
    controls.write_byte(0x0a)
    controls.write_byte(11)
    controls.write_int32(1234)
    controls.write_int32(0)
    config = PRECISE_ACTION_CONFIG if precise else get_config_by_index(10)
    for key, value in ((1, -.5), (2, 1.0), (3, .25), (5, .8), (6, .001), (7, 0.0)):
        controls.write_bits(key, 16)
        _, raw, bits = config.compress(value)
        controls.write_bits(raw, bits)
    for key, value in ((8, True), (4, True), (12, True), (9, False), (13, True)):
        controls.write_bits(key, 16)
        controls.write_bool(value)
    return controls.get_bytes().hex()


def original_format_fixture():
    # Independent byte-level reference for the retail palette/mask operations.
    images = {}
    masks = {}
    decoded_masks = {}
    for name, seed in (('unknown001', 11), ('canyon001', 51), ('4sand001', 101)):
        pixels = bytearray()
        for level in range(8):
            for index in range((128 >> level)**2):
                v = (seed + 17*level + index % 13) % 256
                pixels.extend((v, 255-v, (v*3) % 256, 255))
        images[name] = bytes(pixels)
    for suffix in (1, 7):
        levels = [bytes(255 if (index+level+suffix) % 3 == 0 else 0
                        for index in range((128 >> level)**2)) for level in range(8)]
        # Original indexed files store smallest-to-largest; Godot packs largest first.
        masks[f'2template{suffix:03}'] = b'\x03\x07\x00' + b''.join(reversed(levels))
        decoded_masks[f'2template{suffix:03}'] = b''.join(levels)
    composed = bytearray(images['canyon001'])
    for name, mask_name in (('unknown001', '2template001'), ('4sand001', '2template007')):
        for index, mask in enumerate(decoded_masks[mask_name]):
            if mask:
                composed[index*4:index*4+4] = images[name][index*4:index*4+4]
    palette = bytes(channel for value in range(256) for channel in (value, 255-value, (value*3) % 256))
    runs = [(1, 0, 2), (0, 1, 3), (3, 2, 1)]
    strip = struct.pack('<IHHI', 3, 4, 3, 6) + bytes(range(1, 7))
    strip += b''.join(struct.pack('<HHH', *run) for run in runs)
    decoded = bytearray(4*3*4)
    source = 1
    for x, y, length in runs:
        for column in range(length):
            at = (y*4+x+column)*4
            decoded[at:at+4] = palette[source*3:source*3+3] + b'\xff'
            source += 1
    # One outward +Z face in the original counter-clockwise convention.
    model = b'fixture\0' + struct.pack('<H', 1) + b'quad0\0' + struct.pack('<H', 4)
    for vertex in ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)):
        model += struct.pack('<iii', *(value * 65536 for value in vertex))
    model += struct.pack('<HHH', 1, 0, 4)
    for index, uv in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        model += struct.pack('<Hii', index, *(value * 65536 for value in uv))
    model += struct.pack('<H', 0)
    return {'images': {k: v.hex() for k, v in images.items()},
            'masks': {k: v.hex() for k, v in masks.items()},
            'composed_sha256': hashlib.sha256(composed).hexdigest(),
            'palette': palette.hex(), 'strip': strip.hex(), 'model': model.hex(),
            'strip_sha256': hashlib.sha256(decoded).hexdigest()}


def fixtures():
    snapshot = UpdateArrayPacket(100, is_view_update=True)
    snapshot.set_local_stats(.75, .5, weapon_table_id=1)
    for index, unit in enumerate((0, 1, 27, 30, 19, 37)):
        entity = GameEntity(100 + index, unit, 1 + index % 2,
                            pos=(100.5 + index, -200.25, 8.75),
                            vel=(1, -2, 3), rot=(.1, -.2, .3), spin=(.4, -.5, .6),
                            health=.8, energy=.7,
                            weapon_table_id=1 if unit == 1 else 3 if unit == 30 else 0)
        snapshot.add_entity(entity, force_spawn=True, forced_mask=0x3ff)
    with contextlib.redirect_stdout(io.StringIO()):
        translation = TranslationPacket().serialize()
        precise_translation = TranslationPacket(precise_actions=True).serialize()
    older_remote = UpdateArrayPacket(99)
    older_remote.set_local_stats(.1, .1)
    older_remote.add_entity(GameEntity(100, 0, 1, pos=(900, 900, 900)), force_spawn=True, forced_mask=3)
    older_remote.add_entity(GameEntity(200, 0, 1, pos=(30, 40, 50)), force_spawn=True, forced_mask=3)
    return {
        'original_formats': original_format_fixture(),
        'snapshot': (b'\x0f' + snapshot.get_bytes()).hex(),
        'tank': TankPacket(42, 99, TankPacketConfig(), pos=(10.5, -20.25, 6.0),
                           rot=(0, 0, 1.5), health=.8, energy=.6).serialize().hex(),
        'delete': DeleteObjectPacket(42).serialize().hex(),
        'team': UpdateStatsPacket(7, 2).serialize().hex(),
        'message': CommMessagePacket(0, 0, 0, 0, 'Spawn shield ended.').serialize().hex(),
        'translation': translation.hex(),
        'precise_translation': precise_translation.hex(),
        'controls': control_fixture(),
        'precise_controls': control_fixture(True),
        'behavior': BehaviorPacket(BehaviorConfig()).serialize().hex(),
        'transients': TransientArrayPacket((EntityTransient(0x10, 42),
            PositionalTransient(0x0f, (100, -200, 10)), ExplosionTransient((150, 50, 5), 6))).serialize().hex(),
        'combat_events': TransientArrayPacket((PositionalTransient(0x100, (10, 20, 30), 7),
            PositionalTransient(0x111, (100, 200, 300), 7), PositionalTransient(0x121, (200, 50, 30), 42))).serialize().hex(),
        'visual_feedback': TransientArrayPacket((PositionalTransient(0x100, (486, 1010, 35), 1001),
            PositionalTransient(0x111, (470, 1035, 12), 1001), PositionalTransient(0x120, (505, 1050, 20), 1002))).serialize().hex(),
        'older_remote': (b'\x0e' + older_remote.get_bytes()).hex(),
        'delete_remote': DeleteObjectPacket(200).serialize().hex(),
    }


if __name__ == '__main__':
    target = Path(sys.argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fixtures(), indent=2) + '\n', encoding='utf-8')
