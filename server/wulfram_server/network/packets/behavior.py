# network/packets/behavior.py
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Sequence
from wulfram_server.network.packets.base import Packet
from wulfram_server.network.streams import PacketWriter
from .jet_layout_profiles import (
    DEFAULT_JET_LAYOUT_PROFILE,
    get_jet_layout_profile,
)
from .packet_config import BehaviorConfig, CombatConfig


def _write_jet_shape_block(
    pkt: PacketWriter,
    points: Sequence[tuple[float, ...]],
    trailing_scalar: float = 0.0,
) -> None:
    """
    Serializes one variable-length vehicle jet shape block.
    Wire size: 8 + 28 * point_count bytes.
    """
    pkt.write_int32(len(points))

    for pt in points:
        # Local Point Coordinates (Fixed 16.16)
        pkt.write_fixed1616(pt[0])
        pkt.write_fixed1616(pt[1])
        pkt.write_fixed1616(pt[2])

        # Local Thrust Direction Normal (Fixed 16.16, default: downward -Z)
        pkt.write_fixed1616(pt[3] if len(pt) > 3 else 0.0)
        pkt.write_fixed1616(pt[4] if len(pt) > 4 else 0.0)
        pkt.write_fixed1616(pt[5] if len(pt) > 5 else -1.0)

        # Legacy Flag (Int32)
        pkt.write_int32(int(pt[6]) if len(pt) > 6 else 0)

    # Trailing Scalar (Fixed 16.16)
    pkt.write_fixed1616(trailing_scalar)


