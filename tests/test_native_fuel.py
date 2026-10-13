"""Vehicle-relative fuel survives native snapshots, weapons and docking."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_bots import make_server
from wulfram_server.core.config import Config
from wulfram_server.core.entity import GameEntity
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.core.native_physics import PhysicsWorldHost, NativePhysicsUnavailable, TrackedPhysicsEntity


class NativeFuelTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.native = Mock()
        self.native.api_version.return_value = 14
        self.native.write_snapshot.return_value = {'physics_version':'test','terrain_identity':'flat',
                                                   'configuration_identity':'test'}
        self.native.vehicle_fuel_capacity.side_effect = lambda world,kind: {0:33000.,1:13000.}[kind]
        self.native.consume_fuel.return_value = self.native.add_fuel.return_value = True
        with patch('wulfram_server.core.native_physics._load_native_module',return_value=self.native):
            self.host = PhysicsWorldHost(EntityManager(),Config().physics,collision_root=Path(self.folder.name))
        self.land = SimpleNamespace(loaded=True,identity='flat',revision=1,width=2,height=2,
                                    cell_size_x=10.,cell_size_y=10.,heights=[[0.,0.],[0.,0.]])
        self.host._ensure_world(self.land)

    def snapshot(self, entity, fuel):
        self.host._apply_native_entity(entity,TrackedPhysicsEntity(role='tank',fingerprint=(),entity=entity),
            {'position':entity.pos,'linear_velocity':entity.vel,'euler_radians':entity.rot,
             'angular_velocity':entity.spin,'fuel':fuel,'last_processed_input':0},1)

    def test_snapshot_and_body_recreation_share_each_vehicle_capacity(self):
        for kind,capacity in ((0,33000.),(1,13000.)):
            with self.subTest(kind=kind):
                entity = GameEntity(net_id=kind+1,unit_type=kind,is_manned=True)
                self.snapshot(entity,capacity)
                self.assertEqual(entity.energy,1.)
                self.snapshot(entity,capacity/2)
                self.assertEqual(entity.energy,.5)
                with patch.object(self.host,'_collision_asset',return_value=('shape',b'test-shape')):
                    self.host._create_entity('tank',entity)
                self.assertEqual(self.native.create_vehicle.call_args.kwargs['fuel'],capacity/2)

    def test_weapon_cost_and_refuel_convert_absolute_units_consistently(self):
        for kind,capacity in ((0,33000.),(1,13000.)):
            with self.subTest(kind=kind):
                entity = GameEntity(net_id=kind+1,unit_type=kind,energy=.5,is_manned=True)
                self.native.consume_fuel.reset_mock()
                self.assertFalse(self.host.spend_fuel(entity,capacity*.51))
                self.native.consume_fuel.assert_not_called()
                self.assertEqual(entity.energy,.5)
                self.assertTrue(self.host.spend_fuel(entity,capacity*.2))
                self.assertAlmostEqual(entity.energy,.3)
                self.assertEqual(self.native.consume_fuel.call_args.kwargs['amount'],capacity*.2)
                self.assertTrue(self.host.refuel(entity,capacity*.6))
                self.assertAlmostEqual(entity.energy,.9)
                self.assertTrue(self.host.refuel(entity,capacity))
                self.assertEqual(entity.energy,1.)
                self.native.add_fuel.reset_mock()
                self.assertFalse(self.host.refuel(entity,capacity))
                self.native.add_fuel.assert_not_called()

    def test_docked_scout_regenerates_and_wakes_without_fuel_creation_or_loss(self):
        entity = self.host.entities.create_entity(1,1,(0.,0.,0.))
        entity.is_manned = entity.is_docked = True
        entity.energy = .5
        self.host._fuel_regeneration_per_second = 1000.
        self.host._resting_fuel_multiplier = 2.
        self.host.tick_milliseconds = 40
        self.host._regenerate_docked_fuel()
        self.assertAlmostEqual(entity.energy,.5+80/13000)
        self.native.consume_fuel.reset_mock()
        self.native.add_fuel.reset_mock()
        self.assertTrue(self.host.spend_fuel(entity,80))
        self.assertAlmostEqual(entity.energy,.5)
        self.assertTrue(self.host.refuel(entity,6500))
        self.assertEqual(entity.energy,1.)
        self.host._regenerate_docked_fuel()
        self.assertEqual(entity.energy,1.)
        self.native.consume_fuel.assert_not_called()
        self.native.add_fuel.assert_not_called()
        entity.is_docked = False
        with patch.object(self.host,'_collision_asset',return_value=('shape',b'test-shape')):
            self.host._create_entity('tank',entity)
        self.assertEqual(self.native.create_vehicle.call_args.kwargs['fuel'],13000.)
        self.snapshot(entity,13000.)
        self.assertEqual(entity.energy,1.)

    def test_full_native_scout_leaves_resupply(self):
        server = make_server()
        bot = server.bots.add(team=1,loadout='scout')
        bot.resupplying = True
        self.snapshot(bot.entity,13000.)
        server.bots._decide(bot,100)
        self.assertFalse(bot.resupplying)
        self.assertNotEqual(bot.order,'resupply')

    def test_capacity_comes_from_native_world_and_must_be_valid(self):
        self.native.vehicle_fuel_capacity.side_effect = lambda world,kind: {0:8000.,1:12000.}[kind]
        self.land.revision += 1
        self.host._ensure_world(self.land)
        entity = GameEntity(net_id=1,unit_type=1)
        self.snapshot(entity,6000.)
        self.assertEqual(entity.energy,.5)
        self.native.vehicle_fuel_capacity.side_effect = None
        for invalid in (0.,-1.,float('inf'),float('nan')):
            with self.subTest(capacity=invalid):
                self.land.revision += 1
                self.native.vehicle_fuel_capacity.return_value = invalid
                with self.assertRaises(NativePhysicsUnavailable):
                    self.host._ensure_world(self.land)

    def test_older_binding_is_rejected_before_starting_physics(self):
        self.native.api_version.return_value = 13
        with patch('wulfram_server.core.native_physics._load_native_module',return_value=self.native):
            with self.assertRaisesRegex(NativePhysicsUnavailable,'server expects 14'):
                PhysicsWorldHost(EntityManager(),Config().physics,collision_root=Path(self.folder.name))


if __name__ == '__main__':
    unittest.main()
