# network/packet_config.py
from __future__ import annotations
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Type, TypeVar, Tuple, cast, get_type_hints
import os
import tomllib

from .jet_layout_profiles import (
    DEFAULT_JET_LAYOUT_PROFILE,
    get_jet_layout_profile,
)

# Create a generic type variable
T = TypeVar("T")

# ---------------------------------------------------------
#  HELPER: Recursive Unpacker
# ---------------------------------------------------------
def unpack(dataclass_type: Type[T], data: dict[str, Any], *, strict: bool = False) -> T:
    """
    Recursively unpacks a dictionary into a dataclass.
    """
    # 1. Defensive check: If it's not a dataclass, just return the raw data.
    # We cast to T because Pylance complains that 'dict' isn't 'T', 
    # but logically we shouldn't hit this if used correctly.
    if not is_dataclass(dataclass_type):
        return cast(T, data)

    #  Use get_type_hints to resolve string annotations into actual Classes
    # (e.g. converts the string "BehaviorConfig" -> class BehaviorConfig)
    resolved_types = get_type_hints(dataclass_type)
    
    # We still need the field names to filter out bad keys
    valid_field_names = {f.name for f in fields(dataclass_type)}
    
    clean_data = {}

    if strict:
        unknown_keys = sorted(set(data) - valid_field_names)
        if unknown_keys:
            raise ValueError(
                f"unknown {dataclass_type.__name__} keys: {', '.join(unknown_keys)}"
            )

    for key, value in data.items():
        if key not in valid_field_names:
            continue
        
        # Get the actual class
        target_type = resolved_types[key]

        # Case 1: Nested Dataclass
        if is_dataclass(target_type) and isinstance(value, dict):
            # Recursively unpack the nested section
            nested_class = cast(Type[Any], target_type)
            clean_data[key] = unpack(nested_class, value, strict=strict)
        
        # Case 2: Tuple conversion (TOML arrays are lists)
        elif isinstance(value, list) and (str(target_type).startswith("typing.Tuple") or target_type is tuple):
            clean_data[key] = tuple(value)
            
        # Case 3: Standard value
        else:
            clean_data[key] = value

    # 2. Return the instantiated class
    return dataclass_type(**clean_data)

# ---------------------------------------------------------
#  DATACLASSES
# ---------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TankStatsConfig:
    include_vitals: bool = True
    weapon_id: int = 0          
    health_mult_bits: int = 1   
    energy_mult_bits: int = 1   
    include_firing_mask: bool = False
    firing_mask_13bits: int = 0
    include_extras: bool = False
    extra_a_bits: int = 1       
    extra_b_bits: int = 1       

@dataclass(frozen=True, slots=True)
class TankPacketConfig:
    unit_type: int = 0
    team_id: int = 1
    default_pos: Tuple[float, float, float] = (100.0, 100.0, 100.0)
    default_rot: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    stats: TankStatsConfig = field(default_factory=TankStatsConfig)

@dataclass(slots=True)
class UnitDefaults:
    scale: float = 1.0
    regen_or_health_related: float = 100.0
    max_health: int = 100

@dataclass(slots=True)
class VehiclePhysics:
    speed: float = 20.0
    # SelectVehicleContactSound compares this with the magnitude of position
    # change before returning one of the scrape sound IDs. No time division is
    # visible there, so avoid claiming a stronger velocity unit in Python.
    scrape_sound_movement_threshold: float = 4.0
    engine_torque: int = 700
    suspension_stiffness: int = 550
    starting_jet_strength: float = 0.8
    minimum_jet_strength: float = 0.05
    jet_response_coefficient: float = 1.3
    unknown_int_30: int = 0
    mass: int = 33000

@dataclass(slots=True)
class ActiveVehiclePhysics:
    turn_adjust: float = 4.5
    move_adjust: float = 85.0 # move_forward_adjust
    move_backward_adjust: float = 38.0
    strafe_adjust: float = 69.7
    max_velocity: float = 80.0
    low_fuel_level: float = 2000.0
    # Current server/client calibration. The recovered compiled Tank fallback
    # is 3.25, but the Behavior packet intentionally overrides it.
    max_altitude: float = 4.25
    max_speed_height_pickup: float = 3.5
    gravity_pct: float = 0.5

