#include "wulfram/physics/physics.hpp"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <utility>
#include <vector>

namespace {

using namespace wulfram::physics;

bool NearlyEqual(float left, float right, float tolerance = 1.0e-4F) {
    return std::fabs(left - right) <= tolerance;
}

float FloatFromBits(std::uint32_t bits) {
    float value = 0.0F;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
}

[[noreturn]] void Fail(const char* message) {
    std::fprintf(stderr, "%s\n", message);
    std::exit(1);
}

void Require(bool condition, const char* message) {
    if (!condition) {
        Fail(message);
    }
}

TerrainGrid LevelTerrain(float height = 0.0F) {
    return TerrainGrid(4, 4, 10.0F, 10.0F, std::vector<float>(16, height), "level-v1");
}

CollisionShape BoxShape(Vec3f halfExtents = {1.0F, 1.0F, 1.0F}) {
    std::vector<Vec3f> vertices = {
        {-halfExtents.x, -halfExtents.y, -halfExtents.z},
        { halfExtents.x, -halfExtents.y, -halfExtents.z},
        { halfExtents.x,  halfExtents.y, -halfExtents.z},
        {-halfExtents.x,  halfExtents.y, -halfExtents.z},
        {-halfExtents.x, -halfExtents.y,  halfExtents.z},
        { halfExtents.x, -halfExtents.y,  halfExtents.z},
        { halfExtents.x,  halfExtents.y,  halfExtents.z},
        {-halfExtents.x,  halfExtents.y,  halfExtents.z},
    };
    const std::vector<std::vector<std::uint32_t>> faces = {
        {0, 3, 2, 1}, {4, 5, 6, 7}, {0, 1, 5, 4},
        {1, 2, 6, 5}, {2, 3, 7, 6}, {3, 0, 4, 7},
    };
    return CollisionShape::FromMesh(std::move(vertices), faces, "box-v1");
}

EntityDefinition TankDefinition(EntityId id, Vec3f position, CollisionShape shape = {}) {
    EntityDefinition definition{};
    definition.id = id;
    definition.initialState.position = position;
    definition.initialState.legacyTypeCode = 0;
    definition.baselinePhysicalProperties.mass = 1000.0F;
    definition.baselinePhysicalProperties.inertia = {1000.0F, 1000.0F, 1000.0F};
    definition.baselinePhysicalProperties.friction = 0.4F;
    definition.baselinePhysicalProperties.linearDrag = 0.0F;
    definition.baselinePhysicalProperties.angularDrag = 0.0F;
    definition.collisionShape = std::move(shape);
    return definition;
}

EntityDefinition StaticDefinition(EntityId id, Vec3f position, CollisionShape shape) {
    EntityDefinition definition = TankDefinition(id, position, std::move(shape));
    definition.motionType = BodyMotionType::Static;
    definition.controllerType = ControllerType::None;
    definition.baselinePhysicalProperties.friction = 1.0F;
    return definition;
}

void TestRecoveredMath() {
    const Matrix3d identity = Matrix3d::FromEulerAngles({});
    const Vec3f input{1.25F, -2.5F, 9.0F};
    const Vec3f transformed = identity.Transform(input);
    Require(transformed.x == input.x && transformed.y == input.y && transformed.z == input.z,
        "recovered double-matrix/float-vector operation failed");
}

void TestAuthenticTankCollisionAsset() {
    const char* path = WULFRAM_PHYSICS_COLLISION_ROOT "/tank_1_s";
    std::ifstream stream(path, std::ios::binary);
    Require(stream.good(), "authentic Tank collision asset fixture is unavailable");
    const std::vector<std::uint8_t> bytes{
        std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
    CollisionShape shape{};
    Require(DecodeLegacyCollisionShape(bytes.data(), bytes.size(), shape, "tank_1_s"),
        "authentic Tank collision asset did not decode");
    Require(shape.vertices.size() == 19 && shape.triangles.size() == 29,
        "decoded Tank collision mesh does not match the recovered Wulfram II asset");
    Require(shape.hierarchy.size() == 15,
        "decoded Tank collision hierarchy does not match the recovered Wulfram II asset");
    Require(shape.hierarchy.front().negativeChild == 1 &&
            shape.hierarchy.front().positiveChild == -1 &&
            shape.hierarchy.front().triangles.size() == 2,
        "decoded Tank collision hierarchy root is incorrect");
    Require(shape.hierarchy[3].positiveChild == 4 &&
            shape.hierarchy[3].negativeChild == 6 &&
            shape.hierarchy[4].triangles.front() == 18,
        "decoded Tank hierarchy was not remapped to original runtime depth-first order");
    const auto& rootBounds = shape.hierarchy.front();
    Require(
        NearlyEqual(rootBounds.boundsCenter.x,
            (shape.boundsMinimum.x + shape.boundsMaximum.x) * 0.5F) &&
        NearlyEqual(rootBounds.boundsCenter.y,
            (shape.boundsMinimum.y + shape.boundsMaximum.y) * 0.5F) &&
        NearlyEqual(rootBounds.boundsCenter.z,
            (shape.boundsMinimum.z + shape.boundsMaximum.z) * 0.5F) &&
        rootBounds.boundsRadius > 0.0F,
        "decoded Tank hierarchy root did not retain the compiled subtree bounds");
    const PhysicalProperties properties = DeriveTankPhysicalProperties(
        shape, 6700.0F, 0.4F, 0.2F, 2.0F);
    Require(properties.mass > 3000000.0F && properties.mass < 3500000.0F,
        "asset-derived Tank mass is outside the recovered range");
    Require(properties.inertia.x > 300000000.0F && properties.inertia.z > 1000000000.0F,
        "asset-derived product-squared Tank inertia is incorrect");
}

void TestScheduler() {
    FrameScheduler scheduler(60);
    Require(scheduler.Advance(100) == std::vector<StepMilliseconds>{40},
        "first scheduler tick must force 40 ms");
    Require(scheduler.Advance(100) == std::vector<StepMilliseconds>{0},
        "zero elapsed time must still dispatch one zero-duration substep");
    Require(scheduler.Advance(211) == std::vector<StepMilliseconds>({55, 56}),
        "scheduler must assign integer remainder to final substep");
    Require(scheduler.Advance(1000) == std::vector<StepMilliseconds>({110, 110, 110, 110, 110}),
        "scheduler must cap elapsed duration at 550 ms and five substeps");
}

void TestTerrainParity() {
    std::vector<float> heights(9, 0.0F);
    heights[1 * 3 + 1] = 10.0F;
    const TerrainGrid terrain(3, 3, 10.0F, 10.0F, heights, "parity");
    const TerrainHit first = terrain.Evaluate(2.0F, 8.0F);
    const TerrainHit second = terrain.Evaluate(12.0F, 18.0F);
    Require(first.cellX == 0 && first.cellY == 0 && first.triangle == 1,
        "checkerboard terrain selected the wrong first-cell triangle");
    Require(second.cellX == 1 && second.cellY == 1,
        "terrain grid selected the wrong cell");
    Require(first.normal.z > 0.0F && second.normal.z > 0.0F,
        "terrain normals must use the recovered upward winding");

    // Third-trace probe 0 at frame 0. Keep the real cell coordinates because
    // the selected-triangle helper's plane-offset rounding is translation
    // sensitive. The original returns 0x3FEC489E here; normalizing and solving
    // the plane in float rounds the height three ULPs lower.
    std::vector<float> traceHeights(14 * 55, 0.0F);
    traceHeights[12 * 55 + 53] = FloatFromBits(0x3CAE6213U);
    traceHeights[12 * 55 + 54] = FloatFromBits(0x3D5F30E8U);
    traceHeights[13 * 55 + 53] = FloatFromBits(0x415D40B9U);
    traceHeights[13 * 55 + 54] = FloatFromBits(0x41291F71U);
    const TerrainGrid traceTerrain(
        14,
        55,
        43.75F,
        43.75F,
        std::move(traceHeights),
        "third-trace-terrain-precision");
    const TerrainHit traceHit = traceTerrain.Evaluate(531.1064453125F, 2358.15283203125F);
    Require(traceHit.cellX == 12 && traceHit.cellY == 53 && traceHit.triangle == 1,
        "third-trace terrain regression selected the wrong triangle");
    Require(traceHit.point.z == 1.845966100692749F,
        "terrain plane evaluation introduced an early float-rounding boundary");

    // Third-trace probe 3 at frame 1138 lies on the float coordinate 568.75.
    // The original cell mapper's stored reciprocal produces 12.999999860...
    // in x87 and truncates it to cell 12 without an intervening float store.
    const TerrainGrid boundaryTerrain(
        16,
        56,
        43.75F,
        43.75F,
        std::vector<float>(16 * 56, 0.0F),
        "third-trace-cell-boundary");
    const TerrainHit boundaryHit = boundaryTerrain.Evaluate(568.75F, 2367.243896484375F);
    Require(boundaryHit.cellX == 12 && boundaryHit.cellY == 54,
        "terrain cell mapping rounded the reciprocal product before integer conversion");
}

void TestInitialSpawnPoseIsFinalizedWithoutStepping() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.maximumAltitude = 4.0;
    World world(config, LevelTerrain(10.0F));
    EntityDefinition definition = TankDefinition(
        1, {15.0F, 15.0F, 5.0F}, BoxShape());
    definition.jetStrength = 0.5F;
    for (JetShapePoint& point : definition.jetShape.points) {
        point.localPoint = {};
    }
    Require(world.CreateEntity(definition), "could not create spawn-pose Tank");

    const std::optional<float> lift = world.ResolveInitialSpawnPose(1);
    Require(lift.has_value() && NearlyEqual(*lift, 7.0F),
        "spawn pose did not honor the larger starting-hover clearance");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr && NearlyEqual(body->position.x, 15.0F) &&
            NearlyEqual(body->position.y, 15.0F) &&
            NearlyEqual(body->position.z, 12.0F),
        "spawn pose changed the wrong body components");
    Require(world.WriteSnapshot().tick == 0,
        "spawn-pose finalization advanced the authoritative world");

