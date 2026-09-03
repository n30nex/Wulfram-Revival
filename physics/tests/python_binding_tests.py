from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(extension_path: Path):
    spec = importlib.util.spec_from_file_location("_wulfram_physics", extension_path)
    require(spec is not None and spec.loader is not None, "could not construct extension module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) != 3:
        raise RuntimeError("usage: python_binding_tests.py <extension> <collision-root>")

    native = load_module(Path(sys.argv[1]).resolve())
    collision_root = Path(sys.argv[2]).resolve()
    shape_path = collision_root / "tank_1_s"
    scout_shape_path = collision_root / "scout_2_s"
    pulse_shape_path = collision_root / "pulse_shell_s"

    require(native.api_version() == native.API_VERSION == 12, "binding API version mismatch")
    world = native.create_world(
        count_x=4,
        count_y=4,
        spacing_x=10.0,
        spacing_y=10.0,
        heights_x_major=[0.0] * 16,
        terrain_identity="python-binding-level-v1",
        configuration={
            "configuration_identity": "python-binding-config-v1",
            "gravity_magnitude": 160.0,
            "turn_adjust": 4.5,
        },
    )
    native.create_tank(
        world=world,
        entity_id=7,
        team=1,
        position=(15.0, 15.0, 5.0),
        linear_velocity=(0.0, 0.0, 0.0),
        euler_radians=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        orientation=(1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0),
        linear_acceleration=(1.0, 2.0, 3.0),
        angular_acceleration=(4.0, 5.0, 6.0),
        baseline_properties={
            "mass": 10.0,
            "inertia": (9.0, 8.0, 7.0),
            "friction": 0.4,
            "linear_drag": 0.2,
            "angular_drag": 2.0,
        },
        active_properties={
            "mass": 9.0,
            "inertia": (8.0, 7.0, 6.0),
            "friction": 0.3,
            "linear_drag": 0.1,
            "angular_drag": 1.5,
        },
        current_input=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.0),
        jet_strength=0.25,
        jet_shape=(
            (2.0, -3.0, -20.0, 0.0, 0.0, -1.0, 0),
            (2.0, 3.0, -20.0, 0.0, 0.0, -1.0, 0),
            (-2.0, -3.0, -20.0, 0.0, 0.0, -1.0, 0),
            (-2.0, 3.0, -20.0, 0.0, 0.0, -1.0, 0),
        ),
        collision_asset=shape_path.read_bytes(),
        collision_identity="tank_1_s",
    )
    native.create_vehicle(
        world=world,
        entity_id=8,
        team=2,
        position=(5.0, 5.0, 5.0),
        linear_velocity=(0.0, 0.0, 0.0),
        euler_radians=(0.0, 0.0, 0.0),
        angular_velocity=(0.0, 0.0, 0.0),
        collision_asset=scout_shape_path.read_bytes(),
        collision_identity="scout_2_s",
        vehicle_type=1,
    )
    scout = next(entity for entity in native.write_snapshot(world)["entities"] if entity["id"] == 8)
    require(scout["controller_type"] == 2, "native Scout did not acquire the Scout controller")
    native.destroy_entity(world, 8)
    imported = native.write_snapshot(world)["entities"][0]
    hit = native.trace_segment(
        world=world,
        start=(0.0, 15.0, 5.0),
        end=(30.0, 15.0, 5.0),
        ignored_entity=0,
    )
    require(hit["hit"] and hit["entity_id"] == 7, "combat segment missed the Tank")
    require(imported["orientation"] == (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0), "exact orientation import was ignored")
    require(imported["linear_acceleration"] == (1.0, 2.0, 3.0), "linear acceleration import was ignored")
    require(imported["mass"] == 9.0, "active physical-property import was ignored")
    require(imported["baseline_physical_properties"]["mass"] == 10.0, "baseline physical-property import was ignored")
    require(
        all(abs(left - right) < 1.0e-6 for left, right in zip(imported["current_input"], (0.1, 0.2, 0.3, 0.4, 0.5, 0.6))),
        "persistent controller input import was ignored",
    )
    require(imported["jet_strength"] == 0.25, "jet-strength import was ignored")
    require(imported["jump_input"] == 0.0, "jump input import was ignored")
    require(
        not native.apply_authoritative_mutation(
            world=world,
            entity_id=7,
            position=(15.0, 15.0, -2.0),
            orientation=imported["orientation"],
        ),
        "below-terrain authoritative mutation was accepted",
    )
    require(
        native.write_snapshot(world)["entities"][0]["position"] == (15.0, 15.0, 5.0),
        "rejected authoritative mutation did not roll back",
    )
    require(
        native.apply_authoritative_mutation(
            world=world,
            entity_id=7,
            position=(15.0, 15.0, 30.0),
            orientation=imported["orientation"],
        ),
        "clear authoritative mutation was rejected",
    )
    require(
        native.resolve_initial_spawn_pose(world, 7) == 0.0,
        "clear native spawn pose received an unexpected lift",
    )
    native.submit_input(
        world=world,
        entity_id=7,
        sequence=11,
        target_tick=1,
        time_milliseconds=0,
        turn=0.0,
        move=1.0,
        strafe=0.0,
        jet=0.8,
        tilt=0.0,
        roll=0.0,
        jump=1.0,
    )
    native.set_contact_candidate_tracing(world, True)
    native.set_contact_round_robin_seed(world, 37)
    native.step_world(world, 1, 40)

    snapshot = native.write_snapshot(world)
    require(snapshot["tick"] == 1, "snapshot tick was not advanced")
    require(snapshot["physics_version"], "physics version is missing")
    require(snapshot["configuration_identity"] == "python-binding-config-v1", "configuration identity mismatch")
    require(snapshot["terrain_identity"] == "python-binding-level-v1", "terrain identity mismatch")
    require(len(snapshot["entities"]) == 1, "snapshot entity count mismatch")
    entity = snapshot["entities"][0]
    require(entity["id"] == 7, "snapshot entity id mismatch")
    require(entity["last_processed_input"] == 11, "processed input was not acknowledged")
    require(entity["pre_gravity_acceleration_is_significant"], "corrected +0xAD significance state is missing")
    require(entity["position"] != (15.0, 15.0, 5.0), "Tank did not advance")

    traces = native.drain_trace_events(world)
    require(any(event["type"] == 1 for event in traces), "input integration trace is missing")
    require(
        any(event["type"] == 2 and event["point"][1] > 15.0 for event in traces),
        "explicit jet shape did not reach PhysicsCore probe geometry",
    )
    require(any(event["type"] == 7 for event in traces), "step-end trace is missing")

    native.destroy_entity(world, 7)
    require(native.write_snapshot(world)["entities"] == [], "destroyed entity remains in snapshot")

    native.create_static_collider(
        world=world,
        entity_id=9,
        position=(15.0, 15.0, 50.0),
        euler_radians=(0.0, 0.0, 0.0),
        collision_asset=shape_path.read_bytes(),
        collision_identity="static-tank-shape",
        friction=0.75,
    )
    native.step_world(world, 2, 40)
    static_entity = native.write_snapshot(world)["entities"][0]
    require(static_entity["id"] == 9 and static_entity["is_static"],
            "static-collider role was not exported")
    require(static_entity["position"] == (15.0, 15.0, 50.0),
            "static collider advanced during a native world step")
    try:
        native.submit_input(
            world=world,
            entity_id=9,
            sequence=1,
            target_tick=3,
            time_milliseconds=80,
            turn=0.0,
            move=1.0,
            strafe=0.0,
            jet=0.0,
            tilt=0.0,
            roll=0.0,
            jump=0.0,
        )
        raise RuntimeError("static collider accepted vehicle input")
    except ValueError:
        pass
    native.destroy_entity(world, 9)
    native.create_projectile(
        world=world,
        entity_id=11,
        position=(5.0, 5.0, 20.0),
        linear_velocity=(10.0, 0.0, 0.0),
        euler_radians=(0.0, 0.0, 0.0),
        collision_asset=pulse_shape_path.read_bytes(),
        collision_identity="pulse_shell_s",
    )
    native.step_world(world, 3, 40)
    projectile = native.write_snapshot(world)["entities"][0]
    require(projectile["position"][0] > 5.0, "native projectile did not advance")
    require(projectile["position"][2] < 20.0, "native projectile did not receive gravity")
    require(projectile["controller_type"] == 0, "native projectile acquired a Tank controller")
    native.destroy_entity(world, 11)
    print("WulframPhysicsPython binding tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