@dataclass
class BehaviorPacket(Packet):
    """
    0x24 BEHAVIOR Packet: Overwrites process-wide gameplay, weapon, entity,
    vehicle physics, hover jet shapes, and concrete model tails on the client.
    """
    cfg: BehaviorConfig = field(repr=False)
    combat: CombatConfig = field(default_factory=CombatConfig, repr=False)
    jet_layout_profile: str = DEFAULT_JET_LAYOUT_PROFILE

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        cfg = self.cfg
        combat = self.combat
        layout = get_jet_layout_profile(self.jet_layout_profile)

        # ----------------------------------------------------------------------
        # SECTION 1: HEADER (95 bytes)
        # ----------------------------------------------------------------------
        h = cfg.header

        pkt.write_byte(int(h.spawn_related) & 0xFF)
        pkt.write_fixed1616(h.timeout)
        pkt.write_fixed1616(h.dbl_6792F8)
        pkt.write_fixed1616(h.velocity_q)
        pkt.write_fixed1616(h.dbl_679308)
        pkt.write_fixed1616(h.dbl_679310)

        pkt.write_int32(h.total_team_size)
        pkt.write_int32(h.glimpse_ms)
        pkt.write_int32(h.push_ms)

        pkt.write_fixed1616(h.gravity_force)
        pkt.write_int32(h.dword_6791B8)
        pkt.write_int32(h.dword_6791BC)
        pkt.write_fixed1616(combat.pulse_minimum_strength)

        if len(h.unk10) != 10:
            raise ValueError(f"BehaviorHeader.unk10 must be exactly 10 floats, got {len(h.unk10)}")

        for v in h.unk10:
            pkt.write_fixed1616(v)
        pkt.write_fixed1616(h.enemy_targeting_distance_limit)

        pkt.write_byte(int(h.flag1) & 0xFF)
        pkt.write_byte(int(h.flag2) & 0xFF)

        # ----------------------------------------------------------------------
        # SECTION 2: WEAPONS (4 tables * 13 slots * 45 bytes = 2340 bytes)
        # ----------------------------------------------------------------------
        for unit_index in range(cfg.weapons_units_count):
            for slot_index in range(cfg.weapon_slots_count):
                is_tank_autocannon = unit_index == 0 and slot_index == 0
                is_tank_pulse = unit_index == 0 and slot_index == 4
                is_gun_turret = unit_index == 3 and slot_index == 0
                enabled = is_tank_autocannon or is_tank_pulse or is_gun_turret
                # 5 applicability channel bool bytes
                pkt.write_byte(1 if enabled else 0)
                pkt.write_byte(0)
                pkt.write_byte(0)
                # Both enabled Tank weapons participate in the compact local
                # ready/firing-state mask.
                pkt.write_byte(1 if enabled else 0)
                pkt.write_byte(0)

                # Auto-aim forward-dot threshold
                pkt.write_fixed1616(
                    math.cos(math.radians(combat.autocannon_autoaim_degrees))
                    if is_tank_autocannon else
                    combat.gun_turret_autoaim_dot if is_gun_turret else
                    1.0
                )

                # 5 integer fields (cooldown, load, etc.)
                if is_tank_autocannon:
                    cooldown_ms = int(round(combat.autocannon_refire_seconds * 1000.0))
                    pkt.write_int32(cooldown_ms)
                    # The compiled Tank initializer sets both +0x20 and the
                    # still-unresolved +0x24 field to 80 for autocannon.
                    pkt.write_int32(cooldown_ms)
                elif is_tank_pulse:
                    pkt.write_int32(int(round(combat.pulse_refire_seconds * 1000.0)))
                    pkt.write_int32(0)
                elif is_gun_turret:
                    cooldown_ms = int(round(combat.gun_turret_refire_seconds * 1000.0))
                    pkt.write_int32(cooldown_ms)
                    # The compiled type-30 initializer writes the same 80 ms
                    # value to the still-unresolved adjacent integer field.
                    pkt.write_int32(cooldown_ms)
                else:
                    pkt.write_int32(0)
                    pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)

                # 4 fixed-point fields (base range, random range add, scatter factor, etc.)
                if is_tank_autocannon:
                    pkt.write_fixed1616(combat.autocannon_fuel_cost)
                    pkt.write_fixed1616(combat.autocannon_damage)
                    pkt.write_fixed1616(combat.autocannon_range)
                    pkt.write_fixed1616(combat.autocannon_refire_seconds)
                elif is_tank_pulse:
                    pkt.write_fixed1616(combat.pulse_fuel_cost)
                    pkt.write_fixed1616(combat.pulse_direct_damage)
                    pkt.write_fixed1616(combat.pulse_launch_speed)
                    pkt.write_fixed1616(combat.pulse_refire_seconds)
                elif is_gun_turret:
                    # Exact compiled type-30 defaults. The first fixed field
                    # remains unresolved and is zero in the initializer.
                    pkt.write_fixed1616(0.0)
                    pkt.write_fixed1616(combat.gun_turret_base_ray_range)
                    pkt.write_fixed1616(combat.gun_turret_random_ray_range)
                    pkt.write_fixed1616(combat.gun_turret_scatter_factor)
                else:
                    pkt.write_fixed1616(0.0)
                    pkt.write_fixed1616(0.0)
                    pkt.write_fixed1616(0.0)
                    pkt.write_fixed1616(0.0)

        # ----------------------------------------------------------------------
        # SECTION 3: ENTITY DEFINITIONS (39 records * 12 bytes = 468 bytes)
        # ----------------------------------------------------------------------
        ud = cfg.unit_defaults
        for _ in range(cfg.unit_count):
            pkt.write_fixed1616(ud.scale)
            pkt.write_fixed1616(ud.regen_or_health_related)
            pkt.write_int32(ud.max_health)

        # ----------------------------------------------------------------------
        # SECTION 4: GENERIC VEHICLE BEHAVIOR (2 records * 36 bytes = 72 bytes)
        # ----------------------------------------------------------------------
        # Wire order: Tank (type 0), Medic / Scout (type 1)
        vp = cfg.vehicle_physics
        for _ in range(cfg.vehicle_physics_count):
            pkt.write_fixed1616(vp.speed)                 # dBangMinVelocity
            pkt.write_fixed1616(vp.scrape_sound_movement_threshold)

            pkt.write_int32(vp.engine_torque)             # nBangInterval (ms)
            pkt.write_int32(vp.suspension_stiffness)      # nScrapeInterval (ms)

            pkt.write_fixed1616(vp.starting_jet_strength)
            pkt.write_fixed1616(vp.minimum_jet_strength)
            pkt.write_fixed1616(vp.jet_response_coefficient)

            pkt.write_int32(vp.unknown_int_30)            # nMaxWeaponWeight
            pkt.write_int32(vp.mass)                      # nMaxFuel

        # ----------------------------------------------------------------------
        # SECTION 5: TEAM-SPECIFIC VEHICLE JET SHAPES (4 blocks = 480 bytes)
        # ----------------------------------------------------------------------
        # Fixed wire order: Tank Red, Tank Blue, Medic/Scout Red, Medic/Scout Blue.
        # Neutral aliases Red client-side after reading.
        _write_jet_shape_block(
            pkt,
            layout.tank_red.points,
            layout.tank_red.trailing_scalar,
        )
        _write_jet_shape_block(
            pkt,
            layout.tank_blue.points,
            layout.tank_blue.trailing_scalar,
        )
        _write_jet_shape_block(
            pkt,
            layout.scout_red.points,
            layout.scout_red.trailing_scalar,
        )
        _write_jet_shape_block(
            pkt,
            layout.scout_blue.points,
            layout.scout_blue.trailing_scalar,
        )

        # ----------------------------------------------------------------------
        # SECTION 6: CONCRETE VEHICLE MODEL TAIL (108 bytes total)
        # ----------------------------------------------------------------------
        # Registry order: Tank (7 fields), Medic/Scout (9 fields), Bomber (11 fields)
        av = cfg.active_vehicle_physics

        for i in range(cfg.active_vehicles_count):
            if i == 0:
                # TANK (7 fixed-point values = 28 bytes)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust)
                pkt.write_fixed1616(av.strafe_adjust)
                pkt.write_fixed1616(av.max_velocity)
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(av.max_altitude)
                pkt.write_fixed1616(av.gravity_pct)

            elif i == 1:
                # SCOUT / MEDIC (9 fixed-point values = 36 bytes)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust)      # forward_move_adjust
                pkt.write_fixed1616(38.0)                # backward_move_adjust
                pkt.write_fixed1616(72.0)                # strafe_adjust
                pkt.write_fixed1616(85.0)                # max_velocity
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(4.9)                 # max_altitude
                pkt.write_fixed1616(3.5)                 # max_speed_height_pickup
                pkt.write_fixed1616(av.gravity_pct)

            elif i == 2:
                # BOMBER (11 fixed-point values = 44 bytes)
                pkt.write_fixed1616(-2.5132741233144)    # ax_mag
                pkt.write_fixed1616(2.35619449060725)    # ay_mag
                pkt.write_fixed1616(80.0)                # forward_mag
                pkt.write_fixed1616(45.0)                # low_airspeed
                pkt.write_fixed1616(0.5)                 # angfac
                pkt.write_fixed1616(70.0)                # turn_low
                pkt.write_fixed1616(110.0)               # turn_high
                pkt.write_fixed1616(340.0)               # turn_zero
                pkt.write_fixed1616(1000.0)              # very_high
                pkt.write_fixed1616(1800.0)              # ceiling
                pkt.write_fixed1616(av.low_fuel_level)

        # ----------------------------------------------------------------------
        # FINAL PAYLOAD ASSEMBLY: 0x24 + Body (3,564 bytes total)
        # ----------------------------------------------------------------------
        body = pkt.get_bytes()
        return b"\x24" + body