    const std::optional<float> repeated = world.ResolveInitialSpawnPose(1);
    Require(repeated.has_value() && NearlyEqual(*repeated, 0.0F),
        "spawn-pose finalization was not idempotent");
}

void TestTimeWeightedFreeFlight() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    config.tank.jetResponseCoefficient = 0.0;
    World world(config);
    Require(world.CreateEntity(TankDefinition(1, {})), "could not create free-flight Tank");
    InputEvent input{};
    input.sequence = 1;
    input.targetTick = 1;
    input.timeMilliseconds = 20;
    input.controls.move = 1.0F;
    input.controls.jet = 1.0F;
    Require(world.SubmitInput(1, input), "could not submit input event");
    Require(world.StepWorld(1, 40), "free-flight world step failed");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr, "free-flight body disappeared");
    Require(NearlyEqual(body->linearVelocity.x, 1.7F, 1.0e-3F),
        "time-weighted move input did not produce the recovered half-window acceleration");
    Require(NearlyEqual(body->position.x, 0.034F, 1.0e-3F),
        "constant-acceleration free-flight integration is incorrect");
    const Snapshot snapshot = world.WriteSnapshot();
    Require(snapshot.entities.size() == 1 && snapshot.entities[0].lastProcessedInput == 1,
        "snapshot did not acknowledge the processed input sequence");
}

