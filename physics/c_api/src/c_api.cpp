#include "wulfram/physics/c_api.h"

#include "wulfram/physics/physics.hpp"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace wulfram::physics;

Vec3f FromC(wp_vec3 value) noexcept { return {value.x, value.y, value.z}; }
wp_vec3 ToC(Vec3f value) noexcept { return {value.x, value.y, value.z}; }

BodyState FromC(const wp_body_state& value) noexcept {
    BodyState result{};
    result.position = FromC(value.position);
    result.linearVelocity = FromC(value.linear_velocity);
    result.linearAcceleration = FromC(value.linear_acceleration);
    result.eulerRadians = FromC(value.euler_radians);
    result.angularVelocity = FromC(value.angular_velocity);
    result.angularAcceleration = FromC(value.angular_acceleration);
    std::memcpy(result.orientation.elements, value.orientation.elements, sizeof(result.orientation.elements));
    result.mass = value.mass;
    result.inertia = FromC(value.inertia);
    result.activeFriction = value.active_friction;
    result.activeLinearDrag = value.active_linear_drag;
    result.angularDrag = value.angular_drag;
    result.legacyTypeCode = value.legacy_type_code;
    result.settlingContactThreshold = value.settling_contact_threshold;
    return result;
}

void ToC(const BodyState& value, wp_body_state& result) noexcept {
    result = {};
    result.struct_size = sizeof(result);
    result.position = ToC(value.position);
    result.linear_velocity = ToC(value.linearVelocity);
    result.linear_acceleration = ToC(value.linearAcceleration);
    result.euler_radians = ToC(value.eulerRadians);
    result.angular_velocity = ToC(value.angularVelocity);
    result.angular_acceleration = ToC(value.angularAcceleration);
    std::memcpy(result.orientation.elements, value.orientation.elements, sizeof(result.orientation.elements));
    result.mass = value.mass;
    result.inertia = ToC(value.inertia);
    result.active_friction = value.activeFriction;
    result.active_linear_drag = value.activeLinearDrag;
    result.angular_drag = value.angularDrag;
    result.legacy_type_code = value.legacyTypeCode;
    result.settling_contact_threshold = value.settlingContactThreshold;
}

void ToC(const TraceEvent& value, wp_trace_event& result) noexcept {
    result = {};
    result.struct_size = sizeof(result);
    result.type = static_cast<std::uint32_t>(value.type);
    result.tick = value.tick;
    result.entity_id = value.entity;
    result.step_milliseconds = value.stepMilliseconds;
    result.feature = value.feature;
    result.point = ToC(value.point);
    result.normal = ToC(value.normal);
    result.value = ToC(value.value);
    result.scalar0 = value.scalar0;
    result.scalar1 = value.scalar1;
    result.secondary_feature = value.secondaryFeature;
    result.bucket = value.bucket;
}

bool IsFinite(const wp_vehicle_config& value) noexcept {
    const double doubles[] = {
        value.turn_adjust,
        value.move_adjust,
        value.move_backward_adjust,
        value.strafe_adjust,
        value.maximum_velocity,
        value.low_fuel_level,
        value.maximum_altitude,
        value.maximum_speed_height_pickup,
        value.gravity_percent,
        value.gravity_magnitude,
        value.minimum_jet_strength,
        value.jet_response_coefficient,
        value.maximum_fuel,
        value.jump_velocity,
        value.jump_acceleration,
        value.jump_fuel_cost,
        value.fuel_regeneration_per_second,
    };
    const float floats[] = {
        value.density,
        value.baseline_friction,
        value.baseline_linear_drag,
        value.angular_drag,
        value.active_jet_friction,
        value.acceleration_limit_scale,
    };
    for (double item : doubles) {
        if (!std::isfinite(item)) return false;
    }
    for (float item : floats) {
        if (!std::isfinite(item)) return false;
    }
    return true;
}

bool IsFinite(const wp_vehicle_jet_shape& value) noexcept {
    if (!std::isfinite(value.trailing_scalar)) {
        return false;
    }
    for (const wp_vehicle_jet_point& point : value.points) {
        const float values[] = {
            point.local_point.x,
            point.local_point.y,
            point.local_point.z,
            point.configured_direction.x,
            point.configured_direction.y,
            point.configured_direction.z,
        };
        for (float item : values) {
            if (!std::isfinite(item)) return false;
        }
    }
    return true;
}

