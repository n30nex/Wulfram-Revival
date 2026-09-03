#include "wulfram/physics/c_api.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <vector>

static_assert(sizeof(wp_trace_event) == 96, "wp_trace_event ABI layout changed");
static_assert(sizeof(wp_body_state) == 192, "wp_body_state ABI layout changed");
static_assert(sizeof(wp_authoritative_mutation) == 64,
    "wp_authoritative_mutation ABI layout changed");
static_assert(sizeof(wp_segment_hit) == 48, "wp_segment_hit ABI layout changed");
static_assert(sizeof(wp_vehicle_config) == 168, "wp_vehicle_config ABI layout changed");
static_assert(sizeof(wp_vehicle_jet_point) == 28,
    "wp_vehicle_jet_point ABI layout changed");
static_assert(sizeof(wp_vehicle_jet_shape) == 124,
    "wp_vehicle_jet_shape ABI layout changed");

namespace {

[[noreturn]] void Fail(const char* message) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(1);
}

void Require(bool condition, const char* message) {
    if (!condition) {
        Fail(message);
    }
}

} // namespace

int main() {
    Require(wp_api_version() == 11,
        "C API version does not include soft authoritative mutation");

    std::vector<float> heights(16, 0.0F);
    wp_terrain_desc terrain{};
    terrain.struct_size = sizeof(terrain);
    terrain.count_x = 4;
    terrain.count_y = 4;
    terrain.spacing_x = 10.0F;
    terrain.spacing_y = 10.0F;
    terrain.heights_x_major = heights.data();
    wp_world* world = wp_world_create(&terrain);
    Require(world != nullptr, "could not create C API test world");

    const char* path = WULFRAM_PHYSICS_COLLISION_ROOT "/tank_1_s";
    std::ifstream stream(path, std::ios::binary);
    Require(stream.good(), "authentic Tank collision asset fixture is unavailable");
    const std::vector<std::uint8_t> bytes{
        std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};

    wp_tank_desc tank{};
    tank.struct_size = sizeof(tank);
    tank.entity_id = 1;
    tank.initial_state.struct_size = sizeof(tank.initial_state);
    tank.initial_state.position = {15.0F, 15.0F, 5.0F};
    tank.initial_state.orientation.elements[0] = 1.0;
    tank.initial_state.orientation.elements[4] = 1.0;
    tank.initial_state.orientation.elements[8] = 1.0;
    tank.collision_asset_bytes = bytes.data();
    tank.collision_asset_byte_count = static_cast<std::uint32_t>(bytes.size());
    tank.team = 2;
    tank.fuel = 33000.0F;
    tank.density = 6700.0F;
    tank.baseline_friction = 0.4F;
    tank.baseline_linear_drag = 0.2F;
    tank.angular_drag = 2.0F;
    tank.is_alive = 1;
    Require(wp_world_create_tank(world, &tank) == 1, "could not create C API Tank");
    wp_segment_hit segmentHit{};
    segmentHit.struct_size = sizeof(segmentHit);
    Require(wp_world_trace_segment(
            world,
            {0.0F, 15.0F, 5.0F},
            {30.0F, 15.0F, 5.0F},
            0,
            0,
            &segmentHit) == 1
            && segmentHit.hit == 1
            && segmentHit.entity_id == 1,
        "C API combat segment missed the Tank");
    wp_vehicle_jet_shape packetShape{};
    packetShape.struct_size = sizeof(packetShape);
    packetShape.point_count = WP_VEHICLE_JET_POINT_COUNT;
    const wp_vec3 packetPoints[] = {
        {3.8345032F, -2.8484955F, -3.3065033F},
        {3.8345032F, 2.8484955F, -3.3065033F},
        {-5.3544922F, -3.0984955F, -0.3065033F},
        {-5.3544922F, 3.0984955F, -0.3065033F},
    };
    for (std::size_t index = 0; index < WP_VEHICLE_JET_POINT_COUNT; ++index) {
        packetShape.points[index].local_point = packetPoints[index];
        packetShape.points[index].configured_direction = {0.0F, 0.0F, -1.0F};
    }
    Require(wp_world_set_vehicle_jet_shape(world, 1, &packetShape) == 1,
        "could not install a packet-supplied C API Tank jet shape");

    wp_vehicle_input input{};
    input.struct_size = sizeof(input);
    input.jet = 0.8F;
    input.jump = 1.0F;
    Require(wp_world_advance_frame(world, 100, 1, &input) == 1,
        "C API frame advance failed");

    wp_trace_event tooSmall[1]{};
    std::uint32_t count = 0;
    Require(wp_world_drain_trace_events(world, tooSmall, 1, &count) == 0 && count > 1,
        "trace drain did not report required batch capacity");
    std::vector<wp_trace_event> events(count);
    Require(wp_world_drain_trace_events(world, events.data(), count, &count) == 1,
        "trace drain did not copy the complete batch");
    int probes = 0;
    int hoverOutputs = 0;
    int tunedProbeCount = 0;
    int acceptedJumps = 0;
    for (const wp_trace_event& event : events) {
        Require(event.struct_size == sizeof(wp_trace_event),
            "trace event did not carry its ABI size");
        if (event.type == WP_TRACE_PROBE) {
            ++probes;
            const wp_vec3 expected[] = {
                {18.8345032F, 12.1515045F, 1.6934967F},
                {18.8345032F, 17.8484955F, 1.6934967F},
                {9.6455078F, 11.9015045F, 4.6934967F},
                {9.6455078F, 18.0984955F, 4.6934967F},
            };
            if (event.feature >= 0 && event.feature < 4) {
                const wp_vec3& point = expected[event.feature];
                tunedProbeCount += std::fabs(event.point.x - point.x) < 0.0001F
                    && std::fabs(event.point.y - point.y) < 0.0001F
                    && std::fabs(event.point.z - point.z) < 0.0001F ? 1 : 0;
            }
        }
        hoverOutputs += event.type == WP_TRACE_HOVER_OUTPUT ? 1 : 0;
        acceptedJumps += event.type == WP_TRACE_JUMP_ACCEPTED ? 1 : 0;
    }
    Require(probes == 4 && hoverOutputs == 1,
        "C API trace batch lost native hover diagnostics");
    Require(tunedProbeCount == 4,
        "C API Tank did not independently tune both jet pairs");
    Require(acceptedJumps == 1,
        "C API did not forward the binary jump request into the portable core");

    input.jump = 0.0F;
    Require(wp_world_submit_input(world, 1, 2, 2, 40, &input) == 1,
        "C API rejected a sequenced fixed-tick input");
    Require(wp_world_step_fixed(world, 2, 40) == 1,
        "C API fixed 40 ms step failed");
    Require(wp_world_step_fixed(world, 2, 40) == 0,
        "C API accepted a repeated fixed tick");
    count = 0;
    Require(wp_world_drain_trace_events(world, nullptr, 0, &count) == 0 && count > 0,
        "fixed C API step did not emit diagnostics");
    events.assign(count, {});
    Require(wp_world_drain_trace_events(world, events.data(), count, &count) == 1,
        "fixed C API step diagnostics could not be drained");
    Require(std::any_of(events.begin(), events.end(), [](const wp_trace_event& event) {
        return event.type == WP_TRACE_STEP_BEGIN
            && event.tick == 2
            && event.step_milliseconds == 40;
    }), "fixed C API step diagnostics lost the explicit tick or duration");

    wp_body_state body{};
    body.struct_size = sizeof(body);
    Require(wp_world_get_body_state(world, 1, &body) == 1,
        "C API did not return the post-jump body state");
    Require(body.linear_velocity.z > 100.0F,
        "C API test jump did not leave motion for the sleep transition to clear");
    wp_body_state authoritative = body;
    authoritative.position.x += 1.5F;
    authoritative.euler_radians.z = 0.25F;
    input.move = 0.0F;
    Require(wp_world_restore_authoritative_state(
            world, 1, 2, 80, 2, &authoritative, &input) == 1,
        "C API rejected an authoritative rewind state");
    Require(wp_world_get_body_state(world, 1, &body) == 1
            && std::fabs(body.position.x - authoritative.position.x) < 0.0001F
            && std::fabs(body.euler_radians.z - 0.25F) < 0.0001F,
        "C API authoritative restore did not replace the motion pose");
    Require(wp_world_submit_input(world, 1, 3, 3, 80, &input) == 1
            && wp_world_step_fixed(world, 3, 40) == 1,
        "C API could not replay an unacknowledged input after restore");
    body = {};
    body.struct_size = sizeof(body);
    Require(wp_world_get_body_state(world, 1, &body) == 1,
        "C API could not read the body before a soft correction");
    wp_authoritative_mutation softCorrection{};
    softCorrection.struct_size = sizeof(softCorrection);
    softCorrection.fields = WP_MUTATION_POSITION |
        WP_MUTATION_LINEAR_VELOCITY;
    softCorrection.position = body.position;
    softCorrection.position.z += 0.25F;
    softCorrection.linear_velocity = {1.0F, 2.0F, 3.0F};
    softCorrection.acknowledged_input_sequence = 3;
    Require(wp_world_apply_authoritative_mutation(
            world, 1, &softCorrection) == 1,
        "C API rejected a collision-checked soft authoritative mutation");
    body = {};
    body.struct_size = sizeof(body);
    Require(wp_world_get_body_state(world, 1, &body) == 1
            && std::fabs(body.position.z - softCorrection.position.z) < 0.0001F
            && std::fabs(body.linear_velocity.x - 1.0F) < 0.0001F
            && std::fabs(body.linear_velocity.y - 2.0F) < 0.0001F
            && std::fabs(body.linear_velocity.z - 3.0F) < 0.0001F,
        "C API soft authoritative mutation did not update pose and velocity");
    count = 0;
    Require(wp_world_drain_trace_events(world, nullptr, 0, &count) == 0 && count > 0,
        "authoritative restore and replay did not emit diagnostics");
    events.assign(count, {});
    Require(wp_world_drain_trace_events(world, events.data(), count, &count) == 1,
        "authoritative restore and replay diagnostics could not be drained");
    Require(wp_world_put_body_to_sleep(world, 1) == 1,
        "C API rejected the Unity docking sleep transition");
    Require(wp_world_apply_linear_impulse(world, 1, {100.0F, 0.0F, 0.0F}) == 1,
        "C API rejected a combat impulse");
    Require(wp_world_get_body_state(world, 1, &body) == 1,
        "C API did not return the sleeping body state");
    Require(body.linear_velocity.x > 0.0F
            && body.linear_velocity.y == 0.0F
            && body.linear_velocity.z == 0.0F
            && body.angular_velocity.x == 0.0F
            && body.angular_velocity.y == 0.0F
            && body.angular_velocity.z == 0.0F,
        "C API sleep transition did not clear body motion");

    count = 99;
    Require(wp_world_drain_trace_events(world, nullptr, 0, &count) == 1 && count == 0,
        "trace drain did not consume the copied batch");

    Require(wp_world_destroy_entity(world, 1) == 1,
        "could not remove the Tank before the Scout C API test");
    const char* scoutPath =
        WULFRAM_PHYSICS_COLLISION_ROOT "/scout_1_s";
    std::ifstream scoutStream(scoutPath, std::ios::binary);
    Require(scoutStream.good(), "authentic Scout collision asset fixture is unavailable");
    const std::vector<std::uint8_t> scoutBytes{
        std::istreambuf_iterator<char>(scoutStream),
        std::istreambuf_iterator<char>()};

    wp_vehicle_desc scout{};
    scout.struct_size = sizeof(scout);
    scout.entity_id = 2;
    scout.initial_state.struct_size = sizeof(scout.initial_state);
    scout.initial_state.position = {15.0F, 15.0F, 7.0F};
    scout.initial_state.orientation.elements[0] = 1.0;
    scout.initial_state.orientation.elements[4] = 1.0;
    scout.initial_state.orientation.elements[8] = 1.0;
    scout.collision_asset_bytes = scoutBytes.data();
    scout.collision_asset_byte_count =
        static_cast<std::uint32_t>(scoutBytes.size());
    scout.vehicle_type = WP_VEHICLE_SCOUT;
    scout.team = 2;
    scout.fuel = 13000.0F;
    scout.density = 6700.0F;
    scout.baseline_friction = 0.4F;
    scout.baseline_linear_drag = 0.2F;
    scout.angular_drag = 2.0F;
    scout.is_alive = 1;
    Require(wp_world_create_vehicle(world, &scout) == 1,
        "could not create a C API Scout");
    body = {};
    body.struct_size = sizeof(body);
    Require(wp_world_get_body_state(world, 2, &body) == 1,
        "could not read the Scout before live tuning");
    const float originalScoutMass = body.mass;
    wp_vehicle_config scoutConfig{};
    scoutConfig.struct_size = sizeof(scoutConfig);
    scoutConfig.turn_adjust = 4.5;
    scoutConfig.move_adjust = 85.0;
    scoutConfig.move_backward_adjust = 38.0;
    scoutConfig.strafe_adjust = 72.0;
    scoutConfig.maximum_velocity = 85.0;
    scoutConfig.low_fuel_level = 2000.0;
    scoutConfig.maximum_altitude = 4.9;
    scoutConfig.maximum_speed_height_pickup = 3.5;
    scoutConfig.gravity_percent = 1.0;
    scoutConfig.gravity_magnitude = 160.0;
    scoutConfig.minimum_jet_strength = 0.15;
    scoutConfig.jet_response_coefficient = 1.1;
    scoutConfig.maximum_fuel = 13000.0;
    scoutConfig.fuel_regeneration_per_second = 0.0;
    scoutConfig.density = scout.density * 2.0F;
    scoutConfig.baseline_friction = scout.baseline_friction;
    scoutConfig.baseline_linear_drag = scout.baseline_linear_drag;
    scoutConfig.angular_drag = scout.angular_drag;
    scoutConfig.active_jet_friction = 0.0F;
    scoutConfig.acceleration_limit_scale = 1.25F;
    Require(wp_world_set_vehicle_config(
            world, 2, WP_VEHICLE_SCOUT, &scoutConfig) == 1,
        "could not apply live Scout tuning through the C API");
    Require(wp_world_set_vehicle_config(
            world, 2, WP_VEHICLE_TANK, &scoutConfig) == 0,
        "vehicle tuning accepted a mismatched controller type");
    body = {};
    body.struct_size = sizeof(body);
    Require(wp_world_get_body_state(world, 2, &body) == 1
            && body.mass > originalScoutMass * 1.99F
            && body.mass < originalScoutMass * 2.01F,
        "live Scout density tuning did not refresh native mass/inertia");
    Require(wp_world_set_vehicle_jet_pair_offsets(
            world, 2, WP_VEHICLE_SCOUT, scout.team,
            0.0F, 0.0F, 0.0F, 0.0F, 0.0F, 0.0F) == 1,
        "could not install the Scout jet geometry");
    input.jump = 1.0F;
    Require(wp_world_advance_frame(world, 200, 2, &input) == 1,
        "C API Scout frame advance failed");
    count = 0;
    Require(wp_world_drain_trace_events(world, nullptr, 0, &count) == 0 && count > 0,
        "Scout trace drain did not report its required capacity");
    events.assign(count, {});
    Require(wp_world_drain_trace_events(world, events.data(), count, &count) == 1,
        "Scout trace drain failed");
    probes = 0;
    hoverOutputs = 0;
    acceptedJumps = 0;
    for (const wp_trace_event& event : events) {
        probes += event.type == WP_TRACE_PROBE ? 1 : 0;
        hoverOutputs += event.type == WP_TRACE_HOVER_OUTPUT ? 1 : 0;
        acceptedJumps += event.type == WP_TRACE_JUMP_ACCEPTED ? 1 : 0;
    }
    Require(probes == 4 && hoverOutputs == 1,
        "C API Scout did not use its four-probe hover controller");
    Require(acceptedJumps == 0,
        "Scout accepted a guessed Tank jump configuration");

    wp_vehicle_desc bomber = scout;
    bomber.entity_id = 3;
    bomber.vehicle_type = WP_VEHICLE_BOMBER;
    Require(wp_world_create_vehicle(world, &bomber) == 0,
        "unsupported Bomber controller was not rejected");
    wp_world_destroy(world);
    return 0;
}