void TestRecoveredLinearIntegrationPrecision() {
    // Third trace, frame 9: the 3 ms step crosses a float boundary if the
    // acceleration product is rounded to double before adding velocity.
    BodyState body{};
    body.position = {525.0F, 2362.5F, 12.0966424942017F};
    body.linearVelocity = {0.0F, 0.0F, 2.08434367179871F};
    body.linearAcceleration = {0.0F, 0.0F, 12.873428344727F};
    body.activeLinearDrag = 1.50000309944153F;
    body.dampingEnabled = true;
    IntegrateLinear(body, 0.003);
    Require(body.position.z == 12.1029396057129F,
        "constant-acceleration position integration lost the recovered multiply-add boundary");
    Require(body.linearVelocity.z == 2.11358428001404F,
        "constant-acceleration velocity integration lost the recovered multiply-add boundary");
}

void TestRecoveredAngularIntegrationPrecision() {
    // Clean terrain trace, frame 17: IntegrateOrientationSubstep keeps the
    // drag-adjusted acceleration multiply-add in x87 until the angular
    // velocity component is stored back to float.
    BodyState body{};
    body.orientation = Matrix3d::Identity();
    body.angularVelocity = {
        8.775125024840236e-05F,
        -1.281083882531675e-06F,
        0.0F,
    };
    body.angularAcceleration = {
        0.040327414870262146F,
        -0.00032451748847961426F,
        0.0F,
    };
    body.angularDrag = 2.0F;
    body.dampingEnabled = true;
    IntegrateAngular(body, 0.002);
    Require(body.angularVelocity.x == 0.00016805507766548544F,
        "angular integration lost the recovered X multiply-add boundary");
    Require(body.angularVelocity.y == -1.9249946490162984e-06F,
        "angular integration lost the recovered Y multiply-add boundary");
}

void TestRecoveredUphillPropulsion() {
    constexpr float slopeX = 0.456222F;
    constexpr float slopeY = 0.11854F;
    std::vector<float> heights{};
    heights.reserve(16);
    for (int x = 0; x < 4; ++x) {
        for (int y = 0; y < 4; ++y) {
            heights.push_back(slopeX * static_cast<float>(x * 10) +
                slopeY * static_cast<float>(y * 10));
        }
    }
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, TerrainGrid(4, 4, 10.0F, 10.0F, heights, "uphill-propulsion"));
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 30.0F});
    definition.initialState.eulerRadians = {
        6.118171691894531F, 5.952646732330322F, 0.6287727952003479F};
    definition.initialState.orientation =
        Matrix3d::FromEulerAngles(definition.initialState.eulerRadians);
    definition.initialInput.move = 0.5188146829605103F;
    definition.initialInput.jet = 0.8239997625350952F;
    definition.jetShape = TankRedJetShape();
    definition.fuel = 33000.0F;
    Require(world.CreateEntity(definition), "could not create uphill-propulsion Tank");
    Require(world.StepWorld(1, 1), "uphill-propulsion world step failed");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr, "uphill-propulsion Tank disappeared");
    Require(NearlyEqual(body->linearVelocity.x, 0.02711F, 2.0e-4F) &&
            NearlyEqual(body->linearVelocity.y, 0.022812F, 2.0e-4F),
        "uphill propulsion did not preserve the sine-initialized slope divisor");
}

