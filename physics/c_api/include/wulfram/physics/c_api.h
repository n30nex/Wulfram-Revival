#pragma once

#include <stdint.h>

#if defined(_WIN32)
#  if defined(WULFRAM_PHYSICS_C_EXPORTS)
#    define WP_API __declspec(dllexport)
#  else
#    define WP_API __declspec(dllimport)
#  endif
#else
#  define WP_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct wp_world wp_world;

enum { WP_API_VERSION = 11 };

typedef enum wp_vehicle_type {
    WP_VEHICLE_TANK = 0,
    WP_VEHICLE_SCOUT = 1,
    WP_VEHICLE_BOMBER = 2,
} wp_vehicle_type;

typedef enum wp_trace_event_type {
    WP_TRACE_STEP_BEGIN = 0,
    WP_TRACE_INPUT_INTEGRATED = 1,
    WP_TRACE_PROBE = 2,
    WP_TRACE_HOVER_OUTPUT = 3,
    WP_TRACE_CONTACT = 4,
    WP_TRACE_CORRECTION_ACCEPTED = 5,
    WP_TRACE_CORRECTION_REJECTED = 6,
    WP_TRACE_STEP_END = 7,
    WP_TRACE_CONTACT_CANDIDATE = 8,
    WP_TRACE_JUMP_ACCEPTED = 9,
} wp_trace_event_type;

typedef struct wp_vec3 {
    float x;
    float y;
    float z;
} wp_vec3;

typedef struct wp_matrix3d {
    double elements[9];
} wp_matrix3d;

typedef struct wp_body_state {
    uint32_t struct_size;
    wp_vec3 position;
    wp_vec3 linear_velocity;
    wp_vec3 linear_acceleration;
    wp_vec3 euler_radians;
    wp_vec3 angular_velocity;
    wp_vec3 angular_acceleration;
    wp_matrix3d orientation;
    float mass;
    wp_vec3 inertia;
    float active_friction;
    float active_linear_drag;
    float angular_drag;
    uint32_t legacy_type_code;
    double settling_contact_threshold;
} wp_body_state;

typedef enum wp_authoritative_mutation_field {
    WP_MUTATION_POSITION = 1u << 0,
    WP_MUTATION_ORIENTATION = 1u << 1,
    WP_MUTATION_LINEAR_VELOCITY = 1u << 2,
    WP_MUTATION_ANGULAR_VELOCITY = 1u << 3,
} wp_authoritative_mutation_field;

typedef struct wp_authoritative_mutation {
    uint32_t struct_size;
    uint32_t fields;
    wp_vec3 position;
    wp_vec3 euler_radians;
    wp_vec3 linear_velocity;
    wp_vec3 angular_velocity;
    uint64_t acknowledged_input_sequence;
} wp_authoritative_mutation;

typedef struct wp_terrain_desc {
    uint32_t struct_size;
    uint32_t count_x;
    uint32_t count_y;
    float spacing_x;
    float spacing_y;
    const float* heights_x_major;
} wp_terrain_desc;

typedef struct wp_tank_desc {
    uint32_t struct_size;
    uint64_t entity_id;
    wp_body_state initial_state;
    const uint8_t* collision_asset_bytes;
    uint32_t collision_asset_byte_count;
    uint32_t team;
    float fuel;
    float density;
    float baseline_friction;
    float baseline_linear_drag;
    float angular_drag;
    uint32_t is_alive;
} wp_tank_desc;

typedef struct wp_vehicle_desc {
    uint32_t struct_size;
    uint64_t entity_id;
    wp_body_state initial_state;
    const uint8_t* collision_asset_bytes;
    uint32_t collision_asset_byte_count;
    uint32_t vehicle_type;
    uint32_t team;
    float fuel;
    float density;
    float baseline_friction;
    float baseline_linear_drag;
    float angular_drag;
    uint32_t is_alive;
} wp_vehicle_desc;

typedef struct wp_vehicle_config {
    uint32_t struct_size;
    double turn_adjust;
    double move_adjust;
    double move_backward_adjust;
    double strafe_adjust;
    double maximum_velocity;
    double low_fuel_level;
    double maximum_altitude;
    double maximum_speed_height_pickup;
    double gravity_percent;
    double gravity_magnitude;
    double minimum_jet_strength;
    double jet_response_coefficient;
    double maximum_fuel;
    double jump_velocity;
    double jump_acceleration;
    double jump_fuel_cost;
    double fuel_regeneration_per_second;
    float density;
    float baseline_friction;
    float baseline_linear_drag;
    float angular_drag;
    float active_jet_friction;
    float acceleration_limit_scale;
} wp_vehicle_config;

enum { WP_VEHICLE_JET_POINT_COUNT = 4 };

