#include "wulfram/physics/types.hpp"

#include <algorithm>
#include <cmath>

namespace wulfram::physics {
namespace {

constexpr float kTwoPi = 6.2831855F;

float WrapAngle(float value) noexcept {
    if (value > 20000.0F || value < -20000.0F) {
        return 0.0F;
    }
    while (value < 0.0F) {
        value += kTwoPi;
    }
    while (value > kTwoPi) {
        value -= kTwoPi;
    }
    return value;
}

Matrix3d BuildAxisAngleDeltaMatrix(const Vec3f& axisAngle) noexcept {
    const float length = static_cast<float>(std::sqrt(
        static_cast<double>(axisAngle.x) * axisAngle.x +
        static_cast<double>(axisAngle.y) * axisAngle.y +
        static_cast<double>(axisAngle.z) * axisAngle.z));
    if (length <= 1.0e-5F) {
        return Matrix3d::Identity();
    }

    const float inverseLength = static_cast<float>(1.0 / static_cast<double>(length));
    const float x = axisAngle.x * inverseLength;
    const float y = axisAngle.y * inverseLength;
    const float z = axisAngle.z * inverseLength;
    const float cosine = static_cast<float>(std::cos(static_cast<double>(length)));
    const float sine = static_cast<float>(std::sin(static_cast<double>(length)));
    // BuildAxisAngleRotationMatrix (0x004F1150) keeps the Rodrigues products
    // in x87 precision (with a few explicit double temporaries) and rounds
    // only each completed matrix component to float.
    const double delta = 1.0 - static_cast<double>(cosine);
    const double xd = x;
    const double yd = y;
    const double zd = z;
    const double cd = cosine;
    const double sd = sine;
    Matrix3d result{};
    result.elements[0] = static_cast<float>(xd * xd * delta + cd);
    result.elements[1] = static_cast<float>(xd * yd * delta + zd * sd);
    result.elements[2] = static_cast<float>(xd * zd * delta - yd * sd);
    result.elements[3] = static_cast<float>(yd * xd * delta - zd * sd);
    result.elements[4] = static_cast<float>(yd * yd * delta + cd);
    result.elements[5] = static_cast<float>(yd * zd * delta + xd * sd);
    result.elements[6] = static_cast<float>(zd * xd * delta + yd * sd);
    result.elements[7] = static_cast<float>(zd * yd * delta - xd * sd);
    result.elements[8] = static_cast<float>(zd * zd * delta + cd);
    return result;
}

void ApplyAngularDelta(Matrix3d& matrix, const Matrix3d& rotation) noexcept {
    const float r00 = static_cast<float>(rotation.elements[0]);
    const float r01 = static_cast<float>(rotation.elements[1]);
    const float r02 = static_cast<float>(rotation.elements[2]);
    const float r10 = static_cast<float>(rotation.elements[3]);
    const float r11 = static_cast<float>(rotation.elements[4]);
    const float r12 = static_cast<float>(rotation.elements[5]);
    const float r20 = static_cast<float>(rotation.elements[6]);
    const float r21 = static_cast<float>(rotation.elements[7]);
    const float r22 = static_cast<float>(rotation.elements[8]);
    const float n00 = static_cast<float>(r02 * matrix.elements[2] + r00 * matrix.elements[0] + r01 * matrix.elements[1]);
    const float n01 = static_cast<float>(r12 * matrix.elements[2] + r10 * matrix.elements[0] + r11 * matrix.elements[1]);
    const float n02 = static_cast<float>(r22 * matrix.elements[2] + r20 * matrix.elements[0] + r21 * matrix.elements[1]);
    const float n10 = static_cast<float>(r02 * matrix.elements[5] + r00 * matrix.elements[3] + r01 * matrix.elements[4]);
    const float n11 = static_cast<float>(r12 * matrix.elements[5] + r10 * matrix.elements[3] + r11 * matrix.elements[4]);
    const float n12 = static_cast<float>(r22 * matrix.elements[5] + r20 * matrix.elements[3] + r21 * matrix.elements[4]);
    const float n20 = static_cast<float>(r02 * matrix.elements[8] + r00 * matrix.elements[6] + r01 * matrix.elements[7]);
    const float n21 = static_cast<float>(r12 * matrix.elements[8] + r10 * matrix.elements[6] + r11 * matrix.elements[7]);
    const float n22 = static_cast<float>(r22 * matrix.elements[8] + r20 * matrix.elements[6] + r21 * matrix.elements[7]);
    matrix.elements[0] = n00;
    matrix.elements[1] = n01;
    matrix.elements[2] = n02;
    matrix.elements[3] = n10;
    matrix.elements[4] = n11;
    matrix.elements[5] = n12;
    matrix.elements[6] = n20;
    matrix.elements[7] = n21;
    matrix.elements[8] = n22;
}

} // namespace

Vec3f& Vec3f::operator+=(const Vec3f& other) noexcept {
    x += other.x;
    y += other.y;
    z += other.z;
    return *this;
}

Vec3f& Vec3f::operator-=(const Vec3f& other) noexcept {
    x -= other.x;
    y -= other.y;
    z -= other.z;
    return *this;
}

Vec3f& Vec3f::operator*=(float scalar) noexcept {
    x *= scalar;
    y *= scalar;
    z *= scalar;
    return *this;
}

Vec3f operator+(Vec3f left, const Vec3f& right) noexcept { return left += right; }
Vec3f operator-(Vec3f left, const Vec3f& right) noexcept { return left -= right; }
Vec3f operator-(const Vec3f& value) noexcept { return {-value.x, -value.y, -value.z}; }
Vec3f operator*(Vec3f value, float scalar) noexcept { return value *= scalar; }
Vec3f operator*(float scalar, Vec3f value) noexcept { return value *= scalar; }
Vec3f operator/(Vec3f value, float scalar) noexcept { return value *= 1.0F / scalar; }

float Dot(const Vec3f& left, const Vec3f& right) noexcept {
    return (left.x * right.x + left.y * right.y) + left.z * right.z;
}

Vec3f Cross(const Vec3f& left, const Vec3f& right) noexcept {
    return {
        left.y * right.z - left.z * right.y,
        left.z * right.x - left.x * right.z,
        left.x * right.y - left.y * right.x,
    };
}

float LengthSquared(const Vec3f& value) noexcept { return Dot(value, value); }
float Length(const Vec3f& value) noexcept { return std::sqrt(LengthSquared(value)); }

Vec3f NormalizeOr(const Vec3f& value, const Vec3f& fallback) noexcept {
    const float length = Length(value);
    return length > 1.0e-8F ? value / length : fallback;
}

Matrix3d Matrix3d::Identity() noexcept { return {}; }

Matrix3d Matrix3d::FromEulerAngles(const Vec3f& radians) noexcept {
    // Preserve the recovered helper's float trig results promoted into the
    // stored double matrix expressions.
    const float c0f = static_cast<float>(std::cos(static_cast<double>(radians.x)));
    const float s0f = static_cast<float>(std::sin(static_cast<double>(radians.x)));
    const float c1f = static_cast<float>(std::cos(static_cast<double>(radians.y)));
    const float s1f = static_cast<float>(std::sin(static_cast<double>(radians.y)));
    const float c2f = static_cast<float>(std::cos(static_cast<double>(radians.z)));
    const float s2f = static_cast<float>(std::sin(static_cast<double>(radians.z)));
    const double c0 = c0f;
    const double s0 = s0f;
    const double c1 = c1f;
    const double s1 = s1f;
    const double c2 = c2f;
    const double s2 = s2f;
    Matrix3d result{};
    result.elements[0] = c2 * c1;
    result.elements[1] = ((c2 * s1) * s0) - (s2 * c0);
    result.elements[2] = (s2 * s0) + ((c2 * c0) * s1);
    result.elements[3] = s2 * c1;
    result.elements[4] = ((s1 * s0) * s2) + (c2 * c0);
    result.elements[5] = ((s1 * c0) * s2) - (c2 * s0);
    result.elements[6] = -s1;
    result.elements[7] = c1 * s0;
    result.elements[8] = c0 * c1;
    return result;
}

Vec3f Matrix3d::Transform(const Vec3f& value) const noexcept {
    return {
        static_cast<float>((static_cast<double>(value.x) * elements[0] + static_cast<double>(value.y) * elements[1]) + static_cast<double>(value.z) * elements[2]),
        static_cast<float>((static_cast<double>(value.x) * elements[3] + static_cast<double>(value.y) * elements[4]) + static_cast<double>(value.z) * elements[5]),
        static_cast<float>((static_cast<double>(value.x) * elements[6] + static_cast<double>(value.y) * elements[7]) + static_cast<double>(value.z) * elements[8]),
    };
}

Vec3f Matrix3d::TransformTranspose(const Vec3f& value) const noexcept {
    return {
        static_cast<float>((static_cast<double>(value.x) * elements[0] + static_cast<double>(value.y) * elements[3]) + static_cast<double>(value.z) * elements[6]),
        static_cast<float>((static_cast<double>(value.x) * elements[1] + static_cast<double>(value.y) * elements[4]) + static_cast<double>(value.z) * elements[7]),
        static_cast<float>((static_cast<double>(value.x) * elements[2] + static_cast<double>(value.y) * elements[5]) + static_cast<double>(value.z) * elements[8]),
    };
}

Vec3f RotateAxis(Vec3f value, int axis, float radians) noexcept {
    const float sine = std::sin(radians);
    const float cosine = std::cos(radians);
    switch (axis) {
    case 1: return {value.x, value.y * cosine - value.z * sine, value.y * sine + value.z * cosine};
    case 2: return {value.x * cosine + value.z * sine, value.y, value.z * cosine - value.x * sine};
    case 3: return {value.x * cosine - value.y * sine, value.y * cosine + value.x * sine, value.z};
    default: return value;
    }
}

Vec3f LocalToWorldEulerXYZ(Vec3f value, const Vec3f& euler) noexcept {
    value = RotateAxis(value, 1, euler.x);
    value = RotateAxis(value, 2, euler.y);
    return RotateAxis(value, 3, euler.z);
}

Vec3f WorldToLocalEulerZYX(Vec3f value, const Vec3f& euler) noexcept {
    value = RotateAxis(value, 3, -euler.z);
    value = RotateAxis(value, 2, -euler.y);
    return RotateAxis(value, 1, -euler.x);
}

Vec3f ExtractEuler(const Matrix3d& orientation) noexcept {
    const double horizontal = std::sqrt(
        orientation.elements[0] * orientation.elements[0] +
        orientation.elements[3] * orientation.elements[3]);
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    if (horizontal > 1.9073486328125e-6) {
        x = std::atan2(orientation.elements[7], orientation.elements[8]);
        y = std::atan2(-orientation.elements[6], horizontal);
        z = std::atan2(orientation.elements[3], orientation.elements[0]);
    } else {
        x = std::atan2(-orientation.elements[5], orientation.elements[4]);
        y = std::atan2(-orientation.elements[6], horizontal);
    }
    return {WrapAngle(static_cast<float>(x)), WrapAngle(static_cast<float>(y)), WrapAngle(static_cast<float>(z))};
}

void IntegrateLinear(BodyState& body, double seconds) noexcept {
    if (body.velocityOnlyMotion) {
        body.position += body.linearVelocity * static_cast<float>(seconds);
        return;
    }
    Vec3f acceleration = body.linearAcceleration;
    if (body.dampingEnabled) {
        acceleration -= body.linearVelocity * body.activeLinearDrag;
    }
    const Vec3f position = body.position;
    const Vec3f velocity = body.linearVelocity;
    const double halfSecondsSquared = 0.5 * seconds * seconds;
    // IntegrateVectorConstantAcceleration (0x004F10C0) retains each
    // multiply-add in x87 precision until the completed component is stored
    // as float. std::fma prevents MSVC from rounding acceleration*dt to
    // double before adding the stored-float velocity, which is observable on
    // short 3 ms substeps in the third terrain trace.
    body.position = {
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.x), halfSecondsSquared,
            static_cast<double>(velocity.x) * seconds) + position.x),
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.y), halfSecondsSquared,
            static_cast<double>(velocity.y) * seconds) + position.y),
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.z), halfSecondsSquared,
            static_cast<double>(velocity.z) * seconds) + position.z),
    };
    body.linearVelocity = {
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.x), seconds, velocity.x)),
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.y), seconds, velocity.y)),
        static_cast<float>(std::fma(
            static_cast<double>(acceleration.z), seconds, velocity.z)),
    };
}