void TestHoverTrace() {
    PhysicsConfig config = DefaultPhysicsConfig();
    World world(config, LevelTerrain(0.1F));
    Require(world.CreateEntity(TankDefinition(1, {15.0F, 15.0F, 5.0F})),
        "could not create hover Tank");
    InputEvent input{};
    input.sequence = 1;
    input.targetTick = 1;
    input.controls.jet = 0.8F;
    Require(world.SubmitInput(1, input), "could not submit hover input");
    Require(world.StepWorld(1, 40), "hover world step failed");
    int probes = 0;
    int hoverOutputs = 0;
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        if (event.type == TraceEventType::Probe) {
            ++probes;
            const double recoveredClearance =
                static_cast<double>(event.point.z) - static_cast<double>(event.value.z);
            Require(event.scalar0 == recoveredClearance,
                "hover clearance was rounded to float before double storage");
        }
        hoverOutputs += event.type == TraceEventType::HoverOutput ? 1 : 0;
    }
    Require(probes == 4 && hoverOutputs == 1,
        "hover diagnostics must report four authentic probes and one combined output");
}

void TestRecoveredMovingTankHoverNormalization() {
    // Steady-state Shift-turn capture frame 4949. The original Tank adds its
    // post-model-load 0x411D048F collision-height global to maxAltitude as a
    // double. The earlier portable radius constant is dormant at zero speed,
    // but changes the speed-dependent hover blend while moving.
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.maximumAltitude = 12.0;
    config.tank.maximumSpeedHeightPickup = 3.5;
    config.tank.jetResponseCoefficient = 1.3000030517578125;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 13.671433448791504F});
    definition.initialState.linearVelocity = {
        36.14908218383789F,
        38.13343811035156F,
        0.8488797545433044F,
    };
    definition.initialState.angularVelocity = {
        0.1560898721218109F,
        -0.03824513778090477F,
        -0.5273340940475464F,
    };
    definition.initialState.eulerRadians = {
        0.1678704023361206F,
        0.044942717999219894F,
        0.6274799704551697F,
    };
    definition.initialState.orientation.elements[0] = 0.808689534664154;
    definition.initialState.orientation.elements[1] = -0.5727752447128296;
    definition.initialState.orientation.elements[2] = 0.13395315408706665;
    definition.initialState.orientation.elements[3] = 0.5865118503570557;
    definition.initialState.orientation.elements[4] = 0.8025320768356323;
    definition.initialState.orientation.elements[5] = -0.10924897342920303;
    definition.initialState.orientation.elements[6] = -0.0449274405837059;
    definition.initialState.orientation.elements[7] = 0.16691504418849945;
    definition.initialState.orientation.elements[8] = 0.9849513173103333;
    definition.baselinePhysicalProperties.mass = 3249950.0F;
    definition.baselinePhysicalProperties.inertia = {
        346565920.0F,
        683264512.0F,
        4644288000.0F,
    };
    definition.baselinePhysicalProperties.friction = 0.4000000059604645F;
    definition.baselinePhysicalProperties.linearDrag = 0.20000000298023224F;
    definition.baselinePhysicalProperties.angularDrag = 2.0F;
    definition.jetShape.points = {{
        {{6.101959228515625F, -4.3457794189453125F, -1.3294830322265625F}, {0.0F, 0.0F, -1.0F}, false},
        {{6.101959228515625F, 4.3457794189453125F, -1.3294830322265625F}, {0.0F, 0.0F, -1.0F}, false},
        {{-6.101959228515625F, -4.3457794189453125F, -1.3294830322265625F}, {0.0F, 0.0F, -1.0F}, false},
        {{-6.101959228515625F, 4.3457794189453125F, -1.3294830322265625F}, {0.0F, 0.0F, -1.0F}, false},
    }};
    definition.initialInput.turn = 1.0F;
    definition.initialInput.move = 1.0F;
    definition.initialInput.jet = 0.8240000009536743F;
    Require(world.CreateEntity(definition), "could not create captured moving-hover Tank");
    Require(world.StepWorld(4949, 6), "captured moving-hover step failed");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr, "captured moving-hover Tank disappeared");
    Require(NearlyEqual(body->linearVelocity.z, 0.9053651094436646F, 1.0e-6F),
        "moving Tank hover normalization changed recovered vertical velocity");
    Require(NearlyEqual(body->angularVelocity.x, 0.13603909313678741F, 1.0e-6F) &&
            NearlyEqual(body->angularVelocity.y, -0.037029869854450226F, 1.0e-6F),
        "moving Tank hover normalization changed recovered pitch/roll velocity");
}

