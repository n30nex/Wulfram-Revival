from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import sysconfig
import threading
import time
from types import ModuleType
from typing import TYPE_CHECKING

from wulfram_server.core.entity import GameEntity, InputSample, PendingTransientEvent, UpdateMask
from wulfram_server.network.packets.jet_layout_profiles import (
    JetLayoutProfile,
    get_jet_layout_profile,
)

if TYPE_CHECKING:
    from wulfram_server.core.config import PhysicsConfig
    from wulfram_server.core.entity_manager import EntityManager
    from wulfram_server.core.land import LandMap


PYTHON_BINDING_API_VERSION = 12
TANK_UNIT_TYPE = 0
SCOUT_UNIT_TYPE = 1
PLAYER_VEHICLE_UNIT_TYPES = frozenset((TANK_UNIT_TYPE, SCOUT_UNIT_TYPE))
PULSE_UNIT_TYPE = 6
TRACE_EVENT_CONTACT = 4
TRACE_EVENT_JUMP_ACCEPTED = 9
# ProcessTransientArrayPacket queues an event type, not a raw sound ID.
# FUN_00449490's switch case 0x10 invokes catalogue sound 0x46, whose name is
# TANK_JUMP. Keep that client presentation mapping out of the numerical core.
TANK_JUMP_TRANSIENT_TYPE = 0x10

# These families have ordinary-model `_s` collision assets in the recovered
# Wulfram II shape set. Unit types without a proved asset mapping stay outside
# authoritative collision instead of receiving a guessed shape.
STATIC_COLLISION_FAMILIES: dict[int, str] = {
    19: "cargo",
    25: "energy",
    26: "refuel",
    27: "repair",
    29: "flak_turret",
    30: "gun_turret",
}


class NativePhysicsUnavailable(RuntimeError):
    pass


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_native_module() -> ModuleType:
    try:
        import _wulfram_physics as native
        return native
    except ModuleNotFoundError as initial_error:
        extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
        if not extension_suffix:
            raise NativePhysicsUnavailable(
                "Python did not report a native extension suffix"
            ) from initial_error
        if sys.platform == "win32":
            build_root = _repository_root() / "build" / "physics-x64"
            build_command = "scripts\\build-physics.cmd"
        elif sys.platform.startswith("linux"):
            build_root = _repository_root() / "build" / "physics-linux-x64"
            build_command = "scripts/build-physics.sh"
        else:
            raise NativePhysicsUnavailable(
                f"WulframPhysicsPython is unsupported on {sys.platform}"
            ) from initial_error
        extension_name = f"_wulfram_physics{extension_suffix}"
        candidates = sorted(
            {
                candidate.resolve()
                for directory in (build_root / "RelWithDebInfo", build_root)
                for candidate in directory.glob(extension_name)
            }
        )
        if not candidates:
            raise NativePhysicsUnavailable(
                "WulframPhysicsPython is not built. Run "
                f"{build_command} from the repository root."
            ) from initial_error

        extension_path = candidates[-1]
        spec = importlib.util.spec_from_file_location("_wulfram_physics", extension_path)
        if spec is None or spec.loader is None:
            raise NativePhysicsUnavailable(
                f"could not load native physics extension: {extension_path}"
            ) from initial_error
        native = importlib.util.module_from_spec(spec)
        sys.modules["_wulfram_physics"] = native
        try:
            spec.loader.exec_module(native)
        except Exception:
            sys.modules.pop("_wulfram_physics", None)
            raise
        return native


@dataclass(slots=True)
class PhysicsMetrics:
    ticks: int = 0
    snapshots: int = 0
    created_entities: int = 0
    destroyed_entities: int = 0
    submitted_inputs: int = 0
    rejected_inputs: int = 0
    dropped_catch_up_ticks: int = 0
    contacts: int = 0
    corrections_accepted: int = 0
    corrections_rejected: int = 0
    jumps_accepted: int = 0


@dataclass(slots=True)
class TrackedPhysicsEntity:
    role: str
    fingerprint: tuple[object, ...]
    entity: GameEntity