void IntegrateAngular(BodyState& body, double outerSeconds) noexcept {
    if (outerSeconds <= 0.0) {
        return;
    }
    const double chunk = outerSeconds > 0.08 ? outerSeconds * 0.5 : 0.04;
    double remaining = outerSeconds;
    while (remaining > 0.0) {
        const double seconds = std::min(chunk, remaining);
        remaining -= seconds;
        // IntegrateBodyAngularState (0x004F12C0) multiplies each stored-float
        // angular-velocity component by the double timestep in x87 precision,
        // then stores the completed axis-angle component to float.
        const Vec3f axisAngle{
            static_cast<float>(static_cast<double>(body.angularVelocity.x) * seconds),
            static_cast<float>(static_cast<double>(body.angularVelocity.y) * seconds),
            static_cast<float>(static_cast<double>(body.angularVelocity.z) * seconds),
        };
        ApplyAngularDelta(body.orientation, BuildAxisAngleDeltaMatrix(axisAngle));
        body.eulerRadians = ExtractEuler(body.orientation);
        if (!body.velocityOnlyMotion) {
            Vec3f acceleration = body.angularAcceleration;
            if (body.dampingEnabled) {
                acceleration -= body.angularVelocity * body.angularDrag;
            }
            body.angularVelocity = {
                static_cast<float>(std::fma(
                    static_cast<double>(acceleration.x), seconds, body.angularVelocity.x)),
                static_cast<float>(std::fma(
                    static_cast<double>(acceleration.y), seconds, body.angularVelocity.y)),
                static_cast<float>(std::fma(
                    static_cast<double>(acceleration.z), seconds, body.angularVelocity.z)),
            };
        }
    }
}