void TestSupportedJumpIsAdditiveAndEdgeTriggered() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    config.tank.jumpVelocity = 200.0;
    config.tank.jumpFuelCost = 6000.0;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 5.0F});
    definition.initialState.linearVelocity = {5.0F, -3.0F, 10.0F};
    definition.fuel = 33000.0F;
    Require(world.CreateEntity(definition), "could not create jump Tank");

    InputEvent press{};
    press.sequence = 1;
    press.targetTick = 1;
    press.controls.jump = 1.0F;
    Require(world.SubmitInput(1, press), "could not submit jump press");
    Require(world.StepWorld(1, 0), "supported jump step failed");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr, "jump Tank disappeared");
    Require(
        NearlyEqual(body->linearVelocity.x, 5.0F) &&
        NearlyEqual(body->linearVelocity.y, -3.0F) &&
        NearlyEqual(body->linearVelocity.z, 210.0F, 1.0e-3F),
        "jump replaced existing velocity instead of adding its impulse");
    Require(Length(body->angularVelocity) < 1.0e-4F,
        "equal level support introduced artificial jump torque");

    const Snapshot firstSnapshot = world.WriteSnapshot();
    Require(NearlyEqual(firstSnapshot.entities[0].fuel, 27000.0F),
        "accepted jump did not charge the provisional one-shot fuel cost");
    int acceptedJumps = 0;
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        acceptedJumps += event.type == TraceEventType::JumpAccepted ? 1 : 0;
    }
    Require(acceptedJumps == 1, "supported jump did not emit one acceptance event");

    Require(world.StepWorld(2, 0), "held-jump follow-up step failed");
    InputEvent release{};
    release.sequence = 2;
    release.targetTick = 3;
    release.controls.jump = 0.0F;
    Require(world.SubmitInput(1, release), "could not submit jump release");
    Require(world.StepWorld(3, 0), "jump release step failed");
    InputEvent secondPress = release;
    secondPress.sequence = 3;
    secondPress.targetTick = 4;
    secondPress.controls.jump = 1.0F;
    Require(world.SubmitInput(1, secondPress), "could not submit second jump press");
    Require(world.StepWorld(4, 0), "same-support jump step failed");
    Require(NearlyEqual(world.WriteSnapshot().entities[0].fuel, 27000.0F),
        "same support epoch accepted a second jump");
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        Require(event.type != TraceEventType::JumpAccepted,
            "held/repressed jump emitted a duplicate acceptance event");
    }
}

void TestJumpTapSurvivesOneInputWindow() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 5.0F});
    definition.fuel = 33000.0F;
    Require(world.CreateEntity(definition), "could not create tapped-jump Tank");

    InputEvent press{};
    press.sequence = 1;
    press.targetTick = 1;
    press.timeMilliseconds = 5;
    press.controls.jump = 1.0F;
    InputEvent release = press;
    release.sequence = 2;
    release.timeMilliseconds = 10;
    release.controls.jump = 0.0F;
    Require(world.SubmitInput(1, press), "could not submit tapped jump press");
    Require(world.SubmitInput(1, release), "could not submit tapped jump release");
    Require(world.StepWorld(1, 40), "tapped jump step failed");

    const Snapshot snapshot = world.WriteSnapshot();
    Require(snapshot.entities[0].currentInput.jump == 0.0F,
        "tapped jump did not preserve its final released state");
    Require(snapshot.entities[0].body.linearVelocity.z > 100.0F,
        "press and release inside one input window lost the jump edge");
}

void TestJumpSupportUsesConfiguredHoverRange() {
    PhysicsConfig shortConfig = DefaultPhysicsConfig();
    shortConfig.tank.gravityMagnitude = 0.0;
    shortConfig.tank.maximumAltitude = 1.0;
    World shortWorld(shortConfig, LevelTerrain());
    EntityDefinition shortDefinition = TankDefinition(1, {15.0F, 15.0F, 25.0F});
    shortDefinition.fuel = 33000.0F;
    Require(shortWorld.CreateEntity(shortDefinition), "could not create short-range jump Tank");
    InputEvent press{};
    press.sequence = 1;
    press.targetTick = 1;
    press.controls.jump = 1.0F;
    Require(shortWorld.SubmitInput(1, press), "could not submit short-range jump");
    Require(shortWorld.StepWorld(1, 0), "short-range jump step failed");
    Require(Length(shortWorld.GetBodyState(1)->linearVelocity) == 0.0F,
        "jump used a hidden support distance beyond the configured hover range");

    PhysicsConfig longConfig = shortConfig;
    longConfig.tank.maximumAltitude = 30.0;
    World longWorld(longConfig, LevelTerrain());
    EntityDefinition longDefinition = TankDefinition(1, {15.0F, 15.0F, 25.0F});
    longDefinition.fuel = 33000.0F;
    Require(longWorld.CreateEntity(longDefinition), "could not create long-range jump Tank");
    Require(longWorld.SubmitInput(1, press), "could not submit long-range jump");
    Require(longWorld.StepWorld(1, 0), "long-range jump step failed");
    Require(longWorld.GetBodyState(1)->linearVelocity.z > 100.0F,
        "configured hover range did not extend jump-probe support");
}