TankConfiguration FromC(
    const wp_vehicle_config& value,
    TankConfiguration result) {
    result.turnAdjust = value.turn_adjust;
    result.moveAdjust = value.move_adjust;
    result.moveBackwardAdjust = value.move_backward_adjust;
    result.strafeAdjust = value.strafe_adjust;
    result.maximumVelocity = value.maximum_velocity;
    result.lowFuelLevel = value.low_fuel_level;
    result.maximumAltitude = value.maximum_altitude;
    result.maximumSpeedHeightPickup = value.maximum_speed_height_pickup;
    result.gravityPercent = value.gravity_percent;
    result.gravityMagnitude = value.gravity_magnitude;
    result.minimumJetStrength = value.minimum_jet_strength;
    result.jetResponseCoefficient = value.jet_response_coefficient;
    result.maximumFuel = value.maximum_fuel;
    result.jumpVelocity = value.jump_velocity;
    result.jumpAcceleration = value.jump_acceleration;
    result.jumpFuelCost = value.jump_fuel_cost;
    result.fuelRegenerationPerSecond = value.fuel_regeneration_per_second;
    result.density = value.density;
    result.baselineFriction = value.baseline_friction;
    result.baselineLinearDrag = value.baseline_linear_drag;
    result.angularDrag = value.angular_drag;
    result.activeJetFriction = value.active_jet_friction;
    result.accelerationLimitScale = value.acceleration_limit_scale;
    return result;
}

} // namespace

struct wp_world {
    explicit wp_world(TerrainGrid terrain)
        : world(DefaultPhysicsConfig(), std::move(terrain)) {}

    World world;
    FrameScheduler scheduler{};
    SimulationTick nextTick = 1;
    InputSequence nextInputSequence = 1;
    std::vector<TraceEvent> pendingTrace{};
};

extern "C" uint32_t wp_api_version(void) { return WP_API_VERSION; }

extern "C" wp_world* wp_world_create(const wp_terrain_desc* terrain) {
    try {
        TerrainGrid grid{};
        if (terrain != nullptr && terrain->struct_size >= sizeof(wp_terrain_desc) &&
            terrain->count_x >= 2 && terrain->count_y >= 2 && terrain->heights_x_major != nullptr) {
            const std::size_t count = static_cast<std::size_t>(terrain->count_x) * terrain->count_y;
            grid = TerrainGrid(
                terrain->count_x,
                terrain->count_y,
                terrain->spacing_x,
                terrain->spacing_y,
                std::vector<float>(terrain->heights_x_major, terrain->heights_x_major + count),
                "unity-sandbox-terrain");
        }
        return new wp_world(std::move(grid));
    } catch (...) {
        return nullptr;
    }
}

extern "C" void wp_world_destroy(wp_world* world) { delete world; }