Vec3f PointVelocity(const BodyState& body, const Vec3f& worldPoint) noexcept {
    Vec3f result = body.linearVelocity;
    // ComputeBodyWorldPointVelocity (0x004F2940) keeps the speed-squared
    // comparison and each cross-product component in x87 until its final
    // float store.
    const double angularSpeedSquared =
        (static_cast<double>(body.angularVelocity.x) * body.angularVelocity.x +
         static_cast<double>(body.angularVelocity.y) * body.angularVelocity.y) +
        static_cast<double>(body.angularVelocity.z) * body.angularVelocity.z;
    if (angularSpeedSquared > 1.0e-5) {
        const Vec3f angularWorld = body.orientation.Transform(body.angularVelocity);
        const Vec3f leverArm = worldPoint - body.position;
        const Vec3f angularContribution{
            static_cast<float>(
                static_cast<double>(angularWorld.y) * leverArm.z -
                static_cast<double>(angularWorld.z) * leverArm.y),
            static_cast<float>(
                static_cast<double>(angularWorld.z) * leverArm.x -
                static_cast<double>(angularWorld.x) * leverArm.z),
            static_cast<float>(
                static_cast<double>(angularWorld.x) * leverArm.y -
                static_cast<double>(angularWorld.y) * leverArm.x),
        };
        result += angularContribution;
    }
    return result;
}

} // namespace wulfram::physics