void TestJumpUsesOrientationAndUnevenProbeSupport() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 5.0F});
    definition.initialState.eulerRadians = {0.0F, 0.4F, 0.0F};
    definition.initialState.orientation =
        Matrix3d::FromEulerAngles(definition.initialState.eulerRadians);
    definition.fuel = 33000.0F;
    Require(world.CreateEntity(definition), "could not create tilted jump Tank");
    InputEvent press{};
    press.sequence = 1;
    press.targetTick = 1;
    press.controls.jump = 1.0F;
    Require(world.SubmitInput(1, press), "could not submit tilted jump press");
    Require(world.StepWorld(1, 0), "tilted jump step failed");

    const BodyState* body = world.GetBodyState(1);
    const Vec3f expectedDirection = NormalizeOr(
        definition.initialState.orientation.Transform({0.0F, 0.0F, 1.0F}),
        {0.0F, 0.0F, 1.0F});
    Require(body != nullptr && NearlyEqual(
            Dot(body->linearVelocity, expectedDirection),
            static_cast<float>(config.tank.jumpVelocity),
            1.0e-2F),
        "jump impulse did not follow the Tank-local jet axis");
    Require(std::fabs(body->linearVelocity.x) > 1.0F,
        "tilted Tank received a hardcoded world-Z jump");
    Require(Length(body->angularVelocity) > 1.0e-5F,
        "uneven tilted probe support did not produce angular response");
}

void TestJumpCanUseAnotherBodyAsProbeSupport() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain(-100.0F));
    EntityDefinition support = TankDefinition(
        1,
        {15.0F, 15.0F, 0.0F},
        BoxShape({10.0F, 10.0F, 1.0F}));
    Require(world.CreateEntity(support), "could not create dynamic jump support");
    EntityDefinition jumper = TankDefinition(2, {15.0F, 15.0F, 4.0F});
    jumper.fuel = 33000.0F;
    Require(world.CreateEntity(jumper), "could not create body-supported jump Tank");
    InputEvent press{};
    press.sequence = 1;
    press.targetTick = 1;
    press.controls.jump = 1.0F;
    Require(world.SubmitInput(2, press), "could not submit body-supported jump");
    Require(world.StepWorld(1, 0), "body-supported jump step failed");
    Require(world.GetBodyState(2)->linearVelocity.z > 100.0F,
        "nearby body collision mesh was not accepted as jump-probe support");
}

void TestJumpRejectsMissingSupportAndInsufficientFuel() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    EntityDefinition airborne = TankDefinition(1, {15.0F, 15.0F, 100.0F});
    airborne.fuel = 33000.0F;
    EntityDefinition empty = TankDefinition(2, {15.0F, 15.0F, 5.0F});
    empty.fuel = 5999.0F;
    Require(world.CreateEntity(airborne), "could not create airborne jump Tank");
    Require(world.CreateEntity(empty), "could not create low-fuel jump Tank");
    for (EntityId id : {EntityId{1}, EntityId{2}}) {
        InputEvent press{};
        press.sequence = 1;
        press.targetTick = 1;
        press.controls.jump = 1.0F;
        Require(world.SubmitInput(id, press), "could not submit rejected jump");
    }
    Require(world.StepWorld(1, 0), "rejected-jump step failed");
    Require(Length(world.GetBodyState(1)->linearVelocity) == 0.0F,
        "airborne Tank received a jump impulse");
    Require(Length(world.GetBodyState(2)->linearVelocity) == 0.0F,
        "low-fuel Tank received a jump impulse");
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        Require(event.type != TraceEventType::JumpAccepted,
            "rejected jump emitted an acceptance event");
    }
}

void TestFuelRegenerationIsTimeBasedAndCapped() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    config.tank.fuelRegenerationPerSecond = 350.0;

    World shortStepWorld(config, LevelTerrain());
    EntityDefinition shortStepTank = TankDefinition(1, {15.0F, 15.0F, 100.0F});
    shortStepTank.fuel = 1000.0F;
    Require(shortStepWorld.CreateEntity(shortStepTank),
        "could not create short-step regenerating Tank");
    Require(shortStepWorld.StepWorld(1, 40), "short fuel-regeneration step failed");
    Require(NearlyEqual(shortStepWorld.WriteSnapshot().entities[0].fuel, 1014.0F),
        "40 ms fuel regeneration did not apply the configured per-second rate");

    World longStepWorld(config, LevelTerrain());
    EntityDefinition longStepTank = TankDefinition(2, {15.0F, 15.0F, 100.0F});
    longStepTank.fuel = 1000.0F;
    Require(longStepWorld.CreateEntity(longStepTank),
        "could not create long-step regenerating Tank");
    Require(longStepWorld.StepWorld(1, 100), "long fuel-regeneration step failed");
    Require(NearlyEqual(longStepWorld.WriteSnapshot().entities[0].fuel, 1035.0F),
        "fuel regeneration changed rate with the physics tick duration");

    World cappedWorld(config, LevelTerrain());
    EntityDefinition cappedTank = TankDefinition(3, {15.0F, 15.0F, 100.0F});
    cappedTank.fuel = 32990.0F;
    Require(cappedWorld.CreateEntity(cappedTank),
        "could not create capped regenerating Tank");
    Require(cappedWorld.StepWorld(1, 40), "capped fuel-regeneration step failed");
    Require(NearlyEqual(cappedWorld.WriteSnapshot().entities[0].fuel, 33000.0F),
        "fuel regeneration exceeded the configured maximum fuel");
}

