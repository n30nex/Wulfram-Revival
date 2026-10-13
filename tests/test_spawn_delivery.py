"""Whole-TANK loss repairs deployment without restoring or recreating a vehicle."""
import struct
import unittest
from unittest.mock import Mock, patch

from test_bots import make_server
from test_scout_wire import RetailBits
from wulfram_server import application as app
from wulfram_server.network.streams import PacketDecodeError, PacketReader, PacketWriter


def action_packet(opcode):
    writer = PacketWriter()
    if opcode == 0x0A:
        writer.write_byte(1)
    writer.write_int32(123)
    writer.write_int32(0)
    channels = app.ACTION_DUMP_IDS if opcode == 0x09 else (8,)
    for channel in channels:
        if opcode == 0x0A:
            writer.write_bits(channel, app.get_config_by_index(15).precision_header_bits)
        if channel == 4 or channel >= 8:
            writer.write_bits(0, 1)
        else:
            config = app.get_config_by_index(10 if channel == 5 else 11)
            if config.max_total_bits > 0:
                writer.write_bits(0, config.precision_header_bits)
            writer.write_bits(0, config.precision_base_bits)
    return bytes((opcode,))+writer.get_bytes()


class SpawnDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server()
        self.server.physics = None
        self.server.trace = Mock()
        self.server.logger = Mock()
        self.server.udp_sessions = {}
        self.session = app.ClientSession(self.server, Mock(), ('127.0.0.1', 40000))
        self.session.player_id = 80
        self.session.team = 1
        self.session.is_logged_in = self.session.is_ready_for_updates = True
        self.server.sessions.append(self.session)
        self.transport = Mock()
        self.ctx = app.UdpContext(self.transport, ('127.0.0.1', 40001), self.server, self.session)
        self.session.udp_context = self.ctx

    def spawn(self):
        pad = next(entity for entity in self.server.entities.get_all()
                   if entity.unit_type == 27 and entity.team_id == 1)
        with patch.object(app.time, 'monotonic', return_value=100), patch.object(app, 'get_ticks', return_value=1000):
            app.on_reincarnate(self.ctx, PacketReader(struct.pack('>HHBiiii', 1, 22, 0, pad.net_id, 0, 0, 0)))
        return self.session.entity

    def tanks(self):
        return [call.args[0] for call in self.transport.send.call_args_list
                if call.args[0][:1] == b'\x18']

    def test_lost_first_tank_retries_fresh_pose_and_vitals_without_renewing_shield(self):
        delivered = []
        lost_first = False
        def drop_first(payload, _address):
            nonlocal lost_first
            if payload[:1] == b'\x18':
                self.assertIs(self.session.spawn_delivery.entity, self.session.entity)
                if not lost_first:
                    lost_first = True
                    return
                delivered.append(payload)
        self.transport.send.side_effect = drop_first
        entity = self.spawn()
        self.assertEqual(delivered, [])
        pending = self.session.spawn_delivery
        entity.set_health_points(47)
        entity.energy = .38
        entity.pos = (40., 50., 20.)
        entity.spawn_protection_remaining = 2
        app._update_spawn_deliveries(self.server, 100.499)
        self.assertEqual(len(self.tanks()), 1)
        with patch.object(app, 'get_ticks', return_value=1100):
            app._update_spawn_deliveries(self.server, 100.5)
        self.assertEqual(len(delivered), 1)
        bits = RetailBits(delivered[0][1:])
        self.assertEqual(bits.take(32), 1100)
        self.assertEqual(bits.take(1), 1)
        self.assertEqual(bits.take(5), entity.weapon_table_id)
        self.assertEqual(bits.take(10), int((1-.47)*1022)+1)
        self.assertEqual(bits.take(10), int((1-.38)*1022)+1)
        bits.take(3); bits.take(8)
        self.assertEqual(bits.take(32), entity.unit_type)
        self.assertEqual(bits.take(32), entity.net_id)
        self.assertEqual(bits.take(8), entity.team_id)
        self.assertEqual([bits.take(32) for _ in range(3)], [40<<16, 50<<16, 20<<16])
        self.assertEqual((entity.health_points, entity.energy, entity.spawn_protection_remaining), (47, .38, 2))
        self.assertIs(self.session.entity, entity)
        self.assertIs(self.session.spawn_delivery, pending)
        self.assertEqual(pending.deadline, 108)

    def test_valid_dump_and_update_stop_retries_but_snapshot_ack_and_resend_do_not(self):
        for opcode in (0x09, 0x0A):
            with self.subTest(opcode=opcode):
                self.setUp()
                self.spawn()
                pending = self.session.spawn_delivery
                app.dispatcher.dispatch_datagram(self.ctx, b'\x10\x00')
                app.dispatcher.dispatch_datagram(self.ctx, b'\x19\x00\x01')
                self.assertIs(self.session.spawn_delivery, pending)
                app.dispatcher.dispatch_datagram(self.ctx, action_packet(opcode))
                self.assertIsNone(self.session.spawn_delivery)
                self.assertGreater(self.session.physics_input_sequence, pending.input_sequence)
                sent = len(self.tanks())
                app._update_spawn_deliveries(self.server, 101)
                self.assertEqual(len(self.tanks()), sent)

    def test_malformed_action_table_or_padding_cannot_acknowledge_or_mutate_input(self):
        self.spawn()
        valid = action_packet(0x0A)
        truncated = bytes((0x0A, 2))+valid[2:]
        bad_padding = valid[:-1]+bytes((valid[-1] | 1,))
        pending = self.session.spawn_delivery
        sequence = self.session.physics_input_sequence
        actions = dict(self.session.entity.actions)
        for packet in (truncated, bad_padding):
            with self.subTest(packet=packet), self.assertRaises(PacketDecodeError):
                app.dispatcher.dispatch_datagram(self.ctx, packet)
            self.assertIs(self.session.spawn_delivery, pending)
            self.assertEqual(self.session.physics_input_sequence, sequence)
            self.assertEqual(self.session.entity.actions, actions)
        app.dispatcher.dispatch_datagram(self.ctx, b'\x0a\x00'+struct.pack('>ii', 123, 0))
        self.assertIs(self.session.spawn_delivery, pending)
        app._update_spawn_deliveries(self.server, 100.5)
        self.assertEqual(len(self.tanks()), 2)

    def test_lifecycle_invalidations_cancel_pending_delivery(self):
        for reason in ('death', 'unmanned', 'replacement', 'removed', 'disconnect', 'logout', 'team', 'map', 'not-ready'):
            with self.subTest(reason=reason):
                self.setUp()
                entity = self.spawn()
                if reason == 'death': entity.set_health_points(0)
                elif reason == 'unmanned': entity.is_manned = False
                elif reason == 'replacement': self.session.entity = self.server.entities.create_entity(0, 1, (100, 0, 15))
                elif reason == 'removed': self.server.entities.remove_entity(entity.net_id)
                elif reason == 'disconnect': self.session.disconnect()
                elif reason == 'logout': self.session.is_logged_in = False
                elif reason == 'team': self.session.team = 2; entity.team_id = 2
                elif reason == 'map': self.server.map_change_transition = object()
                elif reason == 'not-ready': self.session.is_ready_for_updates = False
                sent = len(self.tanks())
                app._update_spawn_deliveries(self.server, 100.5)
                self.assertIsNone(self.session.spawn_delivery)
                self.assertEqual(len(self.tanks()), sent)

    def test_retry_window_is_bounded_and_never_catches_up_in_a_burst(self):
        self.spawn()
        for index in range(1, 16):
            app._update_spawn_deliveries(self.server, 100+index*.5)
            app._update_spawn_deliveries(self.server, 100+index*.5)
        self.assertEqual(len(self.tanks()), 16)
        app._update_spawn_deliveries(self.server, 108)
        app._update_spawn_deliveries(self.server, 109)
        self.assertIsNone(self.session.spawn_delivery)
        self.assertEqual(len(self.tanks()), 16)

    def test_action_decoding_started_for_old_entity_cannot_acknowledge_replacement(self):
        self.spawn()
        old = self.session.entity
        read_value = app._read_action_value
        replacement_pending = []
        def replace_during_decode(reader, channel):
            self.session.entity = self.server.entities.create_entity(0, 1, (100, 0, 15))
            with patch.object(app.time, 'monotonic', return_value=101):
                app._send_spawn_tank(self.ctx)
            replacement_pending.append(self.session.spawn_delivery)
            return read_value(reader, channel)
        with patch.object(app, '_read_action_value', side_effect=replace_during_decode):
            app.dispatcher.dispatch_datagram(self.ctx, action_packet(0x0A))
        self.assertIsNot(self.session.entity, old)
        self.assertIs(self.session.spawn_delivery, replacement_pending[0])
        sent = len(self.tanks())
        app._update_spawn_deliveries(self.server, 101.5)
        self.assertEqual(len(self.tanks()), sent+1)


if __name__ == '__main__':
    unittest.main()