typedef struct wp_vehicle_jet_point {
    wp_vec3 local_point;
    wp_vec3 configured_direction;
    uint32_t legacy_flag;
} wp_vehicle_jet_point;

typedef struct wp_vehicle_jet_shape {
    uint32_t struct_size;
    uint32_t point_count;
    wp_vehicle_jet_point points[WP_VEHICLE_JET_POINT_COUNT];
    float trailing_scalar;
} wp_vehicle_jet_shape;

typedef struct wp_vehicle_input {
    uint32_t struct_size;
    float turn;
    float move;
    float strafe;
    float jet;
    float tilt;
    float roll;
    float jump;
} wp_vehicle_input;

typedef struct wp_trace_event {
    uint32_t struct_size;
    uint32_t type;
    uint64_t tick;
    uint64_t entity_id;
    uint32_t step_milliseconds;
    int32_t feature;
    wp_vec3 point;
    wp_vec3 normal;
    wp_vec3 value;
    double scalar0;
    double scalar1;
    int32_t secondary_feature;
    int32_t bucket;
} wp_trace_event;

typedef struct wp_segment_hit {
    uint32_t struct_size;
    uint32_t hit;
    uint64_t entity_id;
    wp_vec3 point;
    wp_vec3 normal;
    float fraction;
} wp_segment_hit;

WP_API uint32_t wp_api_version(void);
WP_API wp_world* wp_world_create(const wp_terrain_desc* terrain);
WP_API void wp_world_destroy(wp_world* world);
WP_API int32_t wp_world_create_tank(wp_world* world, const wp_tank_desc* tank);
WP_API int32_t wp_world_create_vehicle(wp_world* world, const wp_vehicle_desc* vehicle);
WP_API int32_t wp_world_destroy_entity(wp_world* world, uint64_t entity_id);
WP_API int32_t wp_world_set_tank_jet_z_offset(
    wp_world* world,
    uint64_t entity_id,
    uint32_t team,
    float z_offset);
WP_API int32_t wp_world_set_tank_jet_pair_offsets(
    wp_world* world,
    uint64_t entity_id,
    uint32_t team,
    float front_z_offset,
    float front_longitudinal_offset,
    float front_separation_offset,
    float rear_z_offset,
    float rear_longitudinal_offset,
    float rear_separation_offset);
WP_API int32_t wp_world_set_vehicle_jet_pair_offsets(
    wp_world* world,
    uint64_t entity_id,
    uint32_t vehicle_type,
    uint32_t team,
    float front_z_offset,
    float front_longitudinal_offset,
    float front_separation_offset,
    float rear_z_offset,
    float rear_longitudinal_offset,
    float rear_separation_offset);
WP_API int32_t wp_world_set_vehicle_config(
    wp_world* world,
    uint64_t entity_id,
    uint32_t vehicle_type,
    const wp_vehicle_config* configuration);
WP_API int32_t wp_world_set_vehicle_jet_shape(
    wp_world* world,
    uint64_t entity_id,
    const wp_vehicle_jet_shape* shape);
WP_API int32_t wp_world_advance_frame(
    wp_world* world,
    uint32_t now_milliseconds,
    uint64_t entity_id,
    const wp_vehicle_input* input);
WP_API int32_t wp_world_submit_input(
    wp_world* world,
    uint64_t entity_id,
    uint64_t sequence,
    uint64_t target_tick,
    uint64_t time_milliseconds,
    const wp_vehicle_input* input);
WP_API int32_t wp_world_step_fixed(
    wp_world* world,
    uint64_t tick,
    uint32_t step_milliseconds);
WP_API int32_t wp_world_restore_authoritative_state(
    wp_world* world,
    uint64_t entity_id,
    uint64_t tick,
    uint64_t time_milliseconds,
    uint64_t acknowledged_input_sequence,
    const wp_body_state* state,
    const wp_vehicle_input* input);
WP_API int32_t wp_world_apply_authoritative_mutation(
    wp_world* world,
    uint64_t entity_id,
    const wp_authoritative_mutation* mutation);
WP_API int32_t wp_world_get_body_state(
    const wp_world* world,
    uint64_t entity_id,
    wp_body_state* state_out);
WP_API int32_t wp_world_put_body_to_sleep(
    wp_world* world,
    uint64_t entity_id);
WP_API int32_t wp_world_trace_segment(
    const wp_world* world,
    wp_vec3 start,
    wp_vec3 end,
    uint64_t ignored_entity_id,
    uint64_t second_ignored_entity_id,
    wp_segment_hit* hit_out);
WP_API int32_t wp_world_apply_linear_impulse(
    wp_world* world,
    uint64_t entity_id,
    wp_vec3 impulse);
WP_API int32_t wp_world_drain_trace_events(
    wp_world* world,
    wp_trace_event* events,
    uint32_t capacity,
    uint32_t* count_out);

#ifdef __cplusplus
}
#endif