class PhysicsWorldHost:
    """Owns one authoritative native world for the Wulfram server."""

    def __init__(
        self,
        entities: EntityManager,
        config: PhysicsConfig,
        packet_config=None,
        *,
        collision_root: Path | None = None,
        expected_physics_version: str | None = None,
    ):
        self._native = _load_native_module()
        observed_api = int(self._native.api_version())
        if observed_api != PYTHON_BINDING_API_VERSION:
            raise NativePhysicsUnavailable(
                "WulframPhysicsPython API mismatch: "
                f"server expects {PYTHON_BINDING_API_VERSION}, extension provides {observed_api}"
            )
        probe_world = self._native.create_world(
            count_x=2,
            count_y=2,
            spacing_x=1.0,
            spacing_y=1.0,
            heights_x_major=[0.0, 0.0, 0.0, 0.0],
            terrain_identity="release-probe",
            configuration={},
        )
        observed_physics_version = str(
            self._native.write_snapshot(probe_world)["physics_version"]
        )
        if (
            expected_physics_version is not None
            and observed_physics_version != expected_physics_version
        ):
            raise NativePhysicsUnavailable(
                "WulframPhysicsPython semantic version mismatch: "
                f"release expects {expected_physics_version}, "
                f"extension provides {observed_physics_version}"
            )

        if config.tick_milliseconds <= 0:
            raise ValueError("physics.tick_milliseconds must be positive")
        if config.network_hz <= 0.0:
            raise ValueError("physics.network_hz must be positive")
        if config.view_update_hz <= 0.0:
            raise ValueError("physics.view_update_hz must be positive")
        if config.max_catch_up_steps <= 0:
            raise ValueError("physics.max_catch_up_steps must be positive")
        if config.fuel_regeneration_per_second < 0.0:
            raise ValueError("physics.fuel_regeneration_per_second cannot be negative")
        if config.resting_fuel_multiplier < 0.0:
            raise ValueError("physics.resting_fuel_multiplier cannot be negative")

        self.entities = entities
        if collision_root is None:
            raise NativePhysicsUnavailable("the server requires an explicit collision asset directory")
        self._collision_root = collision_root.resolve()
        if not self._collision_root.is_dir():
            raise NativePhysicsUnavailable(
                f"collision asset directory is unavailable: {self._collision_root}"
            )
        self.tick_milliseconds = int(config.tick_milliseconds)
        self.network_hz = float(config.network_hz)
        self.max_catch_up_steps = int(config.max_catch_up_steps)
        self.metrics_interval_seconds = float(config.metrics_interval_seconds)
        self.metrics = PhysicsMetrics()
        self._jet_layout_profile: JetLayoutProfile | None = (
            get_jet_layout_profile(packet_config.jet_layout_profile)
            if packet_config is not None
            else None
        )
        self._core_configuration = self._build_core_configuration(packet_config, config)
        self._maximum_fuel = float(
            self._core_configuration["maximum_fuel"]
            if self._core_configuration is not None
            else 33000.0
        )
        self._starting_jet_strength = float(
            packet_config.behavior.vehicle_physics.starting_jet_strength
            if packet_config is not None
            else 0.0
        )
        self._fuel_regeneration_per_second = float(
            config.fuel_regeneration_per_second
        )
        self._resting_fuel_multiplier = float(config.resting_fuel_multiplier)

        self._lock = threading.RLock()
        self._world = None
        self._terrain_revision = -1
        self._next_tick = 1
        self._world_time_milliseconds = 0
        self._tracked_entities: dict[int, TrackedPhysicsEntity] = {}
        self._last_submitted_input: dict[int, int] = {}
        self._submitted_client_markers: dict[int, dict[int, tuple[int, int]]] = {}
        self._projectile_contacts: dict[int, dict[str, object]] = {}
        self._tank_contacts: list[dict[str, object]] = []
        self._collision_assets: dict[str, bytes] = {}
        self._metadata: dict[str, object] = {}
        self._last_metrics_log = time.monotonic()

    @staticmethod
    def _build_core_configuration(
        packet_config,
        physics_config: PhysicsConfig,
    ) -> dict[str, float | str] | None:
        if packet_config is None:
            return None
        vehicle = packet_config.behavior.vehicle_physics
        active = packet_config.behavior.active_vehicle_physics
        layout = get_jet_layout_profile(packet_config.jet_layout_profile)
        values: dict[str, float | str] = {
            "turn_adjust": float(active.turn_adjust),
            "move_adjust": float(active.move_adjust),
            "strafe_adjust": float(active.strafe_adjust),
            "maximum_velocity": float(active.max_velocity),
            "low_fuel_level": float(active.low_fuel_level),
            "maximum_altitude": float(active.max_altitude),
            "gravity_percent": float(active.gravity_pct),
            "gravity_magnitude": float(packet_config.behavior.header.gravity_force),
            "minimum_jet_strength": float(vehicle.minimum_jet_strength),
            "jet_response_coefficient": float(vehicle.jet_response_coefficient),
            "maximum_fuel": float(vehicle.mass),
            # These are provisional Wulfram 1.0 server_params values, exposed
            # as server policy until matching Wulfram II values are recovered.
            "jump_velocity": float(physics_config.jump_velocity),
            "jump_acceleration": float(physics_config.jump_acceleration),
            "jump_fuel_cost": float(physics_config.jump_fuel_cost),
            "fuel_regeneration_per_second": float(
                physics_config.fuel_regeneration_per_second
            ),
            "density": 6700.0,
            "baseline_friction": 0.4,
            "baseline_linear_drag": 0.2,
            "angular_drag": 2.0,
            "jet_layout_profile": layout.name,
            "jet_layout_identity": layout.identity,
        }
        serialized = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("ascii")
        values["configuration_identity"] = (
            "python-server-tank:" + hashlib.sha256(serialized).hexdigest()[:16]
        )
        return values

    @property
    def metadata(self) -> dict[str, object]:
        return dict(self._metadata)

    def trace_segment(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        *,
        ignored_entity: int = 0,
        second_ignored_entity: int = 0,
    ) -> dict[str, object]:
        """Trace through the same terrain and collision bodies used by authority."""
        with self._lock:
            if self._world is None:
                return {
                    "hit": False,
                    "entity_id": 0,
                    "point": tuple(end),
                    "normal": (0.0, 0.0, 1.0),
                    "fraction": 1.0,
                }
            return self._native.trace_segment(
                world=self._world,
                start=start,
                end=end,
                ignored_entity=ignored_entity,
                second_ignored_entity=second_ignored_entity,
            )

    def apply_linear_impulse(
        self,
        entity_id: int,
        impulse: tuple[float, float, float],
    ) -> bool:
        with self._lock:
            if self._world is None:
                return False
            return bool(self._native.apply_linear_impulse(
                world=self._world,
                entity_id=entity_id,
                impulse=impulse,
            ))

    def _load_collision_asset(self, identity: str) -> bytes:
        if identity not in self._collision_assets:
            path = self._collision_root / identity
            try:
                self._collision_assets[identity] = path.read_bytes()
            except OSError as error:
                raise NativePhysicsUnavailable(
                    f"required collision asset is unavailable: {path}"
                ) from error
        return self._collision_assets[identity]

    def _collision_asset(self, entity: GameEntity) -> tuple[str, bytes]:
        family = "scout" if entity.unit_type == SCOUT_UNIT_TYPE else "tank"
        identity = f"{family}_{2 if entity.team_id == 2 else 1}_s"
        return identity, self._load_collision_asset(identity)

    def _static_collision_asset(self, entity: GameEntity) -> tuple[str, bytes]:
        family = STATIC_COLLISION_FAMILIES[entity.unit_type]
        identity = "cargo_s" if family == "cargo" else f"{family}_{2 if entity.team_id == 2 else 1}_s"
        return identity, self._load_collision_asset(identity)

    def _ensure_world(self, land: LandMap) -> bool:
        if not land.loaded:
            return False
        if self._world is not None and self._terrain_revision == land.revision:
            return True

        # TerrainGrid uses x-major indexing. LandMap intentionally stores rows
        # as [y][x], so transpose exactly once at this adapter boundary.
        heights_x_major = [
            land.heights[y][x]
            for x in range(land.width)
            for y in range(land.height)
        ]
        self._world = self._native.create_world(
            count_x=land.width,
            count_y=land.height,
            spacing_x=land.cell_size_x,
            spacing_y=land.cell_size_y,
            heights_x_major=heights_x_major,
            terrain_identity=land.identity,
            configuration=self._core_configuration,
        )
        self._terrain_revision = land.revision
        self._next_tick = 1
        self._world_time_milliseconds = 0
        self._tracked_entities.clear()
        self._last_submitted_input.clear()
        self._submitted_client_markers.clear()
        self._projectile_contacts.clear()
        self._tank_contacts.clear()
        self._metadata = self._native.write_snapshot(self._world)
        print(
            "[physics] authority=portable-core "
            f"binding_api={PYTHON_BINDING_API_VERSION} "
            f"version={self._metadata['physics_version']} "
            f"configuration={self._metadata['configuration_identity']} "
            f"terrain={self._metadata['terrain_identity']} "
            "collision_assets=tank_1_s,tank_2_s,scout_1_s,scout_2_s "
            f"tick_ms={self.tick_milliseconds} network_hz={self.network_hz:g}"
        )
        return True

    @staticmethod
    def _physics_role(entity: GameEntity) -> str | None:
        if (
            entity.unit_type in PLAYER_VEHICLE_UNIT_TYPES
            and entity.is_manned
            and not entity.is_docked
        ):
            return "tank"
        if entity.unit_type == PULSE_UNIT_TYPE:
            return "projectile"
        if entity.unit_type in STATIC_COLLISION_FAMILIES:
            return "static"
        return None

    def _fingerprint(self, role: str, entity: GameEntity) -> tuple[object, ...]:
        if role == "tank":
            collision_identity, _ = self._collision_asset(entity)
            return (role, collision_identity, entity.unit_type, entity.team_id, id(entity))
        if role == "projectile":
            return (role, "pulse_shell_s", id(entity))
        collision_identity, _ = self._static_collision_asset(entity)
        if entity.unit_type in (29, 30):
            # Turret aiming and flak recoil are presentation/gameplay pose.
            # Their authoritative collision stays at the map-authored base
            # pose instead of being torn down and recreated every combat tick.
            return (
                role,
                collision_identity,
                entity.unit_type,
                entity.team_id,
                id(entity),
            )
        return (
            role,
            collision_identity,
            entity.unit_type,
            entity.team_id,
            tuple(entity.pos),
            tuple(entity.rot),
            id(entity),
        )

    def _create_entity(self, role: str, entity: GameEntity) -> None:
        if role == "projectile":
            collision_identity = "pulse_shell_s"
            self._native.create_projectile(
                world=self._world,
                entity_id=entity.net_id,
                position=entity.pos,
                linear_velocity=entity.vel,
                euler_radians=entity.rot,
                collision_asset=self._load_collision_asset(collision_identity),
                collision_identity=collision_identity,
                density=10000.0,
                friction=0.1,
                linear_drag=0.00001,
                angular_drag=0.0,
            )
            self._tracked_entities[entity.net_id] = TrackedPhysicsEntity(
                role=role,
                fingerprint=self._fingerprint(role, entity),
                entity=entity,
            )
            self.metrics.created_entities += 1
            return
        if role == "static":
            collision_identity, collision_asset = self._static_collision_asset(entity)
            self._native.create_static_collider(
                world=self._world,
                entity_id=entity.net_id,
                position=entity.pos,
                euler_radians=entity.rot,
                collision_asset=collision_asset,
                collision_identity=collision_identity,
                friction=1.0,
            )
            self._tracked_entities[entity.net_id] = TrackedPhysicsEntity(
                role=role,
                fingerprint=self._fingerprint(role, entity),
                entity=entity,
            )
            self.metrics.created_entities += 1
            return

        collision_identity, collision_asset = self._collision_asset(entity)
        vehicle_shape = None
        if self._jet_layout_profile is not None:
            if entity.unit_type == SCOUT_UNIT_TYPE:
                vehicle_shape = (
                    self._jet_layout_profile.scout_blue
                    if entity.team_id == 2
                    else self._jet_layout_profile.scout_red
                )
            else:
                vehicle_shape = (
                    self._jet_layout_profile.tank_blue
                    if entity.team_id == 2
                    else self._jet_layout_profile.tank_red
                )
        self._native.create_vehicle(
            world=self._world,
            entity_id=entity.net_id,
            team=entity.team_id,
            position=entity.pos,
            linear_velocity=entity.vel,
            euler_radians=entity.rot,
            angular_velocity=entity.spin,
            collision_asset=collision_asset,
            collision_identity=collision_identity,
            fuel=self._maximum_fuel * max(0.0, min(1.0, float(entity.energy))),
            jet_strength=self._starting_jet_strength,
            current_input=(
                0.0,
                0.0,
                0.0,
                self._starting_jet_strength,
                0.0,
                0.0,
                0.0,
            ),
            jet_shape=(vehicle_shape.points if vehicle_shape is not None else None),
            vehicle_type=entity.unit_type,
        )
        self._tracked_entities[entity.net_id] = TrackedPhysicsEntity(
            role=role,
            fingerprint=self._fingerprint(role, entity),
            entity=entity,
        )
        self._last_submitted_input[entity.net_id] = 0
        self._submitted_client_markers[entity.net_id] = {}
        self.metrics.created_entities += 1

        # A terrain rebuild reconstructs from the latest server state after old
        # queued samples may already have been consumed. Re-seed that state with
        # its existing server-owned sequence when necessary.
        if entity.input_sequence > 0 and not entity.pending_inputs:
            self._submit_input(entity, entity.current_input_sample())

    def _destroy_entity(self, entity_id: int) -> None:
        self._native.destroy_entity(self._world, entity_id)
        self._tracked_entities.pop(entity_id, None)
        self._last_submitted_input.pop(entity_id, None)
        self._submitted_client_markers.pop(entity_id, None)
        self._projectile_contacts.pop(entity_id, None)
        self._tank_contacts = [
            event
            for event in self._tank_contacts
            if int(event.get("entity_id", 0) or 0) != entity_id
            and int(event.get("other_entity_id", 0) or 0) != entity_id
        ]
        self.metrics.destroyed_entities += 1

    def _reconcile_entities(self) -> dict[int, GameEntity]:
        current = {entity.net_id: entity for entity in self.entities.get_all()}
        desired: dict[int, tuple[str, GameEntity]] = {}
        for entity_id, entity in current.items():
            role = self._physics_role(entity)
            if role is not None:
                desired[entity_id] = (role, entity)

        for entity_id, tracked in list(self._tracked_entities.items()):
            desired_entry = desired.get(entity_id)
            if desired_entry is None:
                self._destroy_entity(entity_id)
                continue
            role, entity = desired_entry
            if (
                entity is not tracked.entity
                or role != tracked.role
                or self._fingerprint(role, entity) != tracked.fingerprint
            ):
                self._destroy_entity(entity_id)

        for entity_id, (role, entity) in desired.items():
            if entity_id not in self._tracked_entities:
                self._create_entity(role, entity)
        return {
            entity_id: entity
            for entity_id, (role, entity) in desired.items()
            if role == "tank"
        }

    def finalize_spawn_pose(self, entity: GameEntity, land: LandMap) -> bool:
        """Create one new player vehicle and publish its terrain-safe native pose.

        The lock prevents the game loop from advancing the body between its
        creation and the spawn packet reading the resulting pose.
        """
        with self._lock:
            entity.is_manned = True
            if self._physics_role(entity) != "tank" or not self._ensure_world(land):
                self.entities.register_entity(entity)
                return False
            # Reconcile existing bodies while the staged spawn remains absent
            # from EntityManager, then add the new vehicle directly. This keeps
            # both physics and network publication from observing a partial
            # pose.
            self._reconcile_entities()
            self._create_entity("tank", entity)
            self._native.resolve_initial_spawn_pose(self._world, entity.net_id)
            snapshot = self._native.write_snapshot(self._world)
            self._metadata = snapshot
            native_entity = next(
                item
                for item in snapshot["entities"]
                if int(item["id"]) == entity.net_id
            )
            self._apply_native_entity(
                entity,
                self._tracked_entities[entity.net_id],
                native_entity,
                int(snapshot["tick"]),
            )
            self.entities.register_entity(entity)
            self.metrics.snapshots += 1
            return True

    def _submit_input(self, entity: GameEntity, sample: InputSample) -> None:
        if sample.sequence <= self._last_submitted_input.get(entity.net_id, 0):
            return
        controls = sample.controls
        try:
            self._native.submit_input(
                world=self._world,
                entity_id=entity.net_id,
                sequence=sample.sequence,
                target_tick=self._next_tick,
                time_milliseconds=self._world_time_milliseconds,
                turn=controls.turn,
                move=controls.move,
                strafe=controls.strafe,
                jet=controls.jet,
                tilt=controls.tilt,
                roll=controls.roll,
                jump=controls.jump,
            )
        except ValueError:
            self.metrics.rejected_inputs += 1
            raise
        self._last_submitted_input[entity.net_id] = sample.sequence
        self._submitted_client_markers.setdefault(entity.net_id, {})[sample.sequence] = (
            int(sample.client_time_or_sequence),
            int(self._next_tick),
        )
        self.metrics.submitted_inputs += 1

    def _submit_pending_inputs(self, desired: dict[int, GameEntity]) -> None:
        for entity_id in sorted(desired):
            entity = desired[entity_id]
            while entity.pending_inputs:
                sample = entity.pending_inputs[0]
                self._submit_input(entity, sample)
                entity.pending_inputs.popleft()

    def _regenerate_docked_fuel(self) -> None:
        """Advance fuel for player vehicles intentionally removed from the native world."""
        if self._maximum_fuel <= 0.0:
            return
        fuel_units = (
            self._fuel_regeneration_per_second
            * self._resting_fuel_multiplier
            * self.tick_milliseconds
            / 1000.0
        )
        if fuel_units <= 0.0:
            return
        normalized_gain = fuel_units / self._maximum_fuel
        for entity in self.entities.get_all():
            if (
                entity.unit_type not in PLAYER_VEHICLE_UNIT_TYPES
                or not entity.is_manned
                or not entity.is_docked
            ):
                continue
            previous = max(0.0, min(1.0, float(entity.energy)))
            regenerated = min(1.0, previous + normalized_gain)
            if regenerated - previous > 1.0e-9:
                entity.energy = regenerated
                entity.mark_dirty(UpdateMask.ENERGY)

    @staticmethod
    def _changed(left: tuple[float, float, float], right: tuple[float, float, float]) -> bool:
        return any(abs(a - b) > 1.0e-6 for a, b in zip(left, right))

    def _apply_native_entity(
        self,
        entity: GameEntity,
        tracked: TrackedPhysicsEntity,
        native_entity: dict[str, object],
        physics_step_tick: int,
    ) -> None:
        mask = UpdateMask(0)
        position = tuple(native_entity["position"])
        velocity = tuple(native_entity["linear_velocity"])
        rotation = tuple(native_entity["euler_radians"])
        spin = tuple(native_entity["angular_velocity"])
        energy = (
            max(0.0, min(1.0, float(native_entity["fuel"]) / self._maximum_fuel))
            if self._maximum_fuel > 0.0
            else 0.0
        )
        entity.settling_contact_threshold = float(
            native_entity.get("settling_contact_threshold", 0.0) or 0.0
        )
        entity.physics_step_tick = physics_step_tick
        if self._changed(entity.pos, position):
            entity.pos = position
            mask |= UpdateMask.POS
        if self._changed(entity.vel, velocity):
            entity.vel = velocity
            mask |= UpdateMask.VEL
        if self._changed(entity.rot, rotation):
            entity.rot = rotation
            mask |= UpdateMask.ROT
        if self._changed(entity.spin, spin):
            entity.spin = spin
            mask |= UpdateMask.SPIN
        if abs(float(entity.energy) - energy) > 1.0e-6 and tracked.role == "tank":
            entity.energy = energy
            mask |= UpdateMask.ENERGY
        entity.last_processed_input = int(native_entity["last_processed_input"])
        submitted_markers = self._submitted_client_markers.get(entity.net_id, {})
        processed_sequences = [
            sequence
            for sequence in submitted_markers
            if sequence <= entity.last_processed_input
        ]
        if processed_sequences:
            newest = max(processed_sequences)
            marker, processed_tick = submitted_markers[newest]
            if marker > 0:
                entity.last_processed_client_marker = marker
                entity.last_processed_client_tick = processed_tick
            for sequence in processed_sequences:
                del submitted_markers[sequence]
        if mask:
            entity.mark_dirty(mask)

    def _apply_snapshot(self, snapshot: dict[str, object]) -> None:
        physics_step_tick = int(snapshot["tick"])
        for native_entity in snapshot["entities"]:
            entity_id = int(native_entity["id"])
            entity = self.entities.get_entity(entity_id)
            tracked = self._tracked_entities.get(entity_id)
            if entity is None or tracked is None or tracked.role not in ("tank", "projectile"):
                continue
            self._apply_native_entity(
                entity, tracked, native_entity, physics_step_tick)

    def _consume_trace(self) -> None:
        events = self._native.drain_trace_events(self._world)
        counts = Counter(int(event["type"]) for event in events)
        for event in events:
            if int(event["type"]) != TRACE_EVENT_CONTACT:
                if int(event["type"]) == TRACE_EVENT_JUMP_ACCEPTED:
                    entity_id = int(event["entity_id"])
                    entity = self.entities.get_entity(entity_id)
                    tracked = self._tracked_entities.get(entity_id)
                    if entity is not None and tracked is not None and tracked.role == "tank":
                        entity.pending_transient_events.append(PendingTransientEvent(
                            event_type=TANK_JUMP_TRANSIENT_TYPE,
                            position=tuple(event["point"]),
                            requires_owner_motion_update=True,
                        ))
                continue
            entity_id = int(event["entity_id"])
            entity = self.entities.get_entity(entity_id)
            tracked = self._tracked_entities.get(entity_id)
            if entity is not None and tracked is not None and tracked.role == "projectile":
                self._projectile_contacts.setdefault(entity_id, event)
                continue
            if entity is not None and tracked is not None and tracked.role == "tank":
                entity.physics_contact_tick = int(event["tick"])
                if int(event.get("other_entity_id", 0) or 0) != 0:
                    self._tank_contacts.append(event)
        self.metrics.contacts += counts[TRACE_EVENT_CONTACT]
        self.metrics.corrections_accepted += counts[5]
        self.metrics.corrections_rejected += counts[6]
        self.metrics.jumps_accepted += counts[TRACE_EVENT_JUMP_ACCEPTED]

    def take_projectile_contact(self, entity_id: int) -> dict[str, object] | None:
        with self._lock:
            return self._projectile_contacts.pop(entity_id, None)

    def take_tank_contacts(self) -> list[dict[str, object]]:
        """Drain dynamic/static contacts for authoritative gameplay systems."""
        with self._lock:
            contacts = self._tank_contacts
            self._tank_contacts = []
            return contacts

    def _log_metrics_if_due(self) -> None:
        if self.metrics_interval_seconds <= 0.0:
            return
        now = time.monotonic()
        if now - self._last_metrics_log < self.metrics_interval_seconds:
            return
        self._last_metrics_log = now
        pending_acknowledgements = sum(
            max(0, entity.input_sequence - entity.last_processed_input)
            for entity in self.entities.get_all()
            if (
                (tracked := self._tracked_entities.get(entity.net_id)) is not None
                and tracked.role == "tank"
            )
        )
        print(
            "[physics-metrics] "
            f"tick={self._next_tick - 1} entities={len(self._tracked_entities)} "
            f"inputs={self.metrics.submitted_inputs} pending_input_acks={pending_acknowledgements} "
            f"contacts={self.metrics.contacts} "
            f"corrections_accepted={self.metrics.corrections_accepted} "
            f"corrections_rejected={self.metrics.corrections_rejected} "
            f"jumps_accepted={self.metrics.jumps_accepted} "
            f"dropped_catch_up_ticks={self.metrics.dropped_catch_up_ticks}"
        )

    def log_final_metrics(self) -> None:
        pending_acknowledgements = sum(
            max(0, entity.input_sequence - entity.last_processed_input)
            for entity in self.entities.get_all()
            if (
                (tracked := self._tracked_entities.get(entity.net_id)) is not None
                and tracked.role == "tank"
            )
        )
        print(
            "WULFRAM_SERVER_FINAL_METRICS "
            f"ticks={self.metrics.ticks} snapshots={self.metrics.snapshots} "
            f"inputs={self.metrics.submitted_inputs} "
            f"pending_input_acks={pending_acknowledgements} "
            f"contacts={self.metrics.contacts} "
            f"destroyed={self.metrics.destroyed_entities} "
            f"dropped_catch_up_ticks={self.metrics.dropped_catch_up_ticks}"
        )

    def step(self, land: LandMap) -> bool:
        with self._lock:
            if not self._ensure_world(land):
                return False
            # Docked Tanks are deliberately absent from the portable world so
            # their sleep pose cannot be disturbed. Advance their legacy
            # resting-rate fuel here; active Tanks regenerate inside the core.
            self._regenerate_docked_fuel()
            desired = self._reconcile_entities()
            self._submit_pending_inputs(desired)
            self._native.step_world(self._world, self._next_tick, self.tick_milliseconds)
            self._next_tick += 1
            self._world_time_milliseconds += self.tick_milliseconds
            snapshot = self._native.write_snapshot(self._world)
            self._metadata = snapshot
            self._apply_snapshot(snapshot)
            self._consume_trace()
            self.metrics.ticks += 1
            self.metrics.snapshots += 1
            self._log_metrics_if_due()
            return True

    def note_dropped_catch_up_ticks(self, count: int) -> None:
        self.metrics.dropped_catch_up_ticks += max(0, int(count))
