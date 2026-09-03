#pragma once

#include "wulfram/physics/config.hpp"
#include "wulfram/physics/terrain.hpp"

#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <vector>

namespace wulfram::physics {

struct VehicleInput {
    float turn = 0.0F;
    float move = 0.0F;
    float strafe = 0.0F;
    float jet = 0.0F;
    float tilt = 0.0F;
    float roll = 0.0F;
    // Original action channel 4. Unlike the sampled motion channels, jump is
    // consumed as a binary rising-edge request by the authoritative core.
    float jump = 0.0F;
};

struct InputEvent {
    InputSequence sequence = 0;
    SimulationTick targetTick = 0;
    std::uint64_t timeMilliseconds = 0;
    VehicleInput controls{};
};

enum class BodyMotionType : std::uint8_t {
    Dynamic,
    Static,
};

enum class ControllerType : std::uint8_t {
    None,
    Tank,
    Scout,
};

struct EntityDefinition {
    EntityId id = 0;
    BodyState initialState{};
    PhysicalProperties baselinePhysicalProperties{};
    std::optional<PhysicalProperties> activePhysicalProperties{};
    CollisionShape collisionShape{};
    JetShape jetShape = TankRedJetShape();
    float fuel = 33000.0F;
    float jetStrength = 0.0F;
    VehicleInput initialInput{};
    InputSequence lastProcessedInput = 0;
    BodyMotionType motionType = BodyMotionType::Dynamic;
    ControllerType controllerType = ControllerType::Tank;
    bool alive = true;
};

struct AuthoritativeMutation {
    std::optional<Vec3f> position{};
    std::optional<Matrix3d> orientation{};
    std::optional<Vec3f> linearVelocity{};
    std::optional<Vec3f> angularVelocity{};
    InputSequence acknowledgedInput = 0;
};

enum class TraceEventType : std::uint8_t {
    StepBegin,
    InputIntegrated,
    Probe,
    HoverOutput,
    Contact,
    CorrectionAccepted,
    CorrectionRejected,
    StepEnd,
    ContactCandidate,
    JumpAccepted,
};

struct TraceEvent {
    TraceEventType type = TraceEventType::StepBegin;
    SimulationTick tick = 0;
    EntityId entity = 0;
    StepMilliseconds stepMilliseconds = 0;
    std::int32_t feature = -1;
    Vec3f point{};
    Vec3f normal{};
    Vec3f value{};
    double scalar0 = 0.0;
    double scalar1 = 0.0;
    std::int32_t secondaryFeature = -1;
    std::int32_t bucket = -1;
    EntityId otherEntity = 0;
};

struct SnapshotEntity {
    EntityId id = 0;
    BodyState body{};
    PhysicalProperties baselinePhysicalProperties{};
    float fuel = 0.0F;
    float jetStrength = 0.0F;
    VehicleInput currentInput{};
    BodyMotionType motionType = BodyMotionType::Dynamic;
    ControllerType controllerType = ControllerType::Tank;
    bool alive = true;
    InputSequence lastProcessedInput = 0;
    SimulationTick lastContactTick = 0;
};

struct Snapshot {
    SimulationTick tick = 0;
    std::string physicsVersion{};
    std::string configurationIdentity{};
    std::string terrainIdentity{};
    std::vector<SnapshotEntity> entities{};
};

struct SegmentHit {
    bool hit = false;
    EntityId entity = 0; // Zero identifies terrain.
    Vec3f point{};
    Vec3f normal{0.0F, 0.0F, 1.0F};
    float fraction = 1.0F;
};

class FrameScheduler {
public:
    explicit FrameScheduler(std::uint32_t initialPreviousMilliseconds = 0) noexcept;
    std::vector<StepMilliseconds> Advance(std::uint32_t nowMilliseconds) noexcept;
    std::uint32_t PreviousMilliseconds() const noexcept { return previousMilliseconds_; }

private:
    std::uint32_t previousMilliseconds_ = 0;
    bool firstTick_ = true;
};

class World {
public:
    explicit World(PhysicsConfig config, TerrainGrid terrain = {});
    ~World();
    World(const World&) = delete;
    World& operator=(const World&) = delete;
    World(World&&) noexcept;
    World& operator=(World&&) noexcept;

    bool CreateEntity(const EntityDefinition& definition);
    bool DestroyEntity(EntityId id) noexcept;
    bool SetJetShape(EntityId id, const JetShape& shape) noexcept;
    // Lift a newly created vehicle just enough to clear terrain with both its
    // collision mesh and its starting hover target. This changes position
    // only; it does not advance the world or any other entity.
    std::optional<float> ResolveInitialSpawnPose(EntityId id) noexcept;
    bool SetVehicleConfiguration(
        EntityId id,
        ControllerType expectedController,
        const TankConfiguration& configuration);
    bool SubmitInput(EntityId id, const InputEvent& input);
    bool ApplyAuthoritativeMutation(EntityId id, const AuthoritativeMutation& mutation);
    bool RestoreAuthoritativeState(
        EntityId id,
        const BodyState& state,
        const VehicleInput& input,
        InputSequence acknowledgedInput,
        SimulationTick tick,
        std::uint64_t timeMilliseconds) noexcept;
    bool PutBodyToSleep(EntityId id) noexcept;
    bool ApplyLinearImpulse(EntityId id, const Vec3f& impulse) noexcept;
    bool ConsumeFuel(EntityId id, float amount) noexcept;
    bool AddFuel(EntityId id, float amount) noexcept;
    bool StepWorld(SimulationTick tick, StepMilliseconds stepMilliseconds);
    const BodyState* GetBodyState(EntityId id) const noexcept;
    BodyState* GetBodyState(EntityId id) noexcept;
    SegmentHit TraceSegment(
        const Vec3f& start,
        const Vec3f& end,
        EntityId ignoredEntity = 0,
        EntityId secondIgnoredEntity = 0) const noexcept;
    Snapshot WriteSnapshot() const;
    std::vector<TraceEvent> DrainTraceEvents();
    void SetContactCandidateTracing(bool enabled) noexcept { traceContactCandidates_ = enabled; }
    void SetContactRoundRobinSeed(std::uint64_t seed) noexcept { contactRoundRobinSeed_ = seed; }
    const PhysicsConfig& Config() const noexcept { return config_; }
    const TerrainGrid& Terrain() const noexcept { return terrain_; }
    std::uint64_t TimeMilliseconds() const noexcept { return timeMilliseconds_; }

private:
    struct Entity;
    PhysicsConfig config_{};
    TerrainGrid terrain_{};
    // An in-class `{}` initializer makes GCC instantiate unique_ptr<Entity>
    // destruction before the out-of-line Entity definition is visible.
    std::map<EntityId, std::unique_ptr<Entity>> entities_;
    std::vector<TraceEvent> trace_{};
    bool traceContactCandidates_ = false;
    std::uint64_t contactRoundRobinSeed_ = 0;
    SimulationTick currentTick_ = 0;
    std::uint64_t timeMilliseconds_ = 0;
};

} // namespace wulfram::physics