@dataclass(slots=True)
class BehaviorHeader:
    spawn_related: int = 0
    timeout: float = 5.0
    dbl_6792F8: float = 10.0
    velocity_q: float = 10.0
    dbl_679308: float = 10.0
    dbl_679310: float = 10.0
    total_team_size: int = 20
    glimpse_ms: int = 25000
    push_ms: int = 35000
    gravity_force: float = 160.0 # Recovered Wulfram II compiled default
    dword_6791B8: int = 1
    dword_6791BC: int = 1
    # Recovered client use: minimum normalized pulse strength, despite the
    # older provisional field name.
    max_pulse_charge: float = 0.5
    unk10: Tuple[float, ...] = (1.0,) * 10
    # Client-side hostile candidate cutoff used even when a target command
    # does not explicitly request FRIENDLY or HOSTILE.
    enemy_targeting_distance_limit: float = 10000.0
    flag1: int = 1
    flag2: int = 1

@dataclass(slots=True)
class BehaviorConfig:
    header: BehaviorHeader = field(default_factory=BehaviorHeader)
    weapons_units_count: int = 4
    weapon_slots_count: int = 13
    unit_count: int = 39
    unit_defaults: UnitDefaults = field(default_factory=UnitDefaults)
    vehicle_physics_count: int = 2
    vehicle_physics: VehiclePhysics = field(default_factory=VehiclePhysics)
    active_vehicles_count: int = 3
    active_vehicle_physics: ActiveVehiclePhysics = field(default_factory=ActiveVehiclePhysics)


@dataclass(frozen=True, slots=True)
class CombatConfig:
    friendly_fire: bool = False
    construction_timeout_seconds: float = 5.0
    autocannon_damage: float = 10.0
    autocannon_fuel_cost: float = 80.0
    autocannon_refire_seconds: float = 0.08
    autocannon_range: float = 1000.0
    autocannon_autoaim_degrees: float = 20.0
    autocannon_base_scatter: float = 0.0
    autocannon_random_scatter: float = 1.0
    autocannon_scatter_factor: float = 0.02
    pulse_minimum_strength: float = 0.5
    pulse_regeneration_seconds: float = 10.0
    pulse_refire_seconds: float = 0.6
    pulse_launch_speed: float = 500.0
    pulse_fuel_cost: float = 3800.0
    pulse_direct_damage: float = 200.0
    pulse_splash_damage: float = 100.0
    pulse_minimum_radius: float = 10.0
    pulse_maximum_radius: float = 50.0
    pulse_force_radius: float = 45.0
    pulse_impulse: float = 150.0
    pulse_lifetime_seconds: float = 5.0
    pulse_gravity: float = 160.0
    gun_turret_range: float = 300.0
    gun_turret_damage: float = 10.0
    gun_turret_refire_seconds: float = 0.08
    gun_turret_autoaim_dot: float = 0.9
    gun_turret_base_ray_range: float = 150.0
    gun_turret_random_ray_range: float = 300.0
    gun_turret_scatter_factor: float = 0.08
    flak_turret_minimum_range: float = 300.0
    flak_turret_maximum_range: float = 1200.0
    flak_turret_muzzle_speed: float = 130.0
    flak_turret_refire_tank_seconds: float = 0.5
    flak_turret_refire_other_seconds: float = 0.75
    flak_turret_muzzle_offset: float = 8.5
    flak_turret_recoil_speed: float = 8.0
    flak_turret_recoil_spring: float = 40.0
    flak_turret_recoil_damping: float = 10.0
    flak_shell_direct_damage: float = 100.0
    flak_shell_splash_damage: float = 40.0
    flak_shell_minimum_radius: float = 10.0
    flak_shell_maximum_radius: float = 35.0
    flak_shell_force_radius: float = 40.5
    flak_shell_impulse: float = 90.0
    flak_shell_arm_seconds: float = 0.35
    flak_shell_max_fuse_seconds: float = 2.6
    flak_shell_miss_fuse_seconds: float = 0.06

@dataclass(frozen=True, slots=True)
class PacketConfig:
    jet_layout_profile: str = DEFAULT_JET_LAYOUT_PROFILE
    tank: TankPacketConfig = field(default_factory=TankPacketConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    combat: CombatConfig = field(default_factory=CombatConfig)

    @classmethod
    def load(
        cls,
        filename: str = "packets.toml",
        *,
        strict: bool = False,
    ) -> PacketConfig:
        if not os.path.exists(filename):
            if strict:
                raise FileNotFoundError(f"packet configuration is missing: {filename}")
            print(f"[WARN] {filename} not found. Using internal defaults.")
            return cls()

        with open(filename, "rb") as f:
            data = tomllib.load(f)

        if strict:
            missing_keys = sorted({"tank", "behavior", "combat"} - set(data))
            if missing_keys:
                raise ValueError(
                    "packet configuration is missing sections: "
                    + ", ".join(missing_keys)
                )
        config = unpack(cls, data, strict=strict)
        get_jet_layout_profile(config.jet_layout_profile)
        return config
