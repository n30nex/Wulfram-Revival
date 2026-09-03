#pragma once

#include <cstdint>

namespace wulfram::physics {

using SimulationTick = std::uint64_t;
using StepMilliseconds = std::uint32_t;
using InputSequence = std::uint64_t;
using EntityId = std::uint64_t;

struct Vec3f {
    float x = 0.0F;
    float y = 0.0F;
    float z = 0.0F;

    Vec3f& operator+=(const Vec3f& other) noexcept;
    Vec3f& operator-=(const Vec3f& other) noexcept;
    Vec3f& operator*=(float scalar) noexcept;
};

Vec3f operator+(Vec3f left, const Vec3f& right) noexcept;
Vec3f operator-(Vec3f left, const Vec3f& right) noexcept;
Vec3f operator-(const Vec3f& value) noexcept;
Vec3f operator*(Vec3f value, float scalar) noexcept;
Vec3f operator*(float scalar, Vec3f value) noexcept;
Vec3f operator/(Vec3f value, float scalar) noexcept;
float Dot(const Vec3f& left, const Vec3f& right) noexcept;
Vec3f Cross(const Vec3f& left, const Vec3f& right) noexcept;
float LengthSquared(const Vec3f& value) noexcept;
float Length(const Vec3f& value) noexcept;
Vec3f NormalizeOr(const Vec3f& value, const Vec3f& fallback) noexcept;

// The recovered orientation matrix stores doubles while the vectors stored in
// body state are floats. Rows transform local vectors into world vectors.
struct Matrix3d {
    double elements[9] = {
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0.0, 0.0, 1.0,
    };

    static Matrix3d Identity() noexcept;
    static Matrix3d FromEulerAngles(const Vec3f& radians) noexcept;
    Vec3f Transform(const Vec3f& value) const noexcept;
    Vec3f TransformTranspose(const Vec3f& value) const noexcept;
};

struct PhysicalProperties {
    float mass = 1.0F;
    Vec3f inertia{1.0F, 1.0F, 1.0F};
    float friction = 0.4F;
    float linearDrag = 0.2F;
    float angularDrag = 2.0F;
};

struct BodyState {
    Vec3f position{};
    Vec3f linearVelocity{};
    Vec3f linearAcceleration{};
    Vec3f eulerRadians{};
    Vec3f angularVelocity{};
    Vec3f angularAcceleration{};
    Matrix3d orientation{};
    float mass = 1.0F;
    Vec3f inertia{1.0F, 1.0F, 1.0F};
    float activeFriction = 0.4F;
    float activeLinearDrag = 0.2F;
    float angularDrag = 2.0F;
    std::uint32_t legacyTypeCode = 5;
    bool preGravityAccelerationIsSignificant = false;
    bool dampingEnabled = true;
    bool velocityOnlyMotion = false;
    double settlingContactThreshold = 0.0;
};

Vec3f RotateAxis(Vec3f value, int axis, float radians) noexcept;
Vec3f LocalToWorldEulerXYZ(Vec3f value, const Vec3f& euler) noexcept;
Vec3f WorldToLocalEulerZYX(Vec3f value, const Vec3f& euler) noexcept;
Vec3f ExtractEuler(const Matrix3d& orientation) noexcept;
void IntegrateLinear(BodyState& body, double seconds) noexcept;
void IntegrateAngular(BodyState& body, double seconds) noexcept;
Vec3f PointVelocity(const BodyState& body, const Vec3f& worldPoint) noexcept;

} // namespace wulfram::physics