extern "C" int32_t wp_world_create_vehicle(
    wp_world* world,
    const wp_vehicle_desc* vehicle) {
    if (world == nullptr || vehicle == nullptr ||
        vehicle->struct_size < sizeof(wp_vehicle_desc) ||
        vehicle->entity_id == 0 ||
        vehicle->initial_state.struct_size < sizeof(wp_body_state) ||
        vehicle->vehicle_type > WP_VEHICLE_SCOUT) {
        return 0;
    }
    try {
        const bool scout = vehicle->vehicle_type == WP_VEHICLE_SCOUT;
        const bool blue = vehicle->team == 1;
        const char* shapeName = scout
            ? (blue ? "scout_2_s" : "scout_1_s")
            : (blue ? "tank_2_s" : "tank_1_s");
        CollisionShape shape{};
        if (!DecodeLegacyCollisionShape(
                vehicle->collision_asset_bytes,
                vehicle->collision_asset_byte_count,
                shape,
                shapeName)) {
            return 0;
        }
        EntityDefinition definition{};
        definition.id = vehicle->entity_id;
        definition.initialState = FromC(vehicle->initial_state);
        definition.collisionShape = shape;
        definition.jetShape = scout
            ? (blue ? MedicBlueJetShape() : MedicRedJetShape())
            : (blue ? TankBlueJetShape() : TankRedJetShape());
        definition.controllerType = scout
            ? ControllerType::Scout
            : ControllerType::Tank;
        definition.fuel = vehicle->fuel;
        definition.alive = vehicle->is_alive != 0;
        definition.baselinePhysicalProperties = DeriveTankPhysicalProperties(
            shape,
            vehicle->density,
            vehicle->baseline_friction,
            vehicle->baseline_linear_drag,
            vehicle->angular_drag);
        return world->world.CreateEntity(definition) ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

extern "C" int32_t wp_world_create_tank(wp_world* world, const wp_tank_desc* tank) {
    if (tank == nullptr || tank->struct_size < sizeof(wp_tank_desc)) {
        return 0;
    }
    wp_vehicle_desc vehicle{};
    vehicle.struct_size = sizeof(vehicle);
    vehicle.entity_id = tank->entity_id;
    vehicle.initial_state = tank->initial_state;
    vehicle.collision_asset_bytes = tank->collision_asset_bytes;
    vehicle.collision_asset_byte_count = tank->collision_asset_byte_count;
    vehicle.vehicle_type = WP_VEHICLE_TANK;
    vehicle.team = tank->team;
    vehicle.fuel = tank->fuel;
    vehicle.density = tank->density;
    vehicle.baseline_friction = tank->baseline_friction;
    vehicle.baseline_linear_drag = tank->baseline_linear_drag;
    vehicle.angular_drag = tank->angular_drag;
    vehicle.is_alive = tank->is_alive;
    return wp_world_create_vehicle(world, &vehicle);
}

extern "C" int32_t wp_world_destroy_entity(wp_world* world, uint64_t entity_id) {
    return world != nullptr && world->world.DestroyEntity(entity_id) ? 1 : 0;
}

extern "C" int32_t wp_world_set_tank_jet_z_offset(
    wp_world* world,
    uint64_t entity_id,
    uint32_t team,
    float z_offset) {
    return wp_world_set_tank_jet_pair_offsets(
        world, entity_id, team,
        z_offset, 0.0F, 0.0F,
        z_offset, 0.0F, 0.0F);
}

extern "C" int32_t wp_world_set_tank_jet_pair_offsets(
    wp_world* world,
    uint64_t entity_id,
    uint32_t team,
    float front_z_offset,
    float front_longitudinal_offset,
    float front_separation_offset,
    float rear_z_offset,
    float rear_longitudinal_offset,
    float rear_separation_offset) {
    return wp_world_set_vehicle_jet_pair_offsets(
        world,
        entity_id,
        WP_VEHICLE_TANK,
        team,
        front_z_offset,
        front_longitudinal_offset,
        front_separation_offset,
        rear_z_offset,
        rear_longitudinal_offset,
        rear_separation_offset);
}

extern "C" int32_t wp_world_set_vehicle_jet_pair_offsets(
    wp_world* world,
    uint64_t entity_id,
    uint32_t vehicle_type,
    uint32_t team,
    float front_z_offset,
    float front_longitudinal_offset,
    float front_separation_offset,
    float rear_z_offset,
    float rear_longitudinal_offset,
    float rear_separation_offset) {
    if (world == nullptr
        || vehicle_type > WP_VEHICLE_SCOUT
        || !std::isfinite(front_z_offset)
        || !std::isfinite(front_longitudinal_offset)
        || !std::isfinite(front_separation_offset)
        || !std::isfinite(rear_z_offset)
        || !std::isfinite(rear_longitudinal_offset)
        || !std::isfinite(rear_separation_offset)) {
        return 0;
    }
    const bool scout = vehicle_type == WP_VEHICLE_SCOUT;
    JetShape shape = scout
        ? (team == 1 ? MedicBlueJetShape() : MedicRedJetShape())
        : (team == 1 ? TankBlueJetShape() : TankRedJetShape());
    for (std::size_t index = 0; index < shape.points.size(); ++index) {
        JetShapePoint& point = shape.points[index];
        const bool front = index < 2;
        point.localPoint.x += front
            ? front_longitudinal_offset : rear_longitudinal_offset;
        point.localPoint.y += std::copysign(
            front ? front_separation_offset : rear_separation_offset,
            point.localPoint.y);
        point.localPoint.z += front ? front_z_offset : rear_z_offset;
    }
    return world->world.SetJetShape(entity_id, shape) ? 1 : 0;
}

extern "C" int32_t wp_world_set_vehicle_config(
    wp_world* world,
    uint64_t entity_id,
    uint32_t vehicle_type,
    const wp_vehicle_config* configuration) {
    if (world == nullptr || configuration == nullptr ||
        configuration->struct_size < sizeof(wp_vehicle_config) ||
        vehicle_type > WP_VEHICLE_SCOUT ||
        !IsFinite(*configuration) ||
        configuration->density <= 0.0F) {
        return 0;
    }
    try {
        const PhysicsConfig& defaults = world->world.Config();
        const TankConfiguration& base = vehicle_type == WP_VEHICLE_SCOUT
            ? defaults.scout
            : defaults.tank;
        return world->world.SetVehicleConfiguration(
            entity_id,
            vehicle_type == WP_VEHICLE_SCOUT
                ? ControllerType::Scout
                : ControllerType::Tank,
            FromC(*configuration, base)) ? 1 : 0;
    } catch (...) {
        return 0;
    }
}

extern "C" int32_t wp_world_set_vehicle_jet_shape(
    wp_world* world,
    uint64_t entity_id,
    const wp_vehicle_jet_shape* shape) {
    if (world == nullptr || shape == nullptr ||
        shape->struct_size < sizeof(wp_vehicle_jet_shape) ||
        shape->point_count != WP_VEHICLE_JET_POINT_COUNT ||
        !IsFinite(*shape)) {
        return 0;
    }
    JetShape nativeShape{};
    for (std::size_t index = 0; index < nativeShape.points.size(); ++index) {
        nativeShape.points[index].localPoint = FromC(shape->points[index].local_point);
        nativeShape.points[index].configuredDirection =
            FromC(shape->points[index].configured_direction);
        nativeShape.points[index].legacyFlag = shape->points[index].legacy_flag != 0;
    }
    return world->world.SetJetShape(entity_id, nativeShape) ? 1 : 0;
}

extern "C" int32_t wp_world_advance_frame(
    wp_world* world,
    uint32_t now_milliseconds,
    uint64_t entity_id,
    const wp_vehicle_input* input) {
    if (world == nullptr || input == nullptr || input->struct_size < sizeof(wp_vehicle_input)) {
        return 0;
    }
    InputEvent event{};
    event.sequence = world->nextInputSequence++;
    event.targetTick = world->nextTick;
    event.timeMilliseconds = world->world.TimeMilliseconds();
    event.controls = {
        input->turn,
        input->move,
        input->strafe,
        input->jet,
        input->tilt,
        input->roll,
        input->jump,
    };
    if (!world->world.SubmitInput(entity_id, event)) {
        return 0;
    }
    for (StepMilliseconds step : world->scheduler.Advance(now_milliseconds)) {
        if (!world->world.StepWorld(world->nextTick++, step)) {
            return 0;
        }
    }
    return 1;
}

extern "C" int32_t wp_world_submit_input(
    wp_world* world,
    uint64_t entity_id,
    uint64_t sequence,
    uint64_t target_tick,
    uint64_t time_milliseconds,
    const wp_vehicle_input* input) {
    if (world == nullptr || input == nullptr ||
        input->struct_size < sizeof(wp_vehicle_input) || sequence == 0 ||
        target_tick < world->nextTick) {
        return 0;
    }
    InputEvent event{};
    event.sequence = sequence;
    event.targetTick = target_tick;
    event.timeMilliseconds = time_milliseconds;
    event.controls = {
        input->turn,
        input->move,
        input->strafe,
        input->jet,
        input->tilt,
        input->roll,
        input->jump,
    };
    if (!world->world.SubmitInput(entity_id, event)) {
        return 0;
    }
    world->nextInputSequence = std::max(
        world->nextInputSequence,
        static_cast<InputSequence>(sequence + 1));
    return 1;
}

extern "C" int32_t wp_world_step_fixed(
    wp_world* world,
    uint64_t tick,
    uint32_t step_milliseconds) {
    if (world == nullptr || tick != world->nextTick || step_milliseconds == 0) {
        return 0;
    }
    if (!world->world.StepWorld(tick, step_milliseconds)) {
        return 0;
    }
    world->nextTick = tick + 1;
    return 1;
}

extern "C" int32_t wp_world_restore_authoritative_state(
    wp_world* world,
    uint64_t entity_id,
    uint64_t tick,
    uint64_t time_milliseconds,
    uint64_t acknowledged_input_sequence,
    const wp_body_state* state,
    const wp_vehicle_input* input) {
    if (world == nullptr || state == nullptr || input == nullptr ||
        state->struct_size < sizeof(wp_body_state) ||
        input->struct_size < sizeof(wp_vehicle_input)) {
        return 0;
    }
    const VehicleInput restoredInput{
        input->turn,
        input->move,
        input->strafe,
        input->jet,
        input->tilt,
        input->roll,
        input->jump,
    };
    if (!world->world.RestoreAuthoritativeState(
            entity_id,
            FromC(*state),
            restoredInput,
            acknowledged_input_sequence,
            tick,
            time_milliseconds)) {
        return 0;
    }
    world->nextTick = tick + 1;
    world->nextInputSequence = acknowledged_input_sequence + 1;
    world->pendingTrace.clear();
    return 1;
}

extern "C" int32_t wp_world_apply_authoritative_mutation(
    wp_world* world,
    uint64_t entity_id,
    const wp_authoritative_mutation* mutation) {
    if (world == nullptr || mutation == nullptr ||
        mutation->struct_size < sizeof(wp_authoritative_mutation)) {
        return 0;
    }
    constexpr uint32_t kKnownFields =
        WP_MUTATION_POSITION |
        WP_MUTATION_ORIENTATION |
        WP_MUTATION_LINEAR_VELOCITY |
        WP_MUTATION_ANGULAR_VELOCITY;
    if ((mutation->fields & ~kKnownFields) != 0) {
        return 0;
    }

    AuthoritativeMutation native{};
    if ((mutation->fields & WP_MUTATION_POSITION) != 0) {
        native.position = FromC(mutation->position);
    }
    if ((mutation->fields & WP_MUTATION_ORIENTATION) != 0) {
        native.orientation = Matrix3d::FromEulerAngles(
            FromC(mutation->euler_radians));
    }
    if ((mutation->fields & WP_MUTATION_LINEAR_VELOCITY) != 0) {
        native.linearVelocity = FromC(mutation->linear_velocity);
    }
    if ((mutation->fields & WP_MUTATION_ANGULAR_VELOCITY) != 0) {
        native.angularVelocity = FromC(mutation->angular_velocity);
    }
    native.acknowledgedInput = mutation->acknowledged_input_sequence;
    return world->world.ApplyAuthoritativeMutation(entity_id, native) ? 1 : 0;
}

extern "C" int32_t wp_world_get_body_state(
    const wp_world* world,
    uint64_t entity_id,
    wp_body_state* state_out) {
    if (world == nullptr || state_out == nullptr || state_out->struct_size < sizeof(wp_body_state)) {
        return 0;
    }
    const BodyState* state = world->world.GetBodyState(entity_id);
    if (state == nullptr) {
        return 0;
    }
    ToC(*state, *state_out);
    return 1;
}

extern "C" int32_t wp_world_put_body_to_sleep(
    wp_world* world,
    uint64_t entity_id) {
    return world != nullptr && world->world.PutBodyToSleep(entity_id) ? 1 : 0;
}

extern "C" int32_t wp_world_trace_segment(
    const wp_world* world,
    wp_vec3 start,
    wp_vec3 end,
    uint64_t ignored_entity_id,
    uint64_t second_ignored_entity_id,
    wp_segment_hit* hit_out) {
    if (world == nullptr || hit_out == nullptr || hit_out->struct_size < sizeof(wp_segment_hit)) {
        return 0;
    }
    const SegmentHit hit = world->world.TraceSegment(
        FromC(start), FromC(end), ignored_entity_id, second_ignored_entity_id);
    *hit_out = {};
    hit_out->struct_size = sizeof(*hit_out);
    hit_out->hit = hit.hit ? 1U : 0U;
    hit_out->entity_id = hit.entity;
    hit_out->point = ToC(hit.point);
    hit_out->normal = ToC(hit.normal);
    hit_out->fraction = hit.fraction;
    return 1;
}

extern "C" int32_t wp_world_apply_linear_impulse(
    wp_world* world,
    uint64_t entity_id,
    wp_vec3 impulse) {
    return world != nullptr && world->world.ApplyLinearImpulse(entity_id, FromC(impulse)) ? 1 : 0;
}

extern "C" int32_t wp_world_drain_trace_events(
    wp_world* world,
    wp_trace_event* events,
    uint32_t capacity,
    uint32_t* count_out) {
    if (world == nullptr || count_out == nullptr || (events == nullptr && capacity != 0)) {
        return 0;
    }
    try {
        if (world->pendingTrace.empty()) {
            world->pendingTrace = world->world.DrainTraceEvents();
        }
        const std::size_t required = world->pendingTrace.size();
        if (required > static_cast<std::size_t>(UINT32_MAX)) {
            *count_out = UINT32_MAX;
            return 0;
        }
        *count_out = static_cast<std::uint32_t>(required);
        if (capacity < required) {
            return 0;
        }
        for (std::size_t index = 0; index < required; ++index) {
            ToC(world->pendingTrace[index], events[index]);
        }
        world->pendingTrace.clear();
        return 1;
    } catch (...) {
        return 0;
    }
}