void TestSweptTerrainContact() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 4.0F}, BoxShape());
    definition.collisionShape.samples.clear();
    definition.initialState.linearVelocity.z = -30.0F;
    Require(world.CreateEntity(definition), "could not create contact Tank");
    Require(world.StepWorld(1, 150), "contact world step failed");
    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr && body->position.z > -0.25F,
        "swept contact allowed the body to tunnel through terrain");
    bool contactSeen = false;
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        contactSeen |= event.type == TraceEventType::Contact;
    }
    Require(contactSeen, "hard landing did not produce a feature contact trace");
    const Snapshot snapshot = world.WriteSnapshot();
    Require(snapshot.entities.size() == 1 && snapshot.entities[0].lastContactTick == 1,
        "snapshot did not retain the last native contact tick");
}

void TestShortIntervalSweepKeepsStartCheckpoint() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    EntityDefinition definition = TankDefinition(
        1,
        {15.0F, 15.0F, 1.05F},
        BoxShape());
    definition.collisionShape.samples.clear();
    definition.initialState.linearVelocity.z = -20.0F;
    Require(world.CreateEntity(definition),
        "could not create short-interval contact Tank");
    Require(world.StepWorld(1, 3), "short-interval contact step failed");

    const BodyState* body = world.GetBodyState(1);
    Require(body != nullptr && NearlyEqual(body->position.z, 1.05F, 1.0e-6F),
        "a <=5 ms swept collision must restore the original start checkpoint");

    bool contactSeen = false;
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        if (event.type == TraceEventType::Contact) {
            contactSeen = true;
            Require(std::fabs(event.scalar0 - 0.003) <= 1.0e-12,
                "short-interval fallback did not retain the full event time");
        }
    }
    Require(contactSeen, "short-interval end-pose collision was not reported");
}

void TestPreGravityAccelerationSignificance() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config);
    EntityDefinition definition = TankDefinition(1, {});
    definition.initialState.linearAcceleration = {1.0F, 0.0F, 0.0F};
    Require(world.CreateEntity(definition), "could not create acceleration-significance Tank");
    Require(world.StepWorld(1, 1), "acceleration-significance world step failed");
    Require(world.GetBodyState(1)->preGravityAccelerationIsSignificant,
        "ordered squared acceleration above 0.001 must set the +0xAD significance flag");
    Require(world.StepWorld(2, 1), "zero-acceleration follow-up step failed");
    Require(!world.GetBodyState(1)->preGravityAccelerationIsSignificant,
        "zero pre-gravity acceleration must clear the +0xAD significance flag");
}

void TestContactCandidateTracing() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config, LevelTerrain());
    world.SetContactCandidateTracing(true);
    EntityDefinition definition = TankDefinition(1, {15.0F, 15.0F, 1.01F}, BoxShape());
    definition.collisionShape.samples.clear();
    definition.initialState.linearVelocity.z = -30.0F;
    Require(world.CreateEntity(definition), "could not create candidate-trace Tank");
    Require(world.StepWorld(1, 1), "candidate-trace world step failed");
    bool contactSeen = false;
    bool candidateSeen = false;
    Vec3f firstCandidatePoint{};
    Vec3f selectedContactPoint{};
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        if (event.type == TraceEventType::ContactCandidate) {
            if (!candidateSeen) {
                firstCandidatePoint = event.point;
            }
            candidateSeen = true;
        }
        if (event.type == TraceEventType::Contact) {
            contactSeen = true;
            selectedContactPoint = event.point;
        }
    }
    Require(contactSeen && candidateSeen,
        "enabled candidate tracing must retain both the selected contact and its candidates");
    Require(NearlyEqual(selectedContactPoint.x, firstCandidatePoint.x) &&
            NearlyEqual(selectedContactPoint.y, firstCandidatePoint.y) &&
            NearlyEqual(selectedContactPoint.z, firstCandidatePoint.z),
        "selected terrain contact must use the first recovered narrow-phase candidate");
}

void TestAuthoritativeCorrectionGate() {
    PhysicsConfig config = DefaultPhysicsConfig();
    World world(config, LevelTerrain());
    Require(world.CreateEntity(TankDefinition(1, {5.0F, 5.0F, 5.0F}, BoxShape())),
        "could not create correction Tank");
    AuthoritativeMutation rejected{};
    rejected.position = Vec3f{5.0F, 5.0F, -2.0F};
    Require(!world.ApplyAuthoritativeMutation(1, rejected),
        "below-terrain authoritative pose should have rolled back");
    Require(NearlyEqual(world.GetBodyState(1)->position.z, 5.0F),
        "rejected authoritative pose did not restore the snapshot");
    AuthoritativeMutation accepted{};
    accepted.position = Vec3f{8.0F, 8.0F, 6.0F};
    accepted.acknowledgedInput = 7;
    Require(world.ApplyAuthoritativeMutation(1, accepted),
        "clear authoritative pose should have been accepted");
    Require(NearlyEqual(world.GetBodyState(1)->position.z, 6.0F),
        "accepted authoritative pose was not committed");
}

