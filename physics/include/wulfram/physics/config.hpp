#pragma once

#include "wulfram/physics/types.hpp"

#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace wulfram::physics {

struct UniformCurve {
    std::vector<float> samples{};
    float Evaluate(float input) const noexcept;
};

struct FeedbackSettings {
    float absoluteMaximumError = 1.0F;
    float errorMultiplier = 1.0F;
    float absoluteMaximumPrime = 1.0F;
    float primeMultiplier = 1.0F;
    float absoluteOutput = 1.0F;
    bool useDamper = false;
};

struct FeedbackTable {
    FeedbackSettings settings{};
    UniformCurve raw{};
    UniformCurve correction{};
    UniformCurve errorWeight{};
    UniformCurve primeWeight{};
    float Evaluate(float error, float prime) const noexcept;
};

struct JetMiscSettings {
    float maximumHorizontalSpeed = 55.0F;
    float jetAbateMaximum = 1.5F;
    float tiltErrorMagnitude = 1.0F;
    float rollErrorMagnitude = 1.0F;
    float tiltMaximum = 0.84F;
    float rollMaximum = 0.90F;
    float rollTurnFactor = 0.20F;
    float rollStrafeFactor = 0.10F;
    float baseReaction = 0.0055F;
    float slopeReaction = 0.003F;
    bool degenerateOnSlope = true;
};

struct JetProfile {
    FeedbackTable fastReaction{};
    FeedbackTable slowReaction{};
    UniformCurve speed{};
    UniformCurve height{};
    UniformCurve heightConsider{};
    UniformCurve abate{};
    UniformCurve speedRoll{};
    JetMiscSettings misc{};
};

struct JetShapePoint {
    Vec3f localPoint{};
    Vec3f configuredDirection{0.0F, 0.0F, -1.0F};
    bool legacyFlag = false;
};

struct JetShape {
    std::array<JetShapePoint, 4> points{};
};

struct TankConfiguration {
    double turnAdjust = 4.5;
    double moveAdjust = 85.0;
    double moveBackwardAdjust = 85.0;
    double strafeAdjust = 69.7;
    double maximumVelocity = 80.0;
    double lowFuelLevel = 2000.0;
    double maximumAltitude = 3.25;
    double maximumSpeedHeightPickup = 0.0;
    double gravityPercent = 1.0;
    double gravityMagnitude = 160.0;
    double minimumJetStrength = 0.05;
    double jetResponseCoefficient = 1.3;
    double maximumFuel = 33000.0;
    // Provisional gameplay values recovered from the Wulfram 1.0
    // server_params file. jumpVelocity is currently interpreted as the
    // additive speed delivered by one accepted jump. jumpAcceleration is
    // retained alongside it for later original-server calibration; the
    // client binary does not prove how that second value was applied.
    double jumpVelocity = 200.0;
    double jumpAcceleration = 20.0;
    double jumpFuelCost = 6000.0;
    // Wulfram 1.0 server_params tank_fuel_regen. The server value is treated
    // as fuel units per second so regeneration remains independent of the
    // fixed physics tick duration.
    double fuelRegenerationPerSecond = 350.0;
    float density = 6700.0F;
    float baselineFriction = 0.4F;
    float baselineLinearDrag = 0.2F;
    float angularDrag = 2.0F;
    float activeJetFriction = 0.1F;
    float accelerationLimitScale = 1.0F;
    JetProfile jetProfile{};
};

struct PhysicsConfig {
    TankConfiguration tank{};
    TankConfiguration scout{};
    std::string semanticVersion = "0.7.0-dev";
    std::string configurationIdentity = "wulfram-recovered-vehicle-defaults-v1";
};

JetProfile CurrentTankJetProfile();
JetProfile CurrentMedicJetProfile();
JetShape TankRedJetShape() noexcept;
JetShape TankBlueJetShape() noexcept;
JetShape MedicRedJetShape() noexcept;
JetShape MedicBlueJetShape() noexcept;
PhysicsConfig DefaultPhysicsConfig();

} // namespace wulfram::physics
