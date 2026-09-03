#include "wulfram/physics/world.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <tuple>
#include <utility>

namespace wulfram::physics {
namespace {

constexpr int kCollisionBucketCount = 30;
constexpr int kMaximumEventsPerStep = 64;
constexpr double kSweepBracketStepSeconds = 0.0025;
constexpr double kSweepFallbackEventAdvanceSeconds = 0.005;
// ApplyTankVehiclePhysics loads this runtime float from 0x005730C4 before
// adding the packet-overwritable Tank maximum altitude. A steady-state
// original-client capture derives the post-model-load value exactly as
// float bits 0x411D048F.
constexpr float kTankCollisionGeometryHeightNormalization = 9.813612937927246F;
// The Scout path is still provisional and retains the prior shared value
// until its distinct model-global consumer is recovered.
constexpr float kProvisionalScoutCollisionGeometryHeightNormalization = 8.527236938476562F;

float ClampControl(float value) noexcept {
    return std::clamp(value, -1.0F, 1.0F);
}

VehicleInput AddScaled(VehicleInput value, const VehicleInput& other, float scale) noexcept {
    value.turn += other.turn * scale;
    value.move += other.move * scale;
    value.strafe += other.strafe * scale;
    value.jet += other.jet * scale;
    value.tilt += other.tilt * scale;
    value.roll += other.roll * scale;
    return value;
}

struct IntegratedInput {
    VehicleInput controls{};
    bool jumpPressed = false;
    InputSequence jumpSequence = 0;
};

IntegratedInput IntegrateInputs(
    std::vector<InputEvent>& events,
    VehicleInput& current,
    InputSequence& lastProcessed,
    SimulationTick tick,
    std::uint64_t startMilliseconds,
    StepMilliseconds durationMilliseconds) {
    const std::uint64_t endMilliseconds = startMilliseconds + durationMilliseconds;
    std::vector<std::size_t> due{};
    for (std::size_t index = 0; index < events.size(); ++index) {
        if (events[index].targetTick <= tick && events[index].timeMilliseconds <= endMilliseconds) {
            due.push_back(index);
        }
    }
    std::stable_sort(due.begin(), due.end(), [&events](std::size_t left, std::size_t right) {
        return std::tie(events[left].timeMilliseconds, events[left].sequence) <
            std::tie(events[right].timeMilliseconds, events[right].sequence);
    });

    VehicleInput area{};
    std::uint64_t cursor = startMilliseconds;
    bool jumpPressed = false;
    InputSequence jumpSequence = 0;
    for (std::size_t index : due) {
        const InputEvent& event = events[index];
        const std::uint64_t eventTime = std::clamp(event.timeMilliseconds, cursor, endMilliseconds);
        area = AddScaled(area, current, static_cast<float>(eventTime - cursor));
        const bool wasJumpPressed = current.jump != 0.0F;
        current = event.controls;
        current.turn = ClampControl(current.turn);
        current.move = ClampControl(current.move);
        current.strafe = ClampControl(current.strafe);
        current.tilt = ClampControl(current.tilt);
        current.roll = ClampControl(current.roll);
        current.jump = current.jump != 0.0F ? 1.0F : 0.0F;
        if (!wasJumpPressed && current.jump != 0.0F && !jumpPressed) {
            // Preserve a tap whose press and release both arrive inside one
            // physics window. Sampling only the final channel value would
            // otherwise lose the discrete jump event.
            jumpPressed = true;
            jumpSequence = event.sequence;
        }
        cursor = eventTime;
        lastProcessed = std::max(lastProcessed, event.sequence);
    }
    area = AddScaled(area, current, static_cast<float>(endMilliseconds - cursor));

    if (!due.empty()) {
        std::vector<bool> remove(events.size(), false);
        for (std::size_t index : due) {
            remove[index] = true;
        }
        std::size_t write = 0;
        for (std::size_t read = 0; read < events.size(); ++read) {
            if (!remove[read]) {
                events[write++] = events[read];
            }
        }
        events.resize(write);
    }

    VehicleInput result = current;
    if (durationMilliseconds != 0) {
        const float inverseDuration = 1.0F / static_cast<float>(durationMilliseconds);
        result.turn = ClampControl(area.turn * inverseDuration);
        result.move = ClampControl(area.move * inverseDuration);
        result.strafe = ClampControl(area.strafe * inverseDuration);
    }
    // The recovered Tank sampler time-averages channels 1-3. Jet, tilt, and
    // explicit roll consume the final value reached in the window.
    result.jet = current.jet;
    result.tilt = current.tilt;
    result.roll = current.roll;
    result.jump = current.jump;
    return {result, jumpPressed, jumpSequence};
}

struct Triangle {
    Vec3f a{};
    Vec3f b{};
    Vec3f c{};
    Vec3f normal{0.0F, 0.0F, 1.0F};
    int feature = 0;
    float planeOffset = 0.0F;
    bool hasStoredPlane = false;
};

float LegacyStoredDot(const Vec3f& left, const Vec3f& right) noexcept {
    // Recovered collision and response helpers form the dot in x87 precision,
    // then store the completed result to a float. Preserve the observed Y+X,
    // then Z evaluation order without rounding the first sum to float.
    return static_cast<float>(
        (static_cast<double>(left.y) * right.y +
         static_cast<double>(left.x) * right.x) +
        static_cast<double>(left.z) * right.z);
}

Vec3f LegacyStoredCross(const Vec3f& left, const Vec3f& right) noexcept {
    // ComputeTriangleNormalUnnormalized (0x004FF9B0) stores the operand
    // differences as floats, but keeps each pair of products and subtraction
    // in x87 precision until the completed component is stored.
    return {
        static_cast<float>(
            static_cast<double>(left.y) * right.z -
            static_cast<double>(left.z) * right.y),
        static_cast<float>(
            static_cast<double>(left.z) * right.x -
            static_cast<double>(left.x) * right.z),
        static_cast<float>(
            static_cast<double>(left.x) * right.y -
            static_cast<double>(left.y) * right.x),
    };
}

float LegacyModelPlaneOffset(const Vec3f& normal, const Vec3f& point) noexcept {
    // FUN_004FFAE0 forms and stores the model-face plane constant as
    // (-nx * px - py * ny) - pz * nz. The stored constant is subsequently
    // reused for every edge endpoint tested against that face.
    return static_cast<float>(
        (-static_cast<double>(normal.x) * point.x -
         static_cast<double>(point.y) * normal.y) -
        static_cast<double>(point.z) * normal.z);
}

float LegacyStoredPlaneDistance(
    const Vec3f& point,
    const Vec3f& normal,
    float planeOffset) noexcept {
    // Endpoint distances in FUN_004FFAE0 retain the products and additions in
    // x87 precision and round only the completed plane equation to float.
    return static_cast<float>(
        ((static_cast<double>(normal.y) * point.y +
          static_cast<double>(normal.x) * point.x) +
         static_cast<double>(normal.z) * point.z) +
        planeOffset);
}

Vec3f NormalizeCollisionPlane(const Vec3f& value) noexcept {
    // FUN_00404350 promotes the stored float components to double for the
    // squared-length/sqrt and division, then rounds each result to float.
    const double x = static_cast<double>(value.x);
    const double y = static_cast<double>(value.y);
    const double z = static_cast<double>(value.z);
    const double length = std::sqrt(x * x + y * y + z * z);
    if (length == 0.0) {
        return value;
    }
    return {
        static_cast<float>(x / length),
        static_cast<float>(y / length),
        static_cast<float>(z / length),
    };
}

std::array<Triangle, 2> TerrainCellTriangles(
    const TerrainGrid& terrain,
    std::int32_t ix,
    std::int32_t iy) noexcept {
    ix = std::clamp(ix, 0, static_cast<std::int32_t>(terrain.CountX()) - 2);
    iy = std::clamp(iy, 0, static_cast<std::int32_t>(terrain.CountY()) - 2);
    const float x0 = ix * terrain.SpacingX();
    const float y0 = iy * terrain.SpacingY();
    const float x1 = x0 + terrain.SpacingX();
    const float y1 = y0 + terrain.SpacingY();
    const Vec3f v00{x0, y0, terrain.Height(static_cast<std::size_t>(ix), static_cast<std::size_t>(iy))};
    const Vec3f v10{x1, y0, terrain.Height(static_cast<std::size_t>(ix + 1), static_cast<std::size_t>(iy))};
    const Vec3f v01{x0, y1, terrain.Height(static_cast<std::size_t>(ix), static_cast<std::size_t>(iy + 1))};
    const Vec3f v11{x1, y1, terrain.Height(static_cast<std::size_t>(ix + 1), static_cast<std::size_t>(iy + 1))};
    std::array<Triangle, 2> triangles{};
    if ((((~ix) ^ iy) & 1) != 0) {
        triangles[0] = {v00, v01, v11, {}, 0};
        triangles[1] = {v10, v00, v11, {}, 1};
    } else {
        triangles[0] = {v00, v01, v10, {}, 0};
        triangles[1] = {v11, v10, v01, {}, 1};
    }
    for (Triangle& triangle : triangles) {
        triangle.normal = NormalizeOr(
            Cross(triangle.a - triangle.b, triangle.c - triangle.a),
            {0.0F, 0.0F, 1.0F});
        if (triangle.normal.z < 0.0F) {
            triangle.normal = -triangle.normal;
        }
    }
    return triangles;
}

Vec3f AddTerrainHeightInLocalSpace(
    const Vec3f& zeroHeightPoint,
    float height,
    const Matrix3d& orientation) noexcept {
    // TestCollisionModelAgainstTerrainGrid (0x005007F0) rounds the three
    // height-axis matrix coefficients to floats before applying terrain height.
    const float zAxisX = static_cast<float>(orientation.elements[6]);
    const float zAxisY = static_cast<float>(orientation.elements[7]);
    const float zAxisZ = static_cast<float>(orientation.elements[8]);
    return {
        static_cast<float>(static_cast<double>(zeroHeightPoint.x) +
            static_cast<double>(height) * zAxisX),
        static_cast<float>(static_cast<double>(zeroHeightPoint.y) +
            static_cast<double>(height) * zAxisY),
        static_cast<float>(static_cast<double>(zeroHeightPoint.z) +
            static_cast<double>(height) * zAxisZ),
    };
}

std::array<Triangle, 2> LocalTerrainCellTrianglesForCollision(
    const BodyState& body,
    const TerrainGrid& terrain,
    std::int32_t minimumCellX,
    std::int32_t minimumCellY,
    std::int32_t cellX,
    std::int32_t cellY) noexcept {
    const Matrix3d& orientation = body.orientation;
    const Vec3f xStep{
        static_cast<float>(static_cast<double>(terrain.SpacingX()) * orientation.elements[0]),
        static_cast<float>(static_cast<double>(terrain.SpacingX()) * orientation.elements[1]),
        static_cast<float>(static_cast<double>(terrain.SpacingX()) * orientation.elements[2]),
    };
    const Vec3f yStep{
        static_cast<float>(static_cast<double>(terrain.SpacingY()) * orientation.elements[3]),
        static_cast<float>(static_cast<double>(terrain.SpacingY()) * orientation.elements[4]),
        static_cast<float>(static_cast<double>(terrain.SpacingY()) * orientation.elements[5]),
    };
    const float relativeX =
        static_cast<float>(minimumCellX) * terrain.SpacingX() - body.position.x;
    const float relativeY =
        static_cast<float>(minimumCellY) * terrain.SpacingY() - body.position.y;
    const float relativeZ = -body.position.z;
    Vec3f row0{
        static_cast<float>(static_cast<double>(relativeZ) * orientation.elements[6] +
            static_cast<double>(relativeX) * orientation.elements[0] +
            static_cast<double>(relativeY) * orientation.elements[3] - yStep.x),
        static_cast<float>(static_cast<double>(relativeZ) * orientation.elements[7] +
            static_cast<double>(relativeY) * orientation.elements[4] +
            static_cast<double>(relativeX) * orientation.elements[1] - yStep.y),
        static_cast<float>(static_cast<double>(relativeZ) * orientation.elements[8] +
            static_cast<double>(relativeY) * orientation.elements[5] +
            static_cast<double>(relativeX) * orientation.elements[2] - yStep.z),
    };
    row0 += yStep;
    Vec3f row1 = row0 + yStep;
    for (std::int32_t y = minimumCellY; y < cellY; ++y) {
        row0 = row1;
        row1 += yStep;
    }
    for (std::int32_t x = minimumCellX; x < cellX; ++x) {
        row0 += xStep;
        row1 += xStep;
    }
    const Vec3f nextRow0 = row0 + xStep;
    const Vec3f nextRow1 = row1 + xStep;
    const Vec3f v00 = AddTerrainHeightInLocalSpace(
        row0, terrain.Height(static_cast<std::size_t>(cellX), static_cast<std::size_t>(cellY)), orientation);
    const Vec3f v10 = AddTerrainHeightInLocalSpace(
        nextRow0, terrain.Height(static_cast<std::size_t>(cellX + 1), static_cast<std::size_t>(cellY)), orientation);
    const Vec3f v01 = AddTerrainHeightInLocalSpace(
        row1, terrain.Height(static_cast<std::size_t>(cellX), static_cast<std::size_t>(cellY + 1)), orientation);
    const Vec3f v11 = AddTerrainHeightInLocalSpace(
        nextRow1, terrain.Height(static_cast<std::size_t>(cellX + 1), static_cast<std::size_t>(cellY + 1)), orientation);
    std::array<Triangle, 2> triangles{};
    if ((((~cellX) ^ cellY) & 1) != 0) {
        // TestCollisionModelAgainstTerrainGrid (0x005007F0) visits the
        // v00-v01-v11 half before v10-v00-v11 on odd-parity cells. Retain
        // those exact argument orders because FUN_004FFAE0 also walks the
        // resulting triangle edges in a fixed order.
        triangles[0] = {v00, v01, v11, {}, 0};
        triangles[1] = {v10, v00, v11, {}, 1};
    } else {
        triangles[0] = {v00, v01, v10, {}, 0};
        triangles[1] = {v11, v10, v01, {}, 1};
    }
    for (Triangle& triangle : triangles) {
        triangle.normal = NormalizeCollisionPlane(
            LegacyStoredCross(triangle.a - triangle.b, triangle.c - triangle.a));
        triangle.planeOffset = LegacyModelPlaneOffset(triangle.normal, triangle.a);
        triangle.hasStoredPlane = true;
    }
    return triangles;
}

bool PointInsideTriangle(const Vec3f& point, const Triangle& triangle) noexcept {
    const Vec3f c0 = LegacyStoredCross(triangle.b - triangle.a, point - triangle.a);
    const Vec3f c1 = LegacyStoredCross(triangle.c - triangle.b, point - triangle.b);
    const Vec3f c2 = LegacyStoredCross(triangle.a - triangle.c, point - triangle.c);
    const float d0 = LegacyStoredDot(c0, triangle.normal);
    const float d1 = LegacyStoredDot(c1, triangle.normal);
    const float d2 = LegacyStoredDot(c2, triangle.normal);
    // FUN_004FB890 tests the oriented sign bits. Call sites supply both model
    // and terrain windings, so accept a consistently oriented point without
    // introducing a geometric epsilon.
    return (d0 >= 0.0F && d1 >= 0.0F && d2 >= 0.0F) ||
        (d0 <= 0.0F && d1 <= 0.0F && d2 <= 0.0F);
}

bool SegmentPlaneTriangleIntersection(
    const Vec3f& start,
    const Vec3f& end,
    const Triangle& triangle,
    Vec3f& pointOut) noexcept {
    const float startDistance = triangle.hasStoredPlane
        ? LegacyStoredPlaneDistance(start, triangle.normal, triangle.planeOffset)
        : LegacyStoredDot(start - triangle.a, triangle.normal);
    const float endDistance = triangle.hasStoredPlane
        ? LegacyStoredPlaneDistance(end, triangle.normal, triangle.planeOffset)
        : LegacyStoredDot(end - triangle.a, triangle.normal);
    // FUN_00500260 clips only a negative-side endpoint against a nonnegative
    // endpoint. Coplanar and positive-to-zero edges do not independently
    // produce candidates.
    if (!((startDistance < 0.0F && endDistance >= 0.0F) ||
          (endDistance < 0.0F && startDistance >= 0.0F))) {
        return false;
    }
    const float denominator = startDistance - endDistance;
    if (denominator == 0.0F) {
        return false;
    }
    const float fraction = startDistance / denominator;
    if (fraction < 0.0F || fraction > 1.0F) {
        return false;
    }
    const Vec3f point = start + (end - start) * fraction;
    if (!PointInsideTriangle(point, triangle)) {
        return false;
    }
    pointOut = point;
    return true;
}

bool TriangleIntersection(const Triangle& model, const Triangle& terrain, Vec3f& pointOut) noexcept {
    const Vec3f modelVertices[3] = {model.a, model.b, model.c};
    const Vec3f terrainVertices[3] = {terrain.a, terrain.b, terrain.c};
    // FUN_005000E0 first tests terrain-edge/model-face intersections produced
    // by FUN_00500260, then falls through to the model-edge/terrain-face tests
    // in FUN_004FFEE0. Within either family the recovered edge order is v0-v1,
    // closing v0-v2, then v1-v2. This family order is observable when both
    // triangles have an intersecting edge at the selected collision pose.
    constexpr int edgeStarts[3] = {0, 2, 1};
    constexpr int edgeEnds[3] = {1, 0, 2};
    for (int order = 0; order < 3; ++order) {
        if (SegmentPlaneTriangleIntersection(
                terrainVertices[edgeStarts[order]], terrainVertices[edgeEnds[order]], model, pointOut)) {
            return true;
        }
    }
    for (int order = 0; order < 3; ++order) {
        if (SegmentPlaneTriangleIntersection(
                modelVertices[edgeStarts[order]], modelVertices[edgeEnds[order]], terrain, pointOut)) {
            return true;
        }
    }
    return false;
}

struct ContactFeature {
    Vec3f point{};
    Vec3f responseNormal{0.0F, 0.0F, 1.0F};
    Vec3f alternateResponseNormal{0.0F, 0.0F, 1.0F};
    Vec3f reportedNormal{0.0F, 0.0F, -1.0F};
    int modelFeature = -1;
    int terrainFeature = -1;
};

struct ContactCandidate {
    ContactFeature contact{};
    // 0: an edge of the moving model crossed the terrain triangle plane.
    // 1: an edge of the terrain triangle crossed the moving model triangle plane.
    int edgeOwner = -1;
    int edgeIndex = -1;
    int generationIndex = -1;
};

float ShapeRadius(const CollisionShape& shape) noexcept;

std::vector<Vec3f> TransformVertices(const BodyState& body, const CollisionShape& shape) {
    std::vector<Vec3f> result{};
    result.reserve(shape.vertices.size());
    for (const Vec3f& vertex : shape.vertices) {
        result.push_back(body.orientation.Transform(vertex) + body.position);
    }
    return result;
}

Triangle ModelTriangle(const CollisionShape& shape, std::size_t modelIndex) noexcept {
    const auto& indices = shape.triangles[modelIndex];
    Triangle triangle{
        shape.vertices[indices[0]], shape.vertices[indices[1]], shape.vertices[indices[2]], {},
        static_cast<int>(modelIndex)};
    triangle.normal = NormalizeCollisionPlane(LegacyStoredCross(
        triangle.b - triangle.a,
        triangle.c - triangle.a));
    triangle.planeOffset = LegacyModelPlaneOffset(triangle.normal, triangle.a);
    triangle.hasStoredPlane = true;
    return triangle;
}

struct StaticBodySurface {
    EntityId id = 0;
    BodyState body{};
    const CollisionShape* shape = nullptr;
    float friction = 1.0F;
};

Triangle WorldModelTriangle(
    const BodyState& body,
    const CollisionShape& shape,
    std::size_t modelIndex) noexcept {
    Triangle triangle = ModelTriangle(shape, modelIndex);
    triangle.a = body.orientation.Transform(triangle.a) + body.position;
    triangle.b = body.orientation.Transform(triangle.b) + body.position;
    triangle.c = body.orientation.Transform(triangle.c) + body.position;
    triangle.normal = NormalizeCollisionPlane(body.orientation.Transform(triangle.normal));
    triangle.planeOffset = LegacyModelPlaneOffset(triangle.normal, triangle.a);
    triangle.hasStoredPlane = true;
    return triangle;
}

bool BoundsOverlap(
    const std::vector<Vec3f>& left,
    const std::vector<Vec3f>& right) noexcept {
    if (left.empty() || right.empty()) {
        return false;
    }
    Vec3f leftMinimum = left.front();
    Vec3f leftMaximum = left.front();
    Vec3f rightMinimum = right.front();
    Vec3f rightMaximum = right.front();
    const auto expand = [](const std::vector<Vec3f>& vertices, Vec3f& minimum, Vec3f& maximum) {
        for (const Vec3f& vertex : vertices) {
            minimum.x = std::min(minimum.x, vertex.x);
            minimum.y = std::min(minimum.y, vertex.y);
            minimum.z = std::min(minimum.z, vertex.z);
            maximum.x = std::max(maximum.x, vertex.x);
            maximum.y = std::max(maximum.y, vertex.y);
            maximum.z = std::max(maximum.z, vertex.z);
        }
    };
    expand(left, leftMinimum, leftMaximum);
    expand(right, rightMinimum, rightMaximum);
    return leftMinimum.x <= rightMaximum.x && leftMaximum.x >= rightMinimum.x &&
        leftMinimum.y <= rightMaximum.y && leftMaximum.y >= rightMinimum.y &&
        leftMinimum.z <= rightMaximum.z && leftMaximum.z >= rightMinimum.z;
}

bool FindModelModelContact(
    const BodyState& dynamicBody,
    const CollisionShape& dynamicShape,
    const BodyState& staticBody,
    const CollisionShape& staticShape,
    ContactFeature& contact) {
    if (dynamicShape.vertices.empty() || dynamicShape.triangles.empty() ||
        staticShape.vertices.empty() || staticShape.triangles.empty()) {
        return false;
    }
    const std::vector<Vec3f> dynamicVertices = TransformVertices(dynamicBody, dynamicShape);
    const std::vector<Vec3f> staticVertices = TransformVertices(staticBody, staticShape);
    if (!BoundsOverlap(dynamicVertices, staticVertices)) {
        return false;
    }

    for (std::size_t dynamicIndex = 0;
         dynamicIndex < dynamicShape.triangles.size();
         ++dynamicIndex) {
        const Triangle dynamicTriangle = WorldModelTriangle(
            dynamicBody, dynamicShape, dynamicIndex);
        for (std::size_t staticIndex = 0;
             staticIndex < staticShape.triangles.size();
             ++staticIndex) {
            const Triangle staticTriangle = WorldModelTriangle(
                staticBody, staticShape, staticIndex);
            Vec3f point{};
            if (!TriangleIntersection(dynamicTriangle, staticTriangle, point)) {
                continue;
            }
            contact = {
                point,
                -dynamicTriangle.normal,
                staticTriangle.normal,
                dynamicTriangle.normal,
                static_cast<int>(dynamicIndex),
                static_cast<int>(staticIndex),
            };
            return true;
        }
    }
    return false;
}

bool FindTriangleContactCandidate(
    const BodyState& body,
    const CollisionShape& shape,
    std::size_t modelIndex,
    const Triangle& localTerrain,
    int terrainFeature,
    ContactCandidate& candidate) noexcept {
    const Triangle modelTriangle = ModelTriangle(shape, modelIndex);
    const Vec3f modelVertices[3] = {modelTriangle.a, modelTriangle.b, modelTriangle.c};
    const Vec3f terrainVertices[3] = {localTerrain.a, localTerrain.b, localTerrain.c};
    const Vec3f modelWorldNormal = body.orientation.Transform(modelTriangle.normal);
    const Vec3f terrainWorldNormal = body.orientation.Transform(localTerrain.normal);
    constexpr int edgeStarts[3] = {0, 2, 1};
    constexpr int edgeEnds[3] = {1, 0, 2};
    for (int order = 0; order < 3; ++order) {
        const int edgeIndex = edgeStarts[order];
        Vec3f point{};
        if (SegmentPlaneTriangleIntersection(
                terrainVertices[edgeIndex], terrainVertices[edgeEnds[order]], modelTriangle, point)) {
            candidate = {{
                body.orientation.Transform(point) + body.position,
                -modelWorldNormal,
                terrainWorldNormal,
                modelWorldNormal,
                static_cast<int>(modelIndex),
                terrainFeature,
            }, 1, edgeIndex, -1};
            return true;
        }
    }
    for (int order = 0; order < 3; ++order) {
        const int edgeIndex = edgeStarts[order];
        Vec3f point{};
        if (SegmentPlaneTriangleIntersection(
                modelVertices[edgeIndex], modelVertices[edgeEnds[order]], localTerrain, point)) {
            candidate = {{
                body.orientation.Transform(point) + body.position,
                -modelWorldNormal,
                terrainWorldNormal,
                modelWorldNormal,
                static_cast<int>(modelIndex),
                terrainFeature,
            }, 0, edgeIndex, -1};
            return true;
        }
    }
    return false;
}

bool OppositeStoredFloatSigns(float left, float right) noexcept {
    std::uint32_t leftBits = 0;
    std::uint32_t rightBits = 0;
    std::memcpy(&leftBits, &left, sizeof(leftBits));
    std::memcpy(&rightBits, &right, sizeof(rightBits));
    return ((leftBits ^ rightBits) & 0x80000000U) != 0;
}

Vec3f InterpolatePlaneCrossing(
    const Vec3f& start,
    const Vec3f& end,
    float startDistance,
    float endDistance) noexcept {
    // FUN_00500260 stores the fraction and each completed component to float.
    const float fraction = static_cast<float>(
        static_cast<double>(startDistance) /
        (static_cast<double>(startDistance) - static_cast<double>(endDistance)));
    return {
        static_cast<float>(
            static_cast<double>(start.x) +
            (static_cast<double>(end.x) - start.x) * fraction),
        static_cast<float>(
            static_cast<double>(start.y) +
            (static_cast<double>(end.y) - start.y) * fraction),
        static_cast<float>(
            static_cast<double>(start.z) +
            (static_cast<double>(end.z) - start.z) * fraction),
    };
}

bool HierarchyNodeBoundsCrossTerrainPlane(
    const CollisionShape::HierarchyNode& node,
    const Triangle& localTerrain) noexcept {
    // FUN_004FFAE0 first rejects a subtree whose bounding sphere misses the
    // terrain plane, then checks the AABB corner farthest toward the opposite
    // side. Only a plane crossing the conservative subtree bounds can reach
    // this node's face list or children.
    const float centerDistance = LegacyStoredPlaneDistance(
        node.boundsCenter, localTerrain.normal, localTerrain.planeOffset);
    if (node.boundsRadius - std::abs(centerDistance) < 0.0F) return false;
    const auto opposingOffset = [centerDistance](float normal, float extent) {
        const bool negative = std::signbit(normal) == std::signbit(centerDistance);
        return std::copysign(extent, negative ? -1.0F : 1.0F);
    };
    const Vec3f opposingCorner{
        node.boundsCenter.x + opposingOffset(localTerrain.normal.x, node.boundsExtents.x),
        node.boundsCenter.y + opposingOffset(localTerrain.normal.y, node.boundsExtents.y),
        node.boundsCenter.z + opposingOffset(localTerrain.normal.z, node.boundsExtents.z),
    };
    const float cornerDistance = LegacyStoredPlaneDistance(
        opposingCorner, localTerrain.normal, localTerrain.planeOffset);
    return OppositeStoredFloatSigns(centerDistance, cornerDistance);
}

bool FindNodeContactCandidate(
    const BodyState& body,
    const CollisionShape& shape,
    const CollisionShape::HierarchyNode& node,
    const Triangle& localTerrain,
    int terrainFeature,
    const float distances[3],
    ContactCandidate& candidate) noexcept {
    const Vec3f terrainVertices[3] = {localTerrain.a, localTerrain.b, localTerrain.c};
    std::array<Vec3f, 3> crossings{};
    std::size_t crossingCount = 0;
    constexpr int edgeStarts[3] = {0, 0, 1};
    constexpr int edgeEnds[3] = {1, 2, 2};
    for (int edge = 0; edge < 3; ++edge) {
        const int start = edgeStarts[edge];
        const int end = edgeEnds[edge];
        if (OppositeStoredFloatSigns(distances[start], distances[end])) {
            crossings[crossingCount++] = InterpolatePlaneCrossing(
                terrainVertices[start], terrainVertices[end], distances[start], distances[end]);
        }
    }

    for (const std::uint32_t triangleIndex : node.triangles) {
        if (triangleIndex >= shape.triangles.size()) continue;
        const Triangle modelTriangle = ModelTriangle(shape, triangleIndex);
        const Vec3f modelWorldNormal = body.orientation.Transform(modelTriangle.normal);
        const Vec3f terrainWorldNormal = body.orientation.Transform(localTerrain.normal);
        for (std::size_t crossing = 0; crossing < crossingCount; ++crossing) {
            if (PointInsideTriangle(crossings[crossing], modelTriangle)) {
                candidate = {{
                    body.orientation.Transform(crossings[crossing]) + body.position,
                    -modelWorldNormal,
                    terrainWorldNormal,
                    modelWorldNormal,
                    static_cast<int>(triangleIndex),
                    terrainFeature,
                }, 1, static_cast<int>(crossing), -1};
                return true;
            }
        }
        const Vec3f modelVertices[3] = {
            modelTriangle.a, modelTriangle.b, modelTriangle.c};
        constexpr int modelEdgeStarts[3] = {0, 2, 1};
        constexpr int modelEdgeEnds[3] = {1, 0, 2};
        for (int edge = 0; edge < 3; ++edge) {
            Vec3f point{};
            if (SegmentPlaneTriangleIntersection(
                    modelVertices[modelEdgeStarts[edge]],
                    modelVertices[modelEdgeEnds[edge]],
                    localTerrain,
                    point)) {
                candidate = {{
                    body.orientation.Transform(point) + body.position,
                    -modelWorldNormal,
                    terrainWorldNormal,
                    modelWorldNormal,
                    static_cast<int>(triangleIndex),
                    terrainFeature,
                }, 0, modelEdgeStarts[edge], -1};
                return true;
            }
        }
    }
    return false;
}

void EnumerateNodeContactCandidates(
    const BodyState& body,
    const CollisionShape& shape,
    const CollisionShape::HierarchyNode& node,
    const Triangle& localTerrain,
    int terrainFeature,
    const float distances[3],
    std::vector<ContactCandidate>& candidates) noexcept {
    const Vec3f terrainVertices[3] = {localTerrain.a, localTerrain.b, localTerrain.c};
    std::array<Vec3f, 3> crossings{};
    std::size_t crossingCount = 0;
    constexpr int terrainEdgeStarts[3] = {0, 0, 1};
    constexpr int terrainEdgeEnds[3] = {1, 2, 2};
    for (int edge = 0; edge < 3; ++edge) {
        const int start = terrainEdgeStarts[edge];
        const int end = terrainEdgeEnds[edge];
        if (OppositeStoredFloatSigns(distances[start], distances[end])) {
            crossings[crossingCount++] = InterpolatePlaneCrossing(
                terrainVertices[start], terrainVertices[end], distances[start], distances[end]);
        }
    }

    for (const std::uint32_t triangleIndex : node.triangles) {
        if (triangleIndex >= shape.triangles.size()) continue;
        const Triangle modelTriangle = ModelTriangle(shape, triangleIndex);
        const Vec3f modelWorldNormal = body.orientation.Transform(modelTriangle.normal);
        const Vec3f terrainWorldNormal = body.orientation.Transform(localTerrain.normal);
        bool appended = false;
        for (std::size_t crossing = 0; crossing < crossingCount; ++crossing) {
            if (!PointInsideTriangle(crossings[crossing], modelTriangle)) continue;
            candidates.push_back({{
                body.orientation.Transform(crossings[crossing]) + body.position,
                -modelWorldNormal,
                terrainWorldNormal,
                modelWorldNormal,
                static_cast<int>(triangleIndex),
                terrainFeature,
            }, 1, static_cast<int>(crossing), -1});
            appended = true;
            break;
        }
        if (appended) continue;

        const Vec3f modelVertices[3] = {
            modelTriangle.a, modelTriangle.b, modelTriangle.c};
        constexpr int modelEdgeStarts[3] = {0, 2, 1};
        constexpr int modelEdgeEnds[3] = {1, 0, 2};
        for (int edge = 0; edge < 3; ++edge) {
            Vec3f point{};
            if (!SegmentPlaneTriangleIntersection(
                    modelVertices[modelEdgeStarts[edge]],
                    modelVertices[modelEdgeEnds[edge]],
                    localTerrain,
                    point)) {
                continue;
            }
            candidates.push_back({{
                body.orientation.Transform(point) + body.position,
                -modelWorldNormal,
                terrainWorldNormal,
                modelWorldNormal,
                static_cast<int>(triangleIndex),
                terrainFeature,
            }, 0, modelEdgeStarts[edge], -1});
            break;
        }
    }
}

bool FindHierarchyContactCandidate(
    const BodyState& body,
    const CollisionShape& shape,
    const Triangle& localTerrain,
    int terrainFeature,
    std::int32_t nodeIndex,
    std::size_t depth,
    ContactCandidate& candidate) noexcept {
    if (nodeIndex < 0 || static_cast<std::size_t>(nodeIndex) >= shape.hierarchy.size() ||
        depth >= shape.hierarchy.size()) {
        return false;
    }
    const CollisionShape::HierarchyNode& node = shape.hierarchy[static_cast<std::size_t>(nodeIndex)];
    if (node.triangles.empty()) return false;
    if (!HierarchyNodeBoundsCrossTerrainPlane(node, localTerrain)) return false;

    const Triangle splittingTriangle = ModelTriangle(shape, node.triangles.front());
    const float distances[3] = {
        LegacyStoredPlaneDistance(
            localTerrain.a, splittingTriangle.normal, splittingTriangle.planeOffset),
        LegacyStoredPlaneDistance(
            localTerrain.b, splittingTriangle.normal, splittingTriangle.planeOffset),
        LegacyStoredPlaneDistance(
            localTerrain.c, splittingTriangle.normal, splittingTriangle.planeOffset),
    };
    const bool firstNegative = std::signbit(distances[0]);
    const bool straddles = firstNegative != std::signbit(distances[1]) ||
        firstNegative != std::signbit(distances[2]);
    if (!straddles) {
        return FindHierarchyContactCandidate(
            body,
            shape,
            localTerrain,
            terrainFeature,
            // A wholly negative terrain face follows the negative subtree;
            // hook-set-6 constraint arrays confirm that this path reaches the
            // later model-face candidates appended by the original traversal.
            firstNegative ? node.negativeChild : node.positiveChild,
            depth + 1,
            candidate);
    }

    if (FindNodeContactCandidate(
            body, shape, node, localTerrain, terrainFeature, distances, candidate)) {
        return true;
    }
    // FUN_00500260 tests the compiled child at +0x32 before +0x30 when a
    // terrain triangle crosses the current hierarchy plane.
    return FindHierarchyContactCandidate(
               body, shape, localTerrain, terrainFeature, node.negativeChild, depth + 1, candidate) ||
        FindHierarchyContactCandidate(
               body, shape, localTerrain, terrainFeature, node.positiveChild, depth + 1, candidate);
}

void EnumerateHierarchyContactCandidates(
    const BodyState& body,
    const CollisionShape& shape,
    const Triangle& localTerrain,
    int terrainFeature,
    std::int32_t nodeIndex,
    std::size_t depth,
    std::vector<ContactCandidate>& candidates) noexcept {
    if (nodeIndex < 0 || static_cast<std::size_t>(nodeIndex) >= shape.hierarchy.size() ||
        depth >= shape.hierarchy.size()) {
        return;
    }
    const CollisionShape::HierarchyNode& node = shape.hierarchy[static_cast<std::size_t>(nodeIndex)];
    if (node.triangles.empty()) return;
    if (!HierarchyNodeBoundsCrossTerrainPlane(node, localTerrain)) return;

    const Triangle splittingTriangle = ModelTriangle(shape, node.triangles.front());
    const float distances[3] = {
        LegacyStoredPlaneDistance(
            localTerrain.a, splittingTriangle.normal, splittingTriangle.planeOffset),
        LegacyStoredPlaneDistance(
            localTerrain.b, splittingTriangle.normal, splittingTriangle.planeOffset),
        LegacyStoredPlaneDistance(
            localTerrain.c, splittingTriangle.normal, splittingTriangle.planeOffset),
    };
    const bool firstNegative = std::signbit(distances[0]);
    const bool straddles = firstNegative != std::signbit(distances[1]) ||
        firstNegative != std::signbit(distances[2]);
    if (!straddles) {
        EnumerateHierarchyContactCandidates(
            body,
            shape,
            localTerrain,
            terrainFeature,
            firstNegative ? node.negativeChild : node.positiveChild,
            depth + 1,
            candidates);
        return;
    }

    EnumerateNodeContactCandidates(
        body, shape, node, localTerrain, terrainFeature, distances, candidates);
    // Constraint-append mode returns false after either edge family, so
    // FUN_00500260 continues through both subtrees after the first matching
    // node triangle. The listing visits the child at +0x32 before +0x30.
    EnumerateHierarchyContactCandidates(
        body, shape, localTerrain, terrainFeature, node.negativeChild, depth + 1, candidates);
    EnumerateHierarchyContactCandidates(
        body, shape, localTerrain, terrainFeature, node.positiveChild, depth + 1, candidates);
}

bool FindModelTerrainContact(
    const BodyState& body,
    const CollisionShape& shape,
    const TerrainGrid& terrain,
    ContactFeature& contact) {
    if (!terrain.IsValid()) {
        return false;
    }
    if (shape.vertices.empty() || shape.triangles.empty()) {
        for (std::size_t index = 0; index < shape.samples.size(); ++index) {
            const Vec3f world = body.orientation.Transform(shape.samples[index]) + body.position;
            const TerrainHit hit = terrain.Evaluate(world.x, world.y);
            if (world.z <= hit.point.z) {
                contact = {
                    hit.point,
                    hit.normal,
                    hit.normal,
                    -hit.normal,
                    static_cast<int>(index),
                    hit.triangle,
                };
                return true;
            }
        }
        return false;
    }

    // TestPhysicsBodyAgainstTerrain (0x00500E80) scans the square formed by
    // position +/- the baseline bounding radius, not the tighter transformed
    // vertex AABB. The broader range can contribute constraints from an
    // adjacent terrain cell even when no transformed vertex enters that cell.
    const float radius = ShapeRadius(shape);
    const int minimumX = std::clamp(
        static_cast<int>(std::floor((body.position.x - radius) / terrain.SpacingX())),
        0,
        static_cast<int>(terrain.CountX()) - 2);
    const int maximumX = std::clamp(
        static_cast<int>(std::floor((body.position.x + radius) / terrain.SpacingX())),
        0,
        static_cast<int>(terrain.CountX()) - 2);
    const int minimumY = std::clamp(
        static_cast<int>(std::floor((body.position.y - radius) / terrain.SpacingY())),
        0,
        static_cast<int>(terrain.CountY()) - 2);
    const int maximumY = std::clamp(
        static_cast<int>(std::floor((body.position.y + radius) / terrain.SpacingY())),
        0,
        static_cast<int>(terrain.CountY()) - 2);

    for (int cellY = minimumY; cellY <= maximumY; ++cellY) {
        for (int cellX = minimumX; cellX <= maximumX; ++cellX) {
            const auto terrainTriangles = TerrainCellTriangles(terrain, cellX, cellY);
            const auto localTerrainTriangles = LocalTerrainCellTrianglesForCollision(
                body, terrain, minimumX, minimumY, cellX, cellY);
            for (std::size_t terrainIndex = 0; terrainIndex < terrainTriangles.size(); ++terrainIndex) {
                const Triangle& terrainTriangle = terrainTriangles[terrainIndex];
                const Triangle& localTerrain = localTerrainTriangles[terrainIndex];
                const int terrainFeature =
                    (cellX * static_cast<int>(terrain.CountY() - 1) + cellY) * 2 +
                        terrainTriangle.feature;
                if (!shape.hierarchy.empty()) {
                    ContactCandidate candidate{};
                    if (FindHierarchyContactCandidate(
                            body, shape, localTerrain, terrainFeature, 0, 0, candidate)) {
                        contact = candidate.contact;
                        return true;
                    }
                    continue;
                }
                for (std::size_t modelIndex = 0; modelIndex < shape.triangles.size(); ++modelIndex) {
                    const Triangle modelTriangle = ModelTriangle(shape, modelIndex);
                    Vec3f localPoint{};
                    if (TriangleIntersection(modelTriangle, localTerrain, localPoint)) {
                        const Vec3f modelWorldNormal = body.orientation.Transform(modelTriangle.normal);
                        const Vec3f terrainWorldNormal = body.orientation.Transform(localTerrain.normal);
                        contact = {
                            body.orientation.Transform(localPoint) + body.position,
                            -modelWorldNormal,
                            terrainWorldNormal,
                            modelWorldNormal,
                            static_cast<int>(modelIndex),
                            terrainFeature,
                        };
                        return true;
                    }
                }
            }
        }
    }
    return false;
}

std::vector<ContactCandidate> EnumerateModelTerrainContactCandidates(
    const BodyState& body,
    const CollisionShape& shape,
    const TerrainGrid& terrain) {
    std::vector<ContactCandidate> candidates{};
    if (!terrain.IsValid() || shape.vertices.empty() || shape.triangles.empty()) {
        return candidates;
    }

    const float radius = ShapeRadius(shape);
    const int minimumX = std::clamp(
        static_cast<int>(std::floor((body.position.x - radius) / terrain.SpacingX())),
        0,
        static_cast<int>(terrain.CountX()) - 2);
    const int maximumX = std::clamp(
        static_cast<int>(std::floor((body.position.x + radius) / terrain.SpacingX())),
        0,
        static_cast<int>(terrain.CountX()) - 2);
    const int minimumY = std::clamp(
        static_cast<int>(std::floor((body.position.y - radius) / terrain.SpacingY())),
        0,
        static_cast<int>(terrain.CountY()) - 2);
    const int maximumY = std::clamp(
        static_cast<int>(std::floor((body.position.y + radius) / terrain.SpacingY())),
        0,
        static_cast<int>(terrain.CountY()) - 2);

    int generationIndex = 0;
    const auto appendCandidate = [&candidates, &generationIndex](
                                     ContactFeature contact,
                                     int edgeOwner,
                                     int edgeIndex) {
        candidates.push_back({contact, edgeOwner, edgeIndex, generationIndex++});
    };
    for (int cellY = minimumY; cellY <= maximumY; ++cellY) {
        for (int cellX = minimumX; cellX <= maximumX; ++cellX) {
            const auto terrainTriangles = TerrainCellTriangles(terrain, cellX, cellY);
            const auto localTerrainTriangles = LocalTerrainCellTrianglesForCollision(
                body, terrain, minimumX, minimumY, cellX, cellY);
            for (std::size_t terrainIndex = 0; terrainIndex < terrainTriangles.size(); ++terrainIndex) {
                const Triangle& terrainTriangle = terrainTriangles[terrainIndex];
                const Triangle& localTerrain = localTerrainTriangles[terrainIndex];
                const int terrainFeature =
                    (cellX * static_cast<int>(terrain.CountY() - 1) + cellY) * 2 +
                        terrainTriangle.feature;
                const Vec3f terrainVertices[3] = {
                    localTerrain.a, localTerrain.b, localTerrain.c};
                if (!shape.hierarchy.empty()) {
                    std::vector<ContactCandidate> hierarchyCandidates{};
                    EnumerateHierarchyContactCandidates(
                        body, shape, localTerrain, terrainFeature, 0, 0, hierarchyCandidates);
                    for (ContactCandidate& candidate : hierarchyCandidates) {
                        candidate.generationIndex = generationIndex++;
                        candidates.push_back(candidate);
                    }
                    continue;
                }
                for (std::size_t modelIndex = 0; modelIndex < shape.triangles.size(); ++modelIndex) {
                    const Triangle modelTriangle = ModelTriangle(shape, modelIndex);
                    const Vec3f modelVertices[3] = {
                        modelTriangle.a, modelTriangle.b, modelTriangle.c};
                    const Vec3f modelWorldNormal = body.orientation.Transform(modelTriangle.normal);
                    const Vec3f terrainWorldNormal = body.orientation.Transform(localTerrain.normal);
                    constexpr int edgeStarts[3] = {0, 2, 1};
                    constexpr int edgeEnds[3] = {1, 0, 2};
                    bool candidateAdded = false;
                    // Preserve FUN_005000E0's candidate-family order: terrain
                    // edges against the model face precede model edges against
                    // the terrain face. That routine returns from the current
                    // model leaf immediately after BuildModelTerrainContactOrConstraints,
                    // so retain only the first intersection for this model
                    // triangle/terrain triangle pair.
                    for (int order = 0; order < 3; ++order) {
                        const int edgeIndex = edgeStarts[order];
                        Vec3f point{};
                        if (SegmentPlaneTriangleIntersection(
                                terrainVertices[edgeIndex],
                                terrainVertices[edgeEnds[order]],
                                modelTriangle,
                                point)) {
                            appendCandidate(
                                {
                                    body.orientation.Transform(point) + body.position,
                                    -modelWorldNormal,
                                    terrainWorldNormal,
                                    modelWorldNormal,
                                    static_cast<int>(modelIndex),
                                    terrainFeature,
                                },
                                1,
                                edgeIndex);
                            candidateAdded = true;
                            break;
                        }
                    }
                    for (int order = 0; order < 3 && !candidateAdded; ++order) {
                        const int edgeIndex = edgeStarts[order];
                        Vec3f point{};
                        if (SegmentPlaneTriangleIntersection(
                                modelVertices[edgeIndex],
                                modelVertices[edgeEnds[order]],
                                localTerrain,
                                point)) {
                            appendCandidate(
                                {
                                    body.orientation.Transform(point) + body.position,
                                    -modelWorldNormal,
                                    terrainWorldNormal,
                                    modelWorldNormal,
                                    static_cast<int>(modelIndex),
                                    terrainFeature,
                                },
                                0,
                                edgeIndex);
                            break;
                        }
                    }
                }
            }
        }
    }
    return candidates;
}

bool IsBodyCenterBelowTerrain(const BodyState& body, const TerrainGrid& terrain) noexcept {
    return terrain.IsValid() && body.position.z < terrain.Evaluate(body.position.x, body.position.y).point.z;
}

void IntegrateBody(BodyState& body, double seconds) noexcept {
    IntegrateLinear(body, seconds);
    IntegrateAngular(body, seconds);
}

float EffectiveInertia(const BodyState& body, const Vec3f& axis) noexcept {
    // 0x004F0FD0 forms each squared-length sum in x87 precision, rounds the
    // sqrt and reciprocal to float, then rounds each weighted component before
    // the second sqrt.
    const float length = static_cast<float>(std::sqrt(
        static_cast<double>(axis.x) * axis.x +
        static_cast<double>(axis.y) * axis.y +
        static_cast<double>(axis.z) * axis.z));
    if (length <= 0.001F) {
        return (body.inertia.x + body.inertia.y + body.inertia.z) / 3.0F;
    }
    const float inverseLength = static_cast<float>(1.0 / static_cast<double>(length));
    const Vec3f weighted{
        static_cast<float>(axis.x * inverseLength * body.inertia.x),
        static_cast<float>(axis.y * inverseLength * body.inertia.y),
        static_cast<float>(axis.z * inverseLength * body.inertia.z),
    };
    return static_cast<float>(std::sqrt(
        static_cast<double>(weighted.x) * weighted.x +
        static_cast<double>(weighted.y) * weighted.y +
        static_cast<double>(weighted.z) * weighted.z));
}

double DirectionalK(const BodyState& body, const Vec3f& point, const Vec3f& direction) noexcept {
    const Vec3f leverArm = point - body.position;
    const Vec3f axis = Cross(leverArm, direction);
    const float inertia = EffectiveInertia(body, axis);
    if (!(body.mass > 0.0F) || !(inertia > 0.0F)) {
        return 0.0;
    }
    const float rotationalNumerator = LegacyStoredDot(direction, Cross(axis, leverArm));
    // ComputeContactImpulseDenominator (0x004F1A10) stores the rotational
    // numerator to float, but returns rotational/inertia + 1/mass in x87
    // precision. Its callers store that return value to double.
    return 1.0 / static_cast<double>(body.mass) +
        static_cast<double>(rotationalNumerator) / static_cast<double>(inertia);
}

void AccumulateImpulseDelta(
    const BodyState& body,
    const Vec3f& point,
    const Vec3f& direction,
    double impulse,
    Vec3f& pendingLinear,
    Vec3f& pendingAngular) noexcept {
    const Vec3f leverArm = point - body.position;
    const Vec3f axis = Cross(leverArm, direction);
    const float inertia = EffectiveInertia(body, axis);
    if (!(body.mass > 0.0F) || !(inertia > 0.0F)) {
        return;
    }
    // AccumulateContactVelocityImpulse (0x004F1B20) divides the incoming
    // double impulse by each float property in x87 precision, then stores each
    // completed scale to float.
    const float linearScale = static_cast<float>(impulse / static_cast<double>(body.mass));
    const float angularScale = static_cast<float>(impulse / static_cast<double>(inertia));
    pendingLinear += direction * linearScale;
    pendingAngular += WorldToLocalEulerZYX(axis * angularScale, body.eulerRadians);
}

void CommitVelocityDeltas(BodyState& body, Vec3f& linear, Vec3f& angular) noexcept {
    body.linearAcceleration = {};
    body.angularAcceleration = {};
    body.linearVelocity += linear;
    body.angularVelocity += angular;
    linear = {};
    angular = {};
}

float SelectContactTarget(BodyState& body, const Vec3f& point) noexcept {
    float target = 0.0F;
    if (body.legacyTypeCode < 5) {
        target = body.preGravityAccelerationIsSignificant ? 0.001F : 0.005F;
    } else {
        target = std::clamp(Length(point - body.position) * 0.03F, 0.01F, 0.5F);
    }
    body.settlingContactThreshold = target * 3.0;
    return target;
}

bool SolveStaticContact(
    BodyState& body,
    const ContactFeature& contact,
    float surfaceFriction,
    TraceEvent& event,
    bool usePreviousNormalVelocity,
    double previousNormalVelocity,
    double& finalNormalVelocityOut) noexcept {
    const double target = usePreviousNormalVelocity
        ? previousNormalVelocity + 0.1
        : static_cast<double>(SelectContactTarget(body, contact.point));
    double normalVelocity = static_cast<double>(
        LegacyStoredDot(PointVelocity(body, contact.point), contact.responseNormal));
    const float incomingNormalVelocity = static_cast<float>(normalVelocity);
    double correctionFloor = 0.005;
    double accumulatedNormalImpulse = 0.0;
    double accumulatedTangentImpulseMagnitude = 0.0;
    int iteration = 0;

    if (normalVelocity < target) {
        for (;;) {
            ++iteration;
            // 0x004F2AA0 fills the relative-velocity vector before the normal
            // update. 0x004F1D00 consumes that saved vector after the normal
            // deltas are committed; it is not recomputed for the tangent phase.
            const Vec3f relativeVelocityBeforeNormal = PointVelocity(body, contact.point);
            const double error = target - normalVelocity;
            double correction = error <= correctionFloor
                ? error
                : static_cast<double>(iteration) * error / 500.0;
            if (correction < correctionFloor) {
                correction = correctionFloor;
            }
            const double denominator = DirectionalK(body, contact.point, contact.responseNormal);
            if (!(denominator > 0.0)) {
                break;
            }
            // 0x004F2C51 divides the double correction by the double-stored
            // denominator sum and passes the result as a double.
            const double impulse = correction / denominator;
            Vec3f pendingLinear{};
            Vec3f pendingAngular{};
            AccumulateImpulseDelta(
                body, contact.point, contact.responseNormal, impulse, pendingLinear, pendingAngular);
            accumulatedNormalImpulse += impulse;
            CommitVelocityDeltas(body, pendingLinear, pendingAngular);

            if (!body.preGravityAccelerationIsSignificant) {
                const float normalProjection =
                    LegacyStoredDot(relativeVelocityBeforeNormal, contact.responseNormal);
                const Vec3f tangentVelocity = relativeVelocityBeforeNormal -
                    contact.responseNormal * normalProjection;
                const float tangentLength = Length(tangentVelocity);
                if (tangentLength >= 0.001F) {
                    const Vec3f tangent = tangentVelocity / tangentLength;
                    const double tangentDenominator = DirectionalK(body, contact.point, tangent);
                    if (tangentDenominator > 0.0) {
                        const float friction = std::min(
                            body.activeFriction,
                            std::max(surfaceFriction, 0.0F));
                        const float tangentProjection =
                            LegacyStoredDot(relativeVelocityBeforeNormal, tangent);
                        // 0x004F1D00 keeps the friction product and denominator
                        // division in x87 precision, then passes a double impulse.
                        const double tangentImpulse =
                            -(static_cast<double>(friction) * tangentProjection) /
                            static_cast<double>(tangentDenominator);
                        AccumulateImpulseDelta(
                            body, contact.point, tangent, tangentImpulse, pendingLinear, pendingAngular);
                        accumulatedTangentImpulseMagnitude += std::fabs(tangentImpulse);
                    }
                }
            }
            // Commit is unconditional on every reached tangent phase.
            CommitVelocityDeltas(body, pendingLinear, pendingAngular);
            if (iteration > 100) {
                break;
            }
            normalVelocity = static_cast<double>(
                LegacyStoredDot(PointVelocity(body, contact.point), contact.responseNormal));
            if (normalVelocity >= target) {
                break;
            }
            correctionFloor += 0.0001;
        }
    }

    Vec3f finalLinear{};
    Vec3f finalAngular{};
    if (accumulatedNormalImpulse > 0.0001) {
        const float fraction = body.legacyTypeCode < 5 && body.preGravityAccelerationIsSignificant
            ? 0.2F
            : 0.1F;
        AccumulateImpulseDelta(
            body,
            contact.point,
            contact.responseNormal,
            static_cast<double>(fraction) * accumulatedNormalImpulse,
            finalLinear,
            finalAngular);
    }
    // The worker-exit commit is unconditional.
    CommitVelocityDeltas(body, finalLinear, finalAngular);
    event.scalar1 = accumulatedNormalImpulse;
    const float finalNormalVelocity =
        LegacyStoredDot(PointVelocity(body, contact.point), contact.responseNormal);
    finalNormalVelocityOut = static_cast<double>(finalNormalVelocity);
    event.value = {
        incomingNormalVelocity,
        static_cast<float>(accumulatedTangentImpulseMagnitude),
        finalNormalVelocity,
    };
    return accumulatedNormalImpulse > 0.0;
}

bool FindEarliestTerrainEvent(
    const BodyState& body,
    const CollisionShape& shape,
    const TerrainGrid& terrain,
    double interval,
    double& eventTime,
    BodyState& responsePose,
    ContactFeature& eventContact) {
    ContactFeature startContact{};
    if (FindModelTerrainContact(body, shape, terrain, startContact)) {
        if (Dot(PointVelocity(body, startContact.point), startContact.responseNormal) < 0.0F) {
            eventTime = 0.0;
            responsePose = body;
            eventContact = startContact;
            return true;
        }
    }

    BodyState collidingTrial = body;
    IntegrateBody(collidingTrial, interval);
    ContactFeature collidingContact{};
    if (!FindModelTerrainContact(collidingTrial, shape, terrain, collidingContact)) {
        return false;
    }

    BodyState checkpoint = body;
    double checkpointTime = 0.0;
    double trialOffset = interval;
    double halfStep = interval;
    bool previousTrialCollided = true;
    bool foundSafeMidpoint = false;
    while ((halfStep *= 0.5) > kSweepBracketStepSeconds) {
        trialOffset += previousTrialCollided ? -halfStep : halfStep;
        BodyState predicted = checkpoint;
        IntegrateBody(predicted, trialOffset);
        ContactFeature contact{};
        previousTrialCollided = FindModelTerrainContact(predicted, shape, terrain, contact);
        if (previousTrialCollided) {
            collidingContact = contact;
        } else {
            checkpoint = predicted;
            checkpointTime += trialOffset;
            trialOffset = 0.0;
            foundSafeMidpoint = true;
        }
    }

    responsePose = checkpoint;
    eventTime = foundSafeMidpoint
        ? checkpointTime
        : std::min(interval, kSweepFallbackEventAdvanceSeconds);
    eventContact = collidingContact;
    return true;
}

bool FindEarliestStaticBodyEvent(
    const BodyState& body,
    const CollisionShape& shape,
    const StaticBodySurface& surface,
    double interval,
    double& eventTime,
    BodyState& responsePose,
    ContactFeature& eventContact) {
    if (surface.shape == nullptr) {
        return false;
    }
    ContactFeature startContact{};
    if (FindModelModelContact(
            body, shape, surface.body, *surface.shape, startContact)) {
        const Vec3f pointVelocity = PointVelocity(body, startContact.point);
        if (Dot(pointVelocity, startContact.responseNormal) < 0.0F ||
            Dot(pointVelocity, startContact.alternateResponseNormal) < 0.0F) {
            eventTime = 0.0;
            responsePose = body;
            eventContact = startContact;
            return true;
        }
    }

    BodyState collidingTrial = body;
    IntegrateBody(collidingTrial, interval);
    ContactFeature collidingContact{};
    if (!FindModelModelContact(
            collidingTrial, shape, surface.body, *surface.shape, collidingContact)) {
        return false;
    }

    BodyState checkpoint = body;
    double checkpointTime = 0.0;
    double trialOffset = interval;
    double halfStep = interval;
    bool previousTrialCollided = true;
    bool foundSafeMidpoint = false;
    while ((halfStep *= 0.5) > kSweepBracketStepSeconds) {
        trialOffset += previousTrialCollided ? -halfStep : halfStep;
        BodyState predicted = checkpoint;
        IntegrateBody(predicted, trialOffset);
        ContactFeature contact{};
        previousTrialCollided = FindModelModelContact(
            predicted, shape, surface.body, *surface.shape, contact);
        if (previousTrialCollided) {
            collidingContact = contact;
        } else {
            checkpoint = predicted;
            checkpointTime += trialOffset;
            trialOffset = 0.0;
            foundSafeMidpoint = true;
        }
    }

    responsePose = checkpoint;
    eventTime = foundSafeMidpoint
        ? checkpointTime
        : std::min(interval, kSweepFallbackEventAdvanceSeconds);
    eventContact = collidingContact;
    return true;
}

void ApplyStaticTerrainEmergencyOverlapRecovery(
    BodyState& body,
    const CollisionShape& shape,
    const TerrainGrid& terrain,
    const ContactFeature& eventContact) noexcept {
    // BuildSweptCollisionEvent selects emergency recovery when the body is
    // already colliding at the saved sweep-start pose. For a static terrain
    // side, ApplyEmergencyOverlapSeparation (0x004FB3E0) repeatedly restores
    // that pose and tries a displacement away from the event point. The first
    // trial is exactly one unit along that direction; later trials grow by 1.2
    // and blend toward +Z by 0.05 per failed collision test.
    const Vec3f savedPosition = body.position;
    const Vec3f eventDirection = NormalizeCollisionPlane(body.position - eventContact.point);
    double directionWeight = 1.0;
    double displacementLength = 1.0;
    for (int attempt = 0; attempt < 128; ++attempt) {
        ContactFeature overlap{};
        if (!FindModelTerrainContact(body, shape, terrain, overlap)) {
            return;
        }
        body.position = savedPosition;
        if (displacementLength > 1000.0) {
            displacementLength = 200.0;
        }
        if (directionWeight < 0.0) {
            directionWeight = 0.0;
        }
        const float storedWeight = static_cast<float>(directionWeight);
        Vec3f direction{
            static_cast<float>(eventDirection.x * storedWeight),
            static_cast<float>(eventDirection.y * storedWeight),
            static_cast<float>(
                eventDirection.z * storedWeight + (1.0F - storedWeight)),
        };
        direction = NormalizeCollisionPlane(direction);
        const float storedLength = static_cast<float>(displacementLength);
        body.position = {
            static_cast<float>(body.position.x + direction.x * storedLength),
            static_cast<float>(body.position.y + direction.y * storedLength),
            static_cast<float>(body.position.z + direction.z * storedLength),
        };
        displacementLength *= 1.2;
        directionWeight -= 0.05;
    }
}

void ApplyStaticBodyEmergencyOverlapRecovery(
    BodyState& body,
    const CollisionShape& shape,
    const StaticBodySurface& surface,
    const ContactFeature& eventContact) {
    if (surface.shape == nullptr) {
        return;
    }
    const Vec3f savedPosition = body.position;
    const Vec3f centerDirection = body.position - surface.body.position;
    const Vec3f direction = NormalizeOr(
        centerDirection,
        NormalizeOr(eventContact.responseNormal, {0.0F, 0.0F, 1.0F}));
    float displacementLength = 1.0F;
    for (int attempt = 0; attempt < 128; ++attempt) {
        ContactFeature overlap{};
        if (!FindModelModelContact(
                body, shape, surface.body, *surface.shape, overlap)) {
            return;
        }
        body.position = savedPosition + direction * displacementLength;
        displacementLength = displacementLength > 1000.0F
            ? 200.0F
            : displacementLength * 1.2F;
    }
}

void SolveAndIntegrateEnvironment(
    BodyState& body,
    const CollisionShape& shape,
    const TerrainGrid& terrain,
    const std::vector<StaticBodySurface>& staticSurfaces,
    double seconds,
    EntityId entity,
    SimulationTick tick,
    StepMilliseconds stepMilliseconds,
    std::vector<TraceEvent>& trace,
    bool traceContactCandidates,
    std::uint64_t& contactRoundRobinSeed) {
    const bool hasTriangleGeometry = !shape.vertices.empty() && !shape.triangles.empty();
    if ((!terrain.IsValid() && staticSurfaces.empty()) ||
        (!hasTriangleGeometry && shape.samples.empty())) {
        IntegrateBody(body, seconds);
        return;
    }
    double remaining = seconds;
    for (int eventIndex = 0;
         eventIndex < kMaximumEventsPerStep && remaining > 1.0e-8;
         ++eventIndex) {
        double eventTime = 0.0;
        BodyState responsePose = body;
        ContactFeature contact{};
        const StaticBodySurface* selectedStaticSurface = nullptr;
        BodyState restoredSweepStart = body;
        // BuildSweptCollisionEvent restores the saved Euler state before its
        // zero-time overlap retest. That restore invalidates the original
        // body's cached matrix, so GetBodyOrientationMatrix (0x00448E50)
        // rebuilds it before TestCollisionModelAgainstTerrainGrid. A fork
        // snapshot can legitimately contain the pre-restore cached matrix.
        restoredSweepStart.orientation =
            Matrix3d::FromEulerAngles(restoredSweepStart.eulerRadians);
        bool emergencyOverlap =
            FindModelTerrainContact(restoredSweepStart, shape, terrain, contact);
        if (!emergencyOverlap && hasTriangleGeometry) {
            for (const StaticBodySurface& surface : staticSurfaces) {
                if (surface.shape != nullptr && FindModelModelContact(
                        restoredSweepStart,
                        shape,
                        surface.body,
                        *surface.shape,
                        contact)) {
                    emergencyOverlap = true;
                    selectedStaticSurface = &surface;
                    break;
                }
            }
        }
        if (emergencyOverlap) {
            body.orientation = restoredSweepStart.orientation;
            TraceEvent event{};
            event.type = TraceEventType::Contact;
            event.tick = tick;
            event.entity = entity;
            event.stepMilliseconds = stepMilliseconds;
            event.feature = contact.modelFeature;
            event.point = contact.point;
            event.normal = contact.reportedNormal;
            event.scalar0 = 0.0;
            event.secondaryFeature = contact.terrainFeature;
            event.bucket = 0;
            event.otherEntity = selectedStaticSurface == nullptr
                ? 0
                : selectedStaticSurface->id;
            trace.push_back(event);
            if (selectedStaticSurface == nullptr) {
                ApplyStaticTerrainEmergencyOverlapRecovery(body, shape, terrain, contact);
            } else {
                ApplyStaticBodyEmergencyOverlapRecovery(
                    body, shape, *selectedStaticSurface, contact);
            }
            IntegrateBody(body, remaining);
            remaining = 0.0;
            break;
        }
        bool foundEvent = FindEarliestTerrainEvent(
            body,
            shape,
            terrain,
            remaining,
            eventTime,
            responsePose,
            contact);
        if (hasTriangleGeometry) {
            for (const StaticBodySurface& surface : staticSurfaces) {
                double candidateTime = 0.0;
                BodyState candidateResponsePose = body;
                ContactFeature candidateContact{};
                if (surface.shape == nullptr || !FindEarliestStaticBodyEvent(
                        body,
                        shape,
                        surface,
                        remaining,
                        candidateTime,
                        candidateResponsePose,
                        candidateContact)) {
                    continue;
                }
                if (!foundEvent || candidateTime < eventTime) {
                    foundEvent = true;
                    eventTime = candidateTime;
                    responsePose = candidateResponsePose;
                    contact = candidateContact;
                    selectedStaticSurface = &surface;
                }
            }
        }
        if (!foundEvent) {
            IntegrateBody(body, remaining);
            remaining = 0.0;
            break;
        }
        // The broad swept probe above runs before BuildSweptCollisionEvent has
        // restored the saved Euler state. Once it finds an event, the original
        // restores that state, invalidates the cached matrix, and repeats the
        // event construction from the rebuilt orientation. This distinction
        // matters at grazing boundaries: rebuilding before the broad probe can
        // manufacture a contact which the original never queued.
        body.orientation = restoredSweepStart.orientation;
        responsePose = body;
        if (selectedStaticSurface == nullptr) {
            FindEarliestTerrainEvent(
                body,
                shape,
                terrain,
                remaining,
                eventTime,
                responsePose,
                contact);
        } else {
            FindEarliestStaticBodyEvent(
                body,
                shape,
                *selectedStaticSurface,
                remaining,
                eventTime,
                responsePose,
                contact);
        }
        BodyState collisionPose = body;
        IntegrateBody(collisionPose, eventTime);
        // BuildSweptCollisionEvent restores the last known-clear checkpoint
        // before solving. Its short-interval fallback can therefore advance
        // the event timestamp while leaving the response pose unchanged. The
        // selected contact still comes from the colliding trial pose.
        body = responsePose;
        remaining = std::max(remaining - eventTime, 0.0);
        const int bucket = seconds <= 0.0
            ? 0
            : std::min(static_cast<int>(std::floor(eventTime * (kCollisionBucketCount / seconds))), 29);
        const std::vector<ContactCandidate> manifold = selectedStaticSurface == nullptr
            ? EnumerateModelTerrainContactCandidates(collisionPose, shape, terrain)
            : std::vector<ContactCandidate>{{contact, -1, -1, 0}};
        if (traceContactCandidates) {
            for (const ContactCandidate& candidate : manifold) {
                TraceEvent candidateEvent{};
                candidateEvent.type = TraceEventType::ContactCandidate;
                candidateEvent.tick = tick;
                candidateEvent.entity = entity;
                candidateEvent.stepMilliseconds = stepMilliseconds;
                candidateEvent.feature = candidate.contact.modelFeature;
                candidateEvent.point = candidate.contact.point;
                candidateEvent.normal = candidate.contact.reportedNormal;
                candidateEvent.value = {
                    static_cast<float>(candidate.edgeOwner),
                    static_cast<float>(candidate.edgeIndex),
                    static_cast<float>(candidate.generationIndex),
                };
                candidateEvent.scalar0 = eventTime;
                candidateEvent.scalar1 = Length(candidate.contact.point - contact.point);
                candidateEvent.secondaryFeature = candidate.contact.terrainFeature;
                candidateEvent.bucket = bucket;
                candidateEvent.otherEntity = selectedStaticSurface == nullptr
                    ? 0
                    : selectedStaticSurface->id;
                trace.push_back(candidateEvent);
            }
        }
        TraceEvent event{};
        event.type = TraceEventType::Contact;
        event.tick = tick;
        event.entity = entity;
        event.stepMilliseconds = stepMilliseconds;
        event.feature = contact.modelFeature;
        event.point = contact.point;
        event.normal = contact.reportedNormal;
        event.scalar0 = eventTime;
        event.otherEntity = selectedStaticSurface == nullptr
            ? 0
            : selectedStaticSurface->id;
        // The event-pose retest appends two directed constraints for every
        // manifold point: the body-directed negative model-face normal first,
        // then the terrain-face normal. The displayed swept-event point is not
        // necessarily the constraint that responds.
        // SolveContactConstraintsRoundRobin advances one persistent seed per
        // pass, begins at seed % totalConstraintCount, and stops at the first
        // constraint that produces positive normal impulse.
        // In constraint-append mode BuildModelTerrainContactOrConstraints
        // returns false after either edge family, but TestPhysicsBodyAgainstTerrain
        // reports success when its appended-record count is nonzero. The swept
        // pair is therefore the fallback only when the retest appended nothing.
        const bool appendSweptFallback = manifold.empty();
        const std::size_t constraintCount =
            (manifold.size() + (appendSweptFallback ? 1 : 0)) * 2;
        std::vector<double> previousNormalVelocities(constraintCount, 0.0);
        const auto solvePass = [&](bool usePreviousNormalVelocity) {
            const std::size_t passFirstConstraint = static_cast<std::size_t>(
                contactRoundRobinSeed++ % constraintCount);
            for (std::size_t attempt = 0; attempt < constraintCount; ++attempt) {
                const std::size_t constraint =
                    (passFirstConstraint + attempt) % constraintCount;
                const std::size_t contactIndex = constraint / 2;
                ContactFeature directedContact = contactIndex < manifold.size()
                    ? manifold[contactIndex].contact
                    : contact;
                directedContact.responseNormal = (constraint % 2) == 0
                    ? directedContact.responseNormal
                    : directedContact.alternateResponseNormal;
                double finalNormalVelocity = 0.0;
                if (SolveStaticContact(
                        body,
                        directedContact,
                        selectedStaticSurface == nullptr
                            ? 1.0F
                            : selectedStaticSurface->friction,
                        event,
                        usePreviousNormalVelocity,
                        previousNormalVelocities[constraint],
                        finalNormalVelocity)) {
                    previousNormalVelocities[constraint] = finalNormalVelocity;
                    return true;
                }
                previousNormalVelocities[constraint] = finalNormalVelocity;
            }
            return false;
        };
        bool producedImpulse = solvePass(false);
        // ProcessBodyPairContactConstraints (0x004F31F0) retries the complete
        // cyclic list when the ordinary target produces no impulse. The retry
        // starts from the next global seed and uses each record's normal
        // velocity stored by the first pass plus 0.1 as its target.
        if (!producedImpulse) {
            producedImpulse = solvePass(true);
        }
        // Preserve bucket identity for trace comparison without making allocator
        // or pointer order part of the portable API.
        // Feature order, bucket, incoming/outgoing velocity, and impulses are
        // all retained in the event without conflating event time with response.
        event.secondaryFeature = contact.terrainFeature;
        event.bucket = bucket;
        trace.push_back(event);
        if (eventTime <= 0.0 && !producedImpulse) {
            IntegrateBody(body, remaining);
            remaining = 0.0;
            break;
        }
    }
    if (remaining > 1.0e-8) {
        IntegrateBody(body, remaining);
    }
}

bool RayIntersectsTriangle(const Vec3f& origin, const Triangle& triangle) noexcept {
    const Vec3f direction{1.0F, 0.0F, 0.0F};
    const Vec3f edge1 = triangle.b - triangle.a;
    const Vec3f edge2 = triangle.c - triangle.a;
    const Vec3f p = Cross(direction, edge2);
    const float determinant = Dot(edge1, p);
    if (std::fabs(determinant) < 1.0e-6F) return false;
    const float inverse = 1.0F / determinant;
    const Vec3f t = origin - triangle.a;
    const float u = Dot(t, p) * inverse;
    if (u < 0.0F || u > 1.0F) return false;
    const Vec3f q = Cross(t, edge1);
    const float v = Dot(direction, q) * inverse;
    if (v < 0.0F || u + v > 1.0F) return false;
    return Dot(edge2, q) * inverse > 1.0e-6F;
}

float ShapeRadius(const CollisionShape& shape) noexcept {
    float radius = 0.0F;
    for (const Vec3f& vertex : shape.vertices) {
        radius = std::max(radius, Length(vertex));
    }
    return radius;
}

bool RelativeCenterInsideLargerShape(
    const BodyState& smallerBody,
    const BodyState& largerBody,
    const CollisionShape& largerShape) noexcept {
    // Preserve the recovered fallback's deliberately coarse input: the smaller
    // center relative to the larger center, without inverse orientation and
    // without the smaller body's extent.
    const Vec3f relativeCenter = smallerBody.position - largerBody.position;
    int intersections = 0;
    for (const auto& indices : largerShape.triangles) {
        Triangle triangle{
            largerShape.vertices[indices[0]],
            largerShape.vertices[indices[1]],
            largerShape.vertices[indices[2]],
        };
        triangle.normal = NormalizeOr(Cross(triangle.b - triangle.a, triangle.c - triangle.a), {0.0F, 0.0F, 1.0F});
        intersections += RayIntersectsTriangle(relativeCenter, triangle) ? 1 : 0;
    }
    return (intersections & 1) != 0;
}

bool BodiesOverlap(
    const BodyState& leftBody,
    const CollisionShape& leftShape,
    const BodyState& rightBody,
    const CollisionShape& rightShape) {
    if (leftShape.vertices.empty() || rightShape.vertices.empty()) {
        return false;
    }
    const auto left = TransformVertices(leftBody, leftShape);
    const auto right = TransformVertices(rightBody, rightShape);
    Vec3f leftMinimum = left.front();
    Vec3f leftMaximum = left.front();
    Vec3f rightMinimum = right.front();
    Vec3f rightMaximum = right.front();
    const auto expand = [](const std::vector<Vec3f>& vertices, Vec3f& minimum, Vec3f& maximum) {
        for (const Vec3f& vertex : vertices) {
            minimum.x = std::min(minimum.x, vertex.x);
            minimum.y = std::min(minimum.y, vertex.y);
            minimum.z = std::min(minimum.z, vertex.z);
            maximum.x = std::max(maximum.x, vertex.x);
            maximum.y = std::max(maximum.y, vertex.y);
            maximum.z = std::max(maximum.z, vertex.z);
        }
    };
    expand(left, leftMinimum, leftMaximum);
    expand(right, rightMinimum, rightMaximum);
    const bool broadOverlap = leftMinimum.x <= rightMaximum.x && leftMaximum.x >= rightMinimum.x &&
        leftMinimum.y <= rightMaximum.y && leftMaximum.y >= rightMinimum.y &&
        leftMinimum.z <= rightMaximum.z && leftMaximum.z >= rightMinimum.z;
    if (!broadOverlap) {
        return false;
    }
    for (const auto& leftIndices : leftShape.triangles) {
        Triangle leftTriangle{left[leftIndices[0]], left[leftIndices[1]], left[leftIndices[2]]};
        leftTriangle.normal = NormalizeOr(
            Cross(leftTriangle.b - leftTriangle.a, leftTriangle.c - leftTriangle.a),
            {0.0F, 0.0F, 1.0F});
        for (const auto& rightIndices : rightShape.triangles) {
            Triangle rightTriangle{right[rightIndices[0]], right[rightIndices[1]], right[rightIndices[2]]};
            rightTriangle.normal = NormalizeOr(
                Cross(rightTriangle.b - rightTriangle.a, rightTriangle.c - rightTriangle.a),
                {0.0F, 0.0F, 1.0F});
            Vec3f point{};
            if (TriangleIntersection(leftTriangle, rightTriangle, point)) {
                return true;
            }
        }
    }
    if (ShapeRadius(leftShape) < ShapeRadius(rightShape)) {
        return RelativeCenterInsideLargerShape(leftBody, rightBody, rightShape);
    }
    return RelativeCenterInsideLargerShape(rightBody, leftBody, leftShape);
}

struct JetRuntime {
    std::array<Vec3f, 4> localPoints{};
    std::array<Vec3f, 4> configuredDirections{};
    std::array<Vec3f, 4> worldProbePoints{};
    std::array<Vec3f, 4> runtimeDirections{};
    std::array<double, 4> groundClearances{};
    std::array<Vec3f, 4> groundHitPositions{};
    std::array<Vec3f, 4> groundHitNormals{};
    std::array<bool, 4> groundHitValid{};
    std::array<EntityId, 4> groundSupportEntities{};
    std::array<Vec3f, 4> groundSupportVelocities{};
    std::array<double, 4> pointReactionScales{1.0, 1.0, 1.0, 1.0};
    std::array<float, 4> groundSegmentAngles{};
    Vec3f groundNormal{0.0F, 0.0F, 1.0F};
    float normalizedHorizontalSpeed = 0.0F;
    double averageGroundClearance = 0.0;
    double normalizedGroundClearance = 0.0;
    double heightNormalization = 1.0;
    double targetHeightScale = 1.0;
    double speedHeightPickup = 0.0;
    double gravityReactionScale = 1.0;
    double gravityMagnitude = 160.0;
    double heightControlInput = 0.0;
    float pitchCommandRadians = 0.0F;
    float rollCommand = 0.0F;
};

void ApplyJetShape(JetRuntime& jet, const JetShape& shape) noexcept {
    for (std::size_t index = 0; index < jet.localPoints.size(); ++index) {
        jet.localPoints[index] = shape.points[index].localPoint;
        jet.configuredDirections[index] = shape.points[index].configuredDirection;
    }
}

float GroundAngle(const JetRuntime& jet, int a, int b) noexcept {
    if (!jet.groundHitValid[a] || !jet.groundHitValid[b]) {
        return 0.0F;
    }
    const float distance = Length(jet.groundHitPositions[b] - jet.groundHitPositions[a]);
    if (distance <= 1.0e-6F) {
        return 0.0F;
    }
    const float ratio = (jet.groundHitPositions[a].z - jet.groundHitPositions[b].z) / distance;
    return std::asin(std::clamp(ratio, -1.0F, 1.0F));
}

struct ProbeBodySurface {
    EntityId id = 0;
    BodyState body{};
    const CollisionShape* shape = nullptr;
};

bool FindVerticalBodyProbeHit(
    const Vec3f& probe,
    const ProbeBodySurface& surface,
    Vec3f& pointOut,
    Vec3f& normalOut) noexcept {
    if (surface.shape == nullptr) {
        return false;
    }

    bool found = false;
    float highestZ = -std::numeric_limits<float>::infinity();
    for (const auto& indices : surface.shape->triangles) {
        if (indices[0] >= surface.shape->vertices.size() ||
            indices[1] >= surface.shape->vertices.size() ||
            indices[2] >= surface.shape->vertices.size()) {
            continue;
        }
        const Vec3f a = surface.body.orientation.Transform(
            surface.shape->vertices[indices[0]]) + surface.body.position;
        const Vec3f b = surface.body.orientation.Transform(
            surface.shape->vertices[indices[1]]) + surface.body.position;
        const Vec3f c = surface.body.orientation.Transform(
            surface.shape->vertices[indices[2]]) + surface.body.position;
        Vec3f planeNormal = Cross(b - a, c - a);
        if (std::fabs(planeNormal.z) <= 1.0e-6F) {
            continue;
        }
        const float hitZ = a.z -
            (planeNormal.x * (probe.x - a.x) +
             planeNormal.y * (probe.y - a.y)) / planeNormal.z;
        if (hitZ > probe.z + 1.0e-4F || hitZ <= highestZ) {
            continue;
        }
        const Vec3f point{probe.x, probe.y, hitZ};
        constexpr float insideTolerance = -1.0e-3F;
        if (Dot(Cross(b - a, point - a), planeNormal) < insideTolerance ||
            Dot(Cross(c - b, point - b), planeNormal) < insideTolerance ||
            Dot(Cross(a - c, point - c), planeNormal) < insideTolerance) {
            continue;
        }
        highestZ = hitZ;
        pointOut = point;
        normalOut = NormalizeOr(planeNormal, {0.0F, 0.0F, 1.0F});
        if (normalOut.z < 0.0F) {
            normalOut = -normalOut;
        }
        found = true;
    }
    return found;
}

void UpdateJetGroundContacts(
    JetRuntime& jet,
    const BodyState& body,
    const TerrainGrid& terrain,
    const std::vector<ProbeBodySurface>& bodySurfaces,
    EntityId entity,
    SimulationTick tick,
    StepMilliseconds stepMilliseconds,
    std::vector<TraceEvent>& trace) {
    const float horizontalSpeed = std::sqrt(
        body.linearVelocity.x * body.linearVelocity.x + body.linearVelocity.y * body.linearVelocity.y);
    Vec3f normalSum{};
    double clearanceSum = 0.0;
    for (std::size_t index = 0; index < jet.localPoints.size(); ++index) {
        jet.worldProbePoints[index] = body.orientation.Transform(jet.localPoints[index]) + body.position;
        jet.runtimeDirections[index] = jet.configuredDirections[index];
        const TerrainHit hit = terrain.Evaluate(jet.worldProbePoints[index].x, jet.worldProbePoints[index].y);
        bool hitValid = terrain.IsValid();
        Vec3f hitPoint = hit.point;
        Vec3f hitNormal = hit.normal;
        EntityId supportEntity = 0;
        Vec3f supportVelocity{};

        // The original hover probe checks nearby body geometry before its
        // terrain fallback. The portable world currently resolves terrain
        // contacts only, but probing the other registered collision meshes
        // here still lets hover and jump support moving Tanks and objects as
        // the broader body solver is reconstructed.
        for (const ProbeBodySurface& surface : bodySurfaces) {
            if (surface.id == entity) {
                continue;
            }
            Vec3f bodyPoint{};
            Vec3f bodyNormal{};
            if (!FindVerticalBodyProbeHit(
                    jet.worldProbePoints[index], surface, bodyPoint, bodyNormal)) {
                continue;
            }
            if (!hitValid || bodyPoint.z > hitPoint.z) {
                hitValid = true;
                hitPoint = bodyPoint;
                hitNormal = bodyNormal;
                supportEntity = surface.id;
                supportVelocity = PointVelocity(surface.body, bodyPoint);
            }
        }

        jet.groundHitValid[index] = hitValid;
        jet.groundHitPositions[index] = hitPoint;
        jet.groundHitNormals[index] = hitNormal;
        jet.groundSupportEntities[index] = supportEntity;
        jet.groundSupportVelocities[index] = supportVelocity;
        // TraceJetPointToGround (0x004DE760) subtracts the two float Z values
        // in x87 precision and stores the result directly in the runtime's
        // double clearance array. Promote before subtracting so the portable
        // path does not introduce an extra float-rounding boundary.
        jet.groundClearances[index] = hitValid
            ? static_cast<double>(jet.worldProbePoints[index].z) -
                static_cast<double>(hitPoint.z)
            : 5000.0;
        if (hitValid) {
            normalSum += hitNormal;
        }
        clearanceSum += jet.groundClearances[index];
        trace.push_back({
            TraceEventType::Probe,
            tick,
            entity,
            stepMilliseconds,
            static_cast<std::int32_t>(index),
            jet.worldProbePoints[index],
            hitNormal,
            hitPoint,
            jet.groundClearances[index],
            supportEntity == 0
                ? static_cast<double>(
                    (hit.cellX * static_cast<int>(terrain.CountY() - 1) + hit.cellY) * 2 +
                    hit.triangle)
                : -1.0,
            supportEntity == 0
                ? -1
                : static_cast<std::int32_t>(supportEntity & 0x7fffffffU),
        });
    }
    jet.groundNormal = Length(normalSum) > 0.0001F
        ? normalSum / Length(normalSum)
        : Vec3f{0.0F, 0.0F, 1.0F};
    jet.averageGroundClearance = clearanceSum / 3.0;
    jet.normalizedGroundClearance = jet.averageGroundClearance / jet.heightNormalization;
    if (jet.normalizedGroundClearance > 1.0) {
        jet.normalizedGroundClearance = 1.0;
    }
    jet.groundSegmentAngles[0] = GroundAngle(jet, 0, 2);
    jet.groundSegmentAngles[1] = GroundAngle(jet, 1, 3);
    jet.groundSegmentAngles[2] = GroundAngle(jet, 0, 1);
    jet.groundSegmentAngles[3] = GroundAngle(jet, 2, 3);
    // Caller applies the profile maximum because it owns configuration.
    jet.normalizedHorizontalSpeed = horizontalSpeed;
}

std::array<float, 4> BuildProbeHeightOffsets(const JetRuntime& jet, const JetMiscSettings& misc) noexcept {
    std::array<float, 4> offsets{};
    const auto addPitch = [&](int angleIndex, int a, int b) {
        const float groundAngle = jet.groundSegmentAngles[angleIndex];
        const float limit = misc.tiltMaximum * 3.14159265358979323846F * 0.5F;
        const float angle = std::clamp(groundAngle - jet.pitchCommandRadians, -limit, limit);
        const float spacing = std::fabs(jet.localPoints[a].x - jet.localPoints[b].x);
        const float correction =
            (std::sin(angle) - std::tan(groundAngle) * std::cos(angle)) *
            spacing * misc.tiltErrorMagnitude;
        if (correction < 0.0F) offsets[b] -= correction; else offsets[a] += correction;
    };
    const auto addRoll = [&](int angleIndex, int a, int b) {
        const float groundAngle = jet.groundSegmentAngles[angleIndex];
        const float limit = misc.rollMaximum * 3.14159265358979323846F * 0.5F;
        const float angle = std::clamp(
            groundAngle + jet.rollCommand * 3.14159265358979323846F * 0.5F,
            -limit,
            limit);
        const float spacing = std::fabs(jet.localPoints[a].y - jet.localPoints[b].y);
        const float correction =
            (std::sin(angle) - std::tan(groundAngle) * std::cos(angle)) *
            spacing * misc.rollErrorMagnitude;
        if (correction < 0.0F) offsets[b] -= correction; else offsets[a] += correction;
    };
    addPitch(0, 0, 2);
    addPitch(1, 1, 3);
    addRoll(2, 0, 1);
    addRoll(3, 2, 3);
    return offsets;
}

double ComputeJetPointResponse(
    const BodyState& body,
    const JetRuntime& jet,
    const JetProfile& profile,
    int pointIndex,
    double target,
    double measured,
    double& reactionBlend) noexcept {
    const double rawHeight = measured / jet.heightNormalization;
    const float abate = profile.abate.Evaluate(
        static_cast<float>(rawHeight / profile.misc.jetAbateMaximum));
    const double height = std::min(rawHeight, 1.0);
    reactionBlend = std::min(
        static_cast<double>(jet.normalizedHorizontalSpeed),
        1.0 - height);
    const float error = static_cast<float>(target - measured);
    const float prime = PointVelocity(body, jet.worldProbePoints[pointIndex]).z;
    const float fast = profile.fastReaction.Evaluate(error, prime);
    const float slow = profile.slowReaction.Evaluate(error, prime);
    const float speed = profile.speed.Evaluate(jet.normalizedHorizontalSpeed);
    const float heightValue = profile.height.Evaluate(static_cast<float>(height));
    const float consider = profile.heightConsider.Evaluate(jet.normalizedHorizontalSpeed);
    // ComputeJetPointResponse (0x004DDFF0) rounds only the response weight to
    // float. The final fast/slow blend remains in x87 precision through the
    // double gravity scale and is not first stored as a float.
    const float weightDenominator = static_cast<float>(
        static_cast<double>(consider) + 1.0);
    const float fastWeight = static_cast<float>(
        (static_cast<double>(speed) +
         static_cast<double>(heightValue) * consider) /
        weightDenominator);
    const double feedback =
        static_cast<double>(fastWeight) * fast +
        static_cast<double>(slow) * (1.0 - static_cast<double>(fastWeight));
    return ((jet.gravityMagnitude +
             feedback * jet.gravityReactionScale * jet.gravityMagnitude) * abate) /
        3.0;
}

std::pair<Vec3f, Vec3f> ComputeHoverAcceleration(
    const BodyState& body,
    const JetRuntime& jet,
    const JetProfile& profile) noexcept {
    const auto offsets = BuildProbeHeightOffsets(jet, profile.misc);
    Vec3f linear{};
    Vec3f angular{};
    for (std::size_t index = 0; index < jet.localPoints.size(); ++index) {
        const double clearance = std::max(jet.groundClearances[index], 0.5);
        const double target = jet.heightControlInput * jet.targetHeightScale +
            offsets[index] + jet.speedHeightPickup;
        double blend = 0.0;
        double response = ComputeJetPointResponse(
            body, jet, profile, static_cast<int>(index), target, clearance, blend);
        if (profile.misc.degenerateOnSlope) {
            response *= jet.pointReactionScales[index];
        }
        if (!(response > 1.0e-5)) {
            continue;
        }
        const Vec3f direction = jet.runtimeDirections[index];
        const float negativeResponse = static_cast<float>(-response);
        linear += direction * negativeResponse;
        // ComputeJetLinearAndAngularAcceleration (0x004DEA60) keeps this
        // complete scale-and-response chain in x87 until the reaction store.
        const float reaction = static_cast<float>(
            (static_cast<double>(profile.misc.slopeReaction) * blend +
             profile.misc.baseReaction) * negativeResponse);
        const Vec3f worldReaction = body.orientation.Transform(direction) * reaction;
        const Vec3f worldMoment = LegacyStoredCross(
            jet.worldProbePoints[index] - body.position, worldReaction);
        angular += body.orientation.TransformTranspose(worldMoment);
    }
    linear.x = 0.0F;
    linear.y = 0.0F;
    angular.z = 0.0F;
    return {linear, angular};
}

bool TryApplyTankJump(
    BodyState& body,
    const JetRuntime& jet,
    const TankConfiguration& tank,
    bool jumpPressed,
    InputSequence jumpSequence,
    bool& jumpConsumedForSupport,
    float& fuel,
    EntityId entity,
    SimulationTick tick,
    StepMilliseconds stepMilliseconds,
    std::vector<TraceEvent>& trace) noexcept {
    std::array<float, 4> supportWeights{};
    const float supportDistance = static_cast<float>(std::max(jet.heightNormalization, 0.001));
    float weightSum = 0.0F;
    int supportCount = 0;
    for (std::size_t index = 0; index < supportWeights.size(); ++index) {
        if (!jet.groundHitValid[index] || jet.groundClearances[index] >= supportDistance) {
            continue;
        }
        // The same behavior-controlled altitude and recovered collision-height
        // normalization used by hover define the usable probe range. A probe
        // on the surface receives full weight; a probe at the edge of the
        // range receives none. No separate terrain-height snap is introduced.
        const float normalizedClearance = std::clamp(
            static_cast<float>(jet.groundClearances[index]) / supportDistance,
            0.0F,
            1.0F);
        supportWeights[index] = 1.0F - normalizedClearance;
        if (supportWeights[index] > 0.0F) {
            weightSum += supportWeights[index];
            ++supportCount;
        }
    }

    if (!(weightSum > 0.0F)) {
        // Leaving probe/contact support starts a new support epoch. A later
        // landing can therefore accept one new rising edge, while repeated
        // presses during the same takeoff cannot create an air jump.
        jumpConsumedForSupport = false;
        return false;
    }
    if (!jumpPressed || jumpConsumedForSupport || !(tank.jumpVelocity > 0.0) ||
        !(body.mass > 0.0F)) {
        return false;
    }

    const float fuelCost = static_cast<float>(std::max(tank.jumpFuelCost, 0.0));
    if (fuel < fuelCost) {
        return false;
    }

    Vec3f localJetCenter{};
    for (const Vec3f& point : jet.localPoints) {
        localJetCenter += point;
    }
    localJetCenter *= 1.0F / static_cast<float>(jet.localPoints.size());

    Vec3f linearDelta{};
    Vec3f angularDelta{};
    const double totalImpulse =
        static_cast<double>(body.mass) * tank.jumpVelocity;
    for (std::size_t index = 0; index < supportWeights.size(); ++index) {
        if (!(supportWeights[index] > 0.0F)) {
            continue;
        }
        const Vec3f fallbackUp = body.orientation.Transform({0.0F, 0.0F, 1.0F});
        const Vec3f thrustDirection = NormalizeOr(
            body.orientation.Transform(-jet.configuredDirections[index]),
            fallbackUp);
        const double pointImpulse = totalImpulse *
            static_cast<double>(supportWeights[index] / weightSum);

        // Center the recovered jet layout around the body's origin before
        // calculating torque. Equal support on level ground then produces no
        // artificial pitch, while a slope, edge, or single supported corner
        // still produces the expected r x impulse angular response.
        const Vec3f applicationPoint = body.position + body.orientation.Transform(
            jet.localPoints[index] - localJetCenter);
        AccumulateImpulseDelta(
            body,
            applicationPoint,
            thrustDirection,
            pointImpulse,
            linearDelta,
            angularDelta);
    }

    body.linearVelocity += linearDelta;
    body.angularVelocity += angularDelta;
    fuel -= fuelCost;
    jumpConsumedForSupport = true;
    trace.push_back({
        TraceEventType::JumpAccepted,
        tick,
        entity,
        stepMilliseconds,
        supportCount,
        body.position,
        jet.groundNormal,
        linearDelta,
        fuelCost,
        static_cast<double>(jumpSequence),
    });
    return true;
}

bool PreGravityAccelerationIsSignificant(const BodyState& body) noexcept {
    float sum = body.linearAcceleration.x * body.linearAcceleration.x;
    sum += body.linearAcceleration.y * body.linearAcceleration.y;
    sum += body.linearAcceleration.z * body.linearAcceleration.z;
    sum += body.angularAcceleration.x * body.angularAcceleration.x;
    sum += body.angularAcceleration.y * body.angularAcceleration.y;
    sum += body.angularAcceleration.z * body.angularAcceleration.z;
    // 0x004F8338..0x004F8347 leaves AL set only for the ordered x87
    // comparison sum > 0.001. Earlier documentation had this predicate inverted.
    return sum > 0.001F;
}

void ApplySlopeCorrection(Vec3f& acceleration, const Vec3f& normal) noexcept {
    // The startup initializer at 0x0053A7E0 loads 0.8639379986146764,
    // calls the CRT fsin wrapper at 0x005126D0, and stores the float result
    // in the divisor read by 0x004F9C53.
    constexpr float normalization = 0.760405958F;
    const float horizontal = std::sqrt(normal.x * normal.x + normal.y * normal.y);
    if (horizontal <= 0.1F) {
        return;
    }
    const float scale = std::min(horizontal / normalization, 1.0F);
    const float scaledInverseLength = scale / horizontal;
    const float projected =
        (acceleration.y * normal.y * scaledInverseLength +
         acceleration.x * normal.x * scaledInverseLength) * scale;
    const float correction = std::fabs(projected);
    acceleration.x += normal.x * scaledInverseLength * correction;
    acceleration.y += normal.y * scaledInverseLength * correction;
}

} // namespace

struct World::Entity {
    BodyState body{};
    PhysicalProperties baselineProperties{};
    CollisionShape collisionShape{};
    JetShape jetShape{};
    JetRuntime jet{};
    float fuel = 0.0F;
    bool alive = true;
    float jetStrength = 0.0F;
    VehicleInput currentInput{};
    std::vector<InputEvent> inputs{};
    InputSequence lastProcessedInput = 0;
    SimulationTick lastContactTick = 0;
    BodyMotionType motionType = BodyMotionType::Dynamic;
    ControllerType controllerType = ControllerType::Tank;
    std::optional<TankConfiguration> vehicleConfiguration{};
    bool jumpConsumedForSupport = false;
};

FrameScheduler::FrameScheduler(std::uint32_t initialPreviousMilliseconds) noexcept
    : previousMilliseconds_(initialPreviousMilliseconds) {}

std::vector<StepMilliseconds> FrameScheduler::Advance(std::uint32_t nowMilliseconds) noexcept {
    std::uint32_t elapsed = firstTick_ ? 40U : nowMilliseconds - previousMilliseconds_;
    firstTick_ = false;
    previousMilliseconds_ = nowMilliseconds;
    std::uint32_t total = std::min(elapsed, 550U);
    const std::uint32_t count = std::min(total / 110U + 1U, 5U);
    const std::uint32_t base = total / count;
    std::vector<StepMilliseconds> result{};
    result.reserve(count);
    for (std::uint32_t index = 1; index <= count; ++index) {
        const std::uint32_t step = index == count ? total : base;
        result.push_back(step);
        if (index != count) {
            total -= base;
        }
    }
    return result;
}

World::World(PhysicsConfig config, TerrainGrid terrain)
    : config_(std::move(config)), terrain_(std::move(terrain)) {}

World::~World() = default;
World::World(World&&) noexcept = default;
World& World::operator=(World&&) noexcept = default;

bool World::CreateEntity(const EntityDefinition& definition) {
    if (definition.id == 0 || entities_.find(definition.id) != entities_.end()) {
        return false;
    }
    Entity entity{};
    entity.body = definition.initialState;
    entity.baselineProperties = definition.baselinePhysicalProperties;
    const PhysicalProperties& active = definition.activePhysicalProperties.has_value()
        ? *definition.activePhysicalProperties
        : entity.baselineProperties;
    entity.body.mass = active.mass;
    entity.body.inertia = active.inertia;
    entity.body.activeFriction = active.friction;
    entity.body.activeLinearDrag = active.linearDrag;
    entity.body.angularDrag = active.angularDrag;
    entity.collisionShape = definition.collisionShape;
    entity.jetShape = definition.jetShape;
    entity.fuel = definition.fuel;
    entity.jetStrength = definition.jetStrength;
    entity.currentInput = definition.initialInput;
    entity.lastProcessedInput = definition.lastProcessedInput;
    entity.motionType = definition.motionType;
    entity.controllerType = definition.controllerType;
    entity.alive = definition.alive;
    ApplyJetShape(entity.jet, entity.jetShape);
    entities_.emplace(definition.id, std::make_unique<Entity>(std::move(entity)));
    return true;
}

bool World::DestroyEntity(EntityId id) noexcept {
    return entities_.erase(id) != 0;
}

bool World::SetJetShape(EntityId id, const JetShape& shape) noexcept {
    const auto iterator = entities_.find(id);
    if (iterator == entities_.end()) {
        return false;
    }
    iterator->second->jetShape = shape;
    ApplyJetShape(iterator->second->jet, shape);
    return true;
}

std::optional<float> World::ResolveInitialSpawnPose(EntityId id) noexcept {
    const auto iterator = entities_.find(id);
    if (iterator == entities_.end() || !terrain_.IsValid()) {
        return std::nullopt;
    }

    Entity& entity = *iterator->second;
    BodyState& body = entity.body;
    float requiredLift = 0.0F;
    if (entity.collisionShape.vertices.empty()) {
        requiredLift = std::max(
            requiredLift,
            terrain_.Evaluate(body.position.x, body.position.y).point.z -
                body.position.z);
    } else {
        for (const Vec3f& vertex : entity.collisionShape.vertices) {
            const Vec3f worldPoint =
                body.orientation.Transform(vertex) + body.position;
            requiredLift = std::max(
                requiredLift,
                terrain_.Evaluate(worldPoint.x, worldPoint.y).point.z -
                    worldPoint.z);
        }
    }

    if (entity.controllerType != ControllerType::None) {
        const TankConfiguration& vehicle = entity.vehicleConfiguration.value_or(
            entity.controllerType == ControllerType::Scout
                ? config_.scout
                : config_.tank);
        const float targetClearance = std::max(
            0.0F,
            entity.jetStrength * static_cast<float>(vehicle.maximumAltitude));
        for (const JetShapePoint& point : entity.jetShape.points) {
            const Vec3f worldPoint =
                body.orientation.Transform(point.localPoint) + body.position;
            requiredLift = std::max(
                requiredLift,
                terrain_.Evaluate(worldPoint.x, worldPoint.y).point.z +
                    targetClearance - worldPoint.z);
        }
    }

    requiredLift = std::max(requiredLift, 0.0F);
    body.position.z += requiredLift;
    return requiredLift;
}

bool World::SetVehicleConfiguration(
    EntityId id,
    ControllerType expectedController,
    const TankConfiguration& configuration) {
    const auto found = entities_.find(id);
    if (found == entities_.end() ||
        found->second->controllerType != expectedController ||
        (found->second->controllerType != ControllerType::Tank &&
         found->second->controllerType != ControllerType::Scout)) {
        return false;
    }
    Entity& entity = *found->second;
    entity.vehicleConfiguration = configuration;
    entity.baselineProperties = DeriveTankPhysicalProperties(
        entity.collisionShape,
        configuration.density,
        configuration.baselineFriction,
        configuration.baselineLinearDrag,
        configuration.angularDrag);
    entity.body.mass = entity.baselineProperties.mass;
    entity.body.inertia = entity.baselineProperties.inertia;
    entity.body.angularDrag = entity.baselineProperties.angularDrag;
    if (entity.jetStrength == 0.0F) {
        entity.body.activeFriction = entity.baselineProperties.friction;
        entity.body.activeLinearDrag = 2.0F;
    } else {
        entity.body.activeFriction = configuration.activeJetFriction;
        entity.body.activeLinearDrag = entity.baselineProperties.linearDrag +
            static_cast<float>(configuration.jetResponseCoefficient);
    }
    entity.fuel = std::min(
        entity.fuel,
        static_cast<float>(std::max(configuration.maximumFuel, 0.0)));
    return true;
}

bool World::SubmitInput(EntityId id, const InputEvent& input) {
    auto found = entities_.find(id);
    const bool hasVehicleController = found != entities_.end() &&
        (found->second->controllerType == ControllerType::Tank ||
         found->second->controllerType == ControllerType::Scout);
    if (found == entities_.end() ||
        found->second->motionType != BodyMotionType::Dynamic ||
        !hasVehicleController ||
        input.sequence <= found->second->lastProcessedInput) {
        return false;
    }
    const auto duplicate = std::find_if(
        found->second->inputs.begin(),
        found->second->inputs.end(),
        [&input](const InputEvent& queued) { return queued.sequence == input.sequence; });
    if (duplicate != found->second->inputs.end()) {
        return false;
    }
    found->second->inputs.push_back(input);
    return true;
}

bool World::ApplyAuthoritativeMutation(EntityId id, const AuthoritativeMutation& mutation) {
    auto found = entities_.find(id);
    if (found == entities_.end()) {
        return false;
    }
    Entity& entity = *found->second;
    const BodyState snapshot = entity.body;
    if (mutation.position) entity.body.position = *mutation.position;
    if (mutation.orientation) {
        entity.body.orientation = *mutation.orientation;
        entity.body.eulerRadians = ExtractEuler(entity.body.orientation);
    }
    if (mutation.linearVelocity) entity.body.linearVelocity = *mutation.linearVelocity;
    if (mutation.angularVelocity) entity.body.angularVelocity = *mutation.angularVelocity;

    bool collides = false;
    if (mutation.position || mutation.orientation) {
        // Preserve the recovered correction gate order for pose mutations:
        // ordinary model/terrain, below-terrain center recovery, then stable
        // nearby-body enumeration. Velocity-only network updates cannot create
        // an overlap and remain valid while an already-supported body touches
        // terrain.
        ContactFeature terrainContact{};
        collides = FindModelTerrainContact(
            entity.body, entity.collisionShape, terrain_, terrainContact);
        if (!collides) {
            collides = IsBodyCenterBelowTerrain(entity.body, terrain_);
        }
        if (!collides) {
            for (const auto& [otherId, otherPointer] : entities_) {
                const Entity& other = *otherPointer;
                if (otherId != id && other.alive && BodiesOverlap(
                        entity.body, entity.collisionShape,
                        other.body, other.collisionShape)) {
                    collides = true;
                    break;
                }
            }
        }
    }
    TraceEvent event{};
    event.type = collides ? TraceEventType::CorrectionRejected : TraceEventType::CorrectionAccepted;
    event.tick = currentTick_;
    event.entity = id;
    event.point = entity.body.position;
    trace_.push_back(event);
    if (collides) {
        entity.body = snapshot;
        return false;
    }
    entity.lastProcessedInput = std::max(entity.lastProcessedInput, mutation.acknowledgedInput);
    return true;
}

bool World::RestoreAuthoritativeState(
    EntityId id,
    const BodyState& state,
    const VehicleInput& input,
    InputSequence acknowledgedInput,
    SimulationTick tick,
    std::uint64_t timeMilliseconds) noexcept {
    const auto found = entities_.find(id);
    if (found == entities_.end()) {
        return false;
    }
    Entity& entity = *found->second;
    entity.body.position = state.position;
    entity.body.linearVelocity = state.linearVelocity;
    entity.body.linearAcceleration = {};
    entity.body.eulerRadians = state.eulerRadians;
    entity.body.orientation = Matrix3d::FromEulerAngles(state.eulerRadians);
    entity.body.angularVelocity = state.angularVelocity;
    entity.body.angularAcceleration = {};
    entity.inputs.clear();
    entity.currentInput = input;
    entity.lastProcessedInput = acknowledgedInput;
    entity.jumpConsumedForSupport = input.jump != 0.0F;
    currentTick_ = tick;
    timeMilliseconds_ = timeMilliseconds;

    TraceEvent event{};
    event.type = TraceEventType::CorrectionAccepted;
    event.tick = tick;
    event.entity = id;
    event.point = entity.body.position;
    trace_.push_back(event);
    return true;
}

bool World::PutBodyToSleep(EntityId id) noexcept {
    const auto found = entities_.find(id);
    if (found == entities_.end()) {
        return false;
    }
    BodyState& body = found->second->body;
    body.linearVelocity = {};
    body.linearAcceleration = {};
    body.angularVelocity = {};
    body.angularAcceleration = {};
    return true;
}

bool World::ApplyLinearImpulse(EntityId id, const Vec3f& impulse) noexcept {
    const auto found = entities_.find(id);
    if (found == entities_.end() || found->second->motionType != BodyMotionType::Dynamic) {
        return false;
    }
    BodyState& body = found->second->body;
    if (body.mass <= 0.0F) {
        return false;
    }
    body.linearVelocity += impulse / body.mass;
    return true;
}

bool World::ConsumeFuel(EntityId id, float amount) noexcept {
    const auto found=entities_.find(id);
    if(found==entities_.end()||amount<0.0F||found->second->fuel<amount)return false;
    found->second->fuel-=amount;
    return true;
}

bool World::AddFuel(EntityId id, float amount) noexcept {
    const auto found=entities_.find(id);
    if(found==entities_.end()||amount<=0.0F)return false;
    Entity& entity=*found->second;
    const auto& vehicle=entity.controllerType==ControllerType::Scout?config_.scout:config_.tank;
    const float previous=entity.fuel;
    entity.fuel=std::min(static_cast<float>(std::max(vehicle.maximumFuel,0.0)),entity.fuel+amount);
    return entity.fuel>previous;
}

SegmentHit World::TraceSegment(
    const Vec3f& start,
    const Vec3f& end,
    EntityId ignoredEntity,
    EntityId secondIgnoredEntity) const noexcept {
    SegmentHit result{};
    const Vec3f delta = end - start;
    const float lengthSquared = LengthSquared(delta);
    if (lengthSquared <= 0.0F) {
        return result;
    }

    const auto consider = [&](const Triangle& triangle, EntityId entityId) {
        Vec3f point{};
        if (!SegmentPlaneTriangleIntersection(start, end, triangle, point)) {
            return;
        }
        const float fraction = Dot(point - start, delta) / lengthSquared;
        if (fraction < 0.0F || fraction > 1.0F ||
            (result.hit && fraction >= result.fraction)) {
            return;
        }
        result.hit = true;
        result.entity = entityId;
        result.point = point;
        result.normal = triangle.normal;
        if (Dot(result.normal, delta) > 0.0F) {
            result.normal = -result.normal;
        }
        result.fraction = fraction;
    };

    if (terrain_.IsValid()) {
        const float minimumX = std::min(start.x, end.x);
        const float maximumX = std::max(start.x, end.x);
        const float minimumY = std::min(start.y, end.y);
        const float maximumY = std::max(start.y, end.y);
        const auto maxCellX = static_cast<std::int32_t>(terrain_.CountX()) - 2;
        const auto maxCellY = static_cast<std::int32_t>(terrain_.CountY()) - 2;
        const auto firstX = std::clamp(
            static_cast<std::int32_t>(std::floor(minimumX / terrain_.SpacingX())),
            0,
            maxCellX);
        const auto lastX = std::clamp(
            static_cast<std::int32_t>(std::floor(maximumX / terrain_.SpacingX())),
            0,
            maxCellX);
        const auto firstY = std::clamp(
            static_cast<std::int32_t>(std::floor(minimumY / terrain_.SpacingY())),
            0,
            maxCellY);
        const auto lastY = std::clamp(
            static_cast<std::int32_t>(std::floor(maximumY / terrain_.SpacingY())),
            0,
            maxCellY);
        for (std::int32_t x = firstX; x <= lastX; ++x) {
            for (std::int32_t y = firstY; y <= lastY; ++y) {
                for (const Triangle& triangle : TerrainCellTriangles(terrain_, x, y)) {
                    consider(triangle, 0);
                }
            }
        }
    }

    for (const auto& [id, entityPointer] : entities_) {
        if (id == ignoredEntity || id == secondIgnoredEntity || !entityPointer->alive) {
            continue;
        }
        const Entity& entity = *entityPointer;
        for (std::size_t index = 0; index < entity.collisionShape.triangles.size(); ++index) {
            consider(WorldModelTriangle(entity.body, entity.collisionShape, index), id);
        }
    }
    return result;
}

bool World::StepWorld(SimulationTick tick, StepMilliseconds stepMilliseconds) {
    if (tick < currentTick_) {
        return false;
    }
    currentTick_ = tick;
    trace_.push_back({TraceEventType::StepBegin, tick, 0, stepMilliseconds});
    const double seconds = static_cast<double>(stepMilliseconds) / 1000.0;
    std::vector<ProbeBodySurface> bodySurfaces{};
    std::vector<StaticBodySurface> staticSurfaces{};
    bodySurfaces.reserve(entities_.size());
    staticSurfaces.reserve(entities_.size());
    for (const auto& [surfaceId, surfacePointer] : entities_) {
        if (surfacePointer->alive) {
            bodySurfaces.push_back({
                surfaceId,
                surfacePointer->body,
                &surfacePointer->collisionShape,
            });
            if (surfacePointer->motionType == BodyMotionType::Static) {
                staticSurfaces.push_back({
                    surfaceId,
                    surfacePointer->body,
                    &surfacePointer->collisionShape,
                    surfacePointer->body.activeFriction,
                });
            }
        }
    }

    for (auto& [id, entityPointer] : entities_) {
        Entity& entity = *entityPointer;
        if (entity.motionType == BodyMotionType::Static) {
            entity.body.linearAcceleration = {};
            entity.body.angularAcceleration = {};
            continue;
        }
        const IntegratedInput integrated = IntegrateInputs(
            entity.inputs,
            entity.currentInput,
            entity.lastProcessedInput,
            tick,
            timeMilliseconds_,
            stepMilliseconds);
        const VehicleInput& input = integrated.controls;
        trace_.push_back({
            TraceEventType::InputIntegrated,
            tick,
            id,
            stepMilliseconds,
            -1,
            {input.tilt, input.roll, 0.0F},
            {},
            {input.move, input.strafe, input.turn},
            input.jet,
            static_cast<double>(entity.lastProcessedInput),
        });

        BodyState& body = entity.body;
        const bool hasVehicleController =
            entity.controllerType == ControllerType::Tank ||
            entity.controllerType == ControllerType::Scout;
        const TankConfiguration& vehicle = entity.vehicleConfiguration.has_value()
            ? *entity.vehicleConfiguration
            : (entity.controllerType == ControllerType::Scout
                ? config_.scout
                : config_.tank);
        if (entity.alive && hasVehicleController) {
            bool jumpProbesUpdated = false;
            body.linearAcceleration.z += static_cast<float>(vehicle.gravityMagnitude) *
                (1.0F - static_cast<float>(vehicle.gravityPercent));
            float jet = input.jet;
            if (jet != 0.0F && jet < static_cast<float>(vehicle.minimumJetStrength)) {
                jet = static_cast<float>(vehicle.minimumJetStrength);
            }
            entity.jetStrength = jet;
            if (jet == 0.0F) {
                body.activeFriction = entity.baselineProperties.friction;
                body.activeLinearDrag = 2.0F;
                if (integrated.jumpPressed || entity.jumpConsumedForSupport) {
                    ApplyJetShape(entity.jet, entity.jetShape);
                    entity.jet.heightNormalization =
                        entity.controllerType == ControllerType::Tank
                        ? static_cast<double>(kTankCollisionGeometryHeightNormalization) +
                            vehicle.maximumAltitude
                        : static_cast<double>(
                            static_cast<float>(vehicle.maximumAltitude) +
                            kProvisionalScoutCollisionGeometryHeightNormalization);
                    UpdateJetGroundContacts(
                        entity.jet,
                        body,
                        terrain_,
                        bodySurfaces,
                        id,
                        tick,
                        stepMilliseconds,
                        trace_);
                    jumpProbesUpdated = true;
                }
            } else {
                body.activeFriction = vehicle.activeJetFriction;
                ApplyJetShape(entity.jet, entity.jetShape);
                const Vec3f forward = LocalToWorldEulerXYZ(
                    {1.0F, 0.0F, 0.0F}, body.eulerRadians);
                const float forwardSpeed = Dot(body.linearVelocity, forward);
                float speedHeightPickup = 0.0F;
                if (entity.controllerType == ControllerType::Scout &&
                    forwardSpeed > 0.0F && vehicle.maximumSpeedHeightPickup > 0.0) {
                    const float denominator =
                        static_cast<float>(vehicle.maximumVelocity) * 0.8F;
                    if (denominator > 0.0F) {
                        const float ratio = std::min(forwardSpeed / denominator, 1.0F);
                        speedHeightPickup = ratio * ratio *
                            static_cast<float>(vehicle.maximumSpeedHeightPickup);
                    }
                }
                entity.jet.speedHeightPickup = speedHeightPickup;
                entity.jet.targetHeightScale = vehicle.maximumAltitude;
                if (entity.controllerType == ControllerType::Tank) {
                    // 0x004F9E98 loads the model-derived float, adds the
                    // double maximum altitude in x87, and stores a double.
                    // Tank explicitly clears speed-height pickup at
                    // 0x004F9E81..0x004F9E86.
                    entity.jet.heightNormalization =
                        static_cast<double>(kTankCollisionGeometryHeightNormalization) +
                        vehicle.maximumAltitude;
                } else {
                    entity.jet.heightNormalization = static_cast<double>(
                        static_cast<float>(vehicle.maximumAltitude) +
                        static_cast<float>(vehicle.maximumSpeedHeightPickup) +
                        kProvisionalScoutCollisionGeometryHeightNormalization);
                }
                entity.jet.gravityReactionScale = vehicle.gravityPercent;
                entity.jet.gravityMagnitude = vehicle.gravityMagnitude;
                entity.jet.heightControlInput = entity.jetStrength;
                UpdateJetGroundContacts(
                    entity.jet,
                    body,
                    terrain_,
                    bodySurfaces,
                    id,
                    tick,
                    stepMilliseconds,
                    trace_);
                jumpProbesUpdated = true;
                entity.jet.normalizedHorizontalSpeed = std::min(
                    entity.jet.normalizedHorizontalSpeed /
                        vehicle.jetProfile.misc.maximumHorizontalSpeed,
                    1.0F);

                float moveScale = 1.0F;
                const float maximumSpeed = static_cast<float>(vehicle.maximumVelocity);
                if (input.move != 0.0F && forwardSpeed != 0.0F &&
                    std::signbit(input.move) == std::signbit(forwardSpeed) &&
                    std::fabs(forwardSpeed) > maximumSpeed) {
                    const float excess = std::min(
                        (std::fabs(forwardSpeed) - maximumSpeed) / maximumSpeed,
                        0.2F);
                    moveScale *= (0.2F - excess) / 0.2F;
                }
                if (entity.fuel < static_cast<float>(vehicle.lowFuelLevel)) {
                    const float fuelScale = 0.4F + 0.6F * entity.fuel /
                        static_cast<float>(vehicle.lowFuelLevel);
                    moveScale = std::min(moveScale, fuelScale);
                }
                body.activeLinearDrag = entity.baselineProperties.linearDrag +
                    static_cast<float>(vehicle.jetResponseCoefficient);

                const float moveAdjust = static_cast<float>(
                    input.move <= 0.0F
                        ? vehicle.moveBackwardAdjust
                        : vehicle.moveAdjust);
                Vec3f acceleration{
                    moveScale * moveAdjust * input.move,
                    moveScale * static_cast<float>(vehicle.strafeAdjust) * input.strafe,
                    0.0F,
                };
                acceleration = LocalToWorldEulerXYZ(acceleration, body.eulerRadians);
                const float accelerationLength = Length(acceleration);
                const float accelerationLimit =
                    static_cast<float>(vehicle.moveAdjust) *
                    vehicle.accelerationLimitScale;
                if (accelerationLimit < accelerationLength) {
                    acceleration *= accelerationLimit / accelerationLength;
                }
                ApplySlopeCorrection(acceleration, entity.jet.groundNormal);
                body.linearAcceleration += acceleration;
                body.angularAcceleration += WorldToLocalEulerZYX(
                    {0.0F, 0.0F, static_cast<float>(vehicle.turnAdjust) * input.turn},
                    body.eulerRadians);

                entity.jet.pitchCommandRadians = input.tilt * 1.4137167F;
                const JetMiscSettings& misc = vehicle.jetProfile.misc;
                entity.jet.rollCommand = std::clamp(
                    input.roll + vehicle.jetProfile.speedRoll.Evaluate(
                        entity.jet.normalizedHorizontalSpeed) *
                        (misc.rollTurnFactor * input.turn + misc.rollStrafeFactor * input.strafe),
                    -1.0F,
                    1.0F);
                const auto hover = ComputeHoverAcceleration(body, entity.jet, vehicle.jetProfile);
                body.linearAcceleration += hover.first;
                body.angularAcceleration += hover.second;
                trace_.push_back({
                    TraceEventType::HoverOutput,
                    tick,
                    id,
                    stepMilliseconds,
                    -1,
                    body.position,
                    entity.jet.groundNormal,
                    hover.first,
                    hover.second.x,
                    hover.second.y,
                });
            }
            if (jumpProbesUpdated) {
                TryApplyTankJump(
                    body,
                    entity.jet,
                    vehicle,
                    integrated.jumpPressed,
                    integrated.jumpSequence,
                    entity.jumpConsumedForSupport,
                    entity.fuel,
                    id,
                    tick,
                    stepMilliseconds,
                    trace_);
            }
        }

        body.preGravityAccelerationIsSignificant = PreGravityAccelerationIsSignificant(body);
        body.linearAcceleration.z -= static_cast<float>(vehicle.gravityMagnitude);
        const std::size_t traceStart = trace_.size();
        SolveAndIntegrateEnvironment(
            body,
            entity.collisionShape,
            terrain_,
            staticSurfaces,
            seconds,
            id,
            tick,
            stepMilliseconds,
            trace_,
            traceContactCandidates_,
            contactRoundRobinSeed_);
        if (std::any_of(
                trace_.begin() + static_cast<std::ptrdiff_t>(traceStart),
                trace_.end(),
                [id](const TraceEvent& event) {
                    return event.type == TraceEventType::Contact && event.entity == id;
                })) {
            entity.lastContactTick = tick;
        }
        if (entity.alive && hasVehicleController) {
            // Regenerate after one-shot costs for this step. Expressing the
            // legacy server rate per second keeps the result invariant when
            // the authoritative fixed-step duration is tuned.
            const double maximumFuel = std::max(vehicle.maximumFuel, 0.0);
            const double regeneration =
                std::max(vehicle.fuelRegenerationPerSecond, 0.0) * seconds;
            entity.fuel = static_cast<float>(std::clamp(
                static_cast<double>(entity.fuel) + regeneration,
                0.0,
                maximumFuel));
        }
        body.linearAcceleration = {};
        body.angularAcceleration = {};
    }
    timeMilliseconds_ += stepMilliseconds;
    trace_.push_back({TraceEventType::StepEnd, tick, 0, stepMilliseconds});
    return true;
}

const BodyState* World::GetBodyState(EntityId id) const noexcept {
    const auto found = entities_.find(id);
    return found == entities_.end() ? nullptr : &found->second->body;
}

BodyState* World::GetBodyState(EntityId id) noexcept {
    const auto found = entities_.find(id);
    return found == entities_.end() ? nullptr : &found->second->body;
}

Snapshot World::WriteSnapshot() const {
    Snapshot snapshot{};
    snapshot.tick = currentTick_;
    snapshot.physicsVersion = config_.semanticVersion;
    snapshot.configurationIdentity = config_.configurationIdentity;
    snapshot.terrainIdentity = terrain_.Identity();
    snapshot.entities.reserve(entities_.size());
    for (const auto& [id, entityPointer] : entities_) {
        const Entity& entity = *entityPointer;
        snapshot.entities.push_back({
            id,
            entity.body,
            entity.baselineProperties,
            entity.fuel,
            entity.jetStrength,
            entity.currentInput,
            entity.motionType,
            entity.controllerType,
            entity.alive,
            entity.lastProcessedInput,
            entity.lastContactTick,
        });
    }
    return snapshot;
}

std::vector<TraceEvent> World::DrainTraceEvents() {
    std::vector<TraceEvent> result{};
    result.swap(trace_);
    return result;
}

} // namespace wulfram::physics