void TestStaticBodyDoesNotAdvance() {
    PhysicsConfig config = DefaultPhysicsConfig();
    World world(config);
    EntityDefinition definition = StaticDefinition(2, {3.0F, 4.0F, 5.0F}, BoxShape());
    definition.initialState.linearVelocity = {100.0F, -50.0F, 25.0F};
    definition.initialState.angularVelocity = {1.0F, 2.0F, 3.0F};
    Require(world.CreateEntity(definition), "could not create static body");
    InputEvent input{};
    input.sequence = 1;
    Require(!world.SubmitInput(2, input), "static body accepted Tank input");
    Require(world.StepWorld(1, 250), "static-body world step failed");
    const BodyState* body = world.GetBodyState(2);
    Require(body != nullptr &&
            NearlyEqual(body->position.x, 3.0F) &&
            NearlyEqual(body->position.y, 4.0F) &&
            NearlyEqual(body->position.z, 5.0F),
        "static body advanced during the world step");
}

void TestSweptDynamicStaticContact() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config);
    EntityDefinition moving = TankDefinition(1, {-5.0F, 0.0F, 0.0F}, BoxShape());
    moving.controllerType = ControllerType::None;
    moving.initialState.linearVelocity = {20.0F, 0.0F, 0.0F};
    Require(world.CreateEntity(moving), "could not create dynamic collision body");
    Require(world.CreateEntity(StaticDefinition(2, {0.0F, 0.0F, 0.0F}, BoxShape())),
        "could not create static collision body");

    Require(world.StepWorld(1, 250), "dynamic/static collision step failed");
    const BodyState* dynamicBody = world.GetBodyState(1);
    const BodyState* staticBody = world.GetBodyState(2);
    Require(dynamicBody != nullptr && dynamicBody->position.x < -1.0F,
        "dynamic body crossed the static collider");
    Require(staticBody != nullptr && NearlyEqual(staticBody->position.x, 0.0F),
        "contact response moved the static collider");
    bool contactSeen = false;
    for (const TraceEvent& event : world.DrainTraceEvents()) {
        if (event.type == TraceEventType::Contact && event.entity == 1 && event.otherEntity == 2) {
            contactSeen = true;
        }
    }
    Require(contactSeen, "dynamic/static contact trace did not identify the static partner");
}

void TestCorrectionGateSeesStaticBody() {
    PhysicsConfig config = DefaultPhysicsConfig();
    config.tank.gravityMagnitude = 0.0;
    World world(config);
    Require(world.CreateEntity(TankDefinition(1, {-5.0F, 0.0F, 0.0F}, BoxShape())),
        "could not create correction-gate dynamic body");
    Require(world.CreateEntity(StaticDefinition(2, {0.0F, 0.0F, 0.0F}, BoxShape())),
        "could not create correction-gate static body");
    AuthoritativeMutation mutation{};
    mutation.position = Vec3f{0.0F, 0.0F, 0.0F};
    Require(!world.ApplyAuthoritativeMutation(1, mutation),
        "authoritative correction overlapping a static body was accepted");
    Require(NearlyEqual(world.GetBodyState(1)->position.x, -5.0F),
        "rejected static-body correction did not restore the dynamic pose");
}

void TestStableEntityOrder() {
    World world(DefaultPhysicsConfig());
    Require(world.CreateEntity(TankDefinition(9, {})), "could not create entity 9");
    Require(world.CreateEntity(TankDefinition(2, {})), "could not create entity 2");
    const Snapshot snapshot = world.WriteSnapshot();
    Require(snapshot.entities.size() == 2 && snapshot.entities[0].id == 2 && snapshot.entities[1].id == 9,
        "snapshot entity order must be stable and independent of allocation addresses");
}

} // namespace

int main() {
    TestRecoveredMath();
    TestAuthenticTankCollisionAsset();
    TestScheduler();
    TestTerrainParity();
    TestInitialSpawnPoseIsFinalizedWithoutStepping();
    TestTimeWeightedFreeFlight();
    TestRecoveredLinearIntegrationPrecision();
    TestRecoveredAngularIntegrationPrecision();
    TestRecoveredUphillPropulsion();
    TestHoverTrace();
    TestRecoveredMovingTankHoverNormalization();
    TestSupportedJumpIsAdditiveAndEdgeTriggered();
    TestJumpTapSurvivesOneInputWindow();
    TestJumpSupportUsesConfiguredHoverRange();
    TestJumpUsesOrientationAndUnevenProbeSupport();
    TestJumpCanUseAnotherBodyAsProbeSupport();
    TestJumpRejectsMissingSupportAndInsufficientFuel();
    TestFuelRegenerationIsTimeBasedAndCapped();
    TestSweptTerrainContact();
    TestShortIntervalSweepKeepsStartCheckpoint();
    TestPreGravityAccelerationSignificance();
    TestContactCandidateTracing();
    TestAuthoritativeCorrectionGate();
    TestStaticBodyDoesNotAdvance();
    TestSweptDynamicStaticContact();
    TestCorrectionGateSeesStaticBody();
    TestStableEntityOrder();
    return 0;
}
