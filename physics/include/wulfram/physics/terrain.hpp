#pragma once

#include "wulfram/physics/types.hpp"

#include <cstddef>
#include <cstdint>
#include <array>
#include <string>
#include <vector>

namespace wulfram::physics {

struct TerrainHit {
    Vec3f point{};
    Vec3f normal{0.0F, 0.0F, 1.0F};
    std::int32_t cellX = 0;
    std::int32_t cellY = 0;
    std::int32_t triangle = 0;
};

class TerrainGrid {
public:
    TerrainGrid() = default;
    TerrainGrid(
        std::size_t countX,
        std::size_t countY,
        float spacingX,
        float spacingY,
        std::vector<float> heights,
        std::string identity = {});

    bool IsValid() const noexcept;
    TerrainHit Evaluate(float x, float y) const noexcept;
    float Height(std::size_t x, std::size_t y) const noexcept;
    std::size_t CountX() const noexcept { return countX_; }
    std::size_t CountY() const noexcept { return countY_; }
    float SpacingX() const noexcept { return spacingX_; }
    float SpacingY() const noexcept { return spacingY_; }
    const std::string& Identity() const noexcept { return identity_; }

private:
    std::size_t countX_ = 0;
    std::size_t countY_ = 0;
    float spacingX_ = 0.0F;
    float spacingY_ = 0.0F;
    std::vector<float> heights_{};
    std::string identity_{};
};

struct CollisionShape {
    struct HierarchyNode {
        std::vector<std::uint32_t> triangles{};
        std::int32_t negativeChild = -1;
        std::int32_t positiveChild = -1;
        float boundsRadius = 0.0F;
        Vec3f boundsExtents{};
        Vec3f boundsCenter{};
    };

    std::vector<Vec3f> vertices{};
    std::vector<std::array<std::uint32_t, 3>> triangles{};
    std::vector<HierarchyNode> hierarchy{};
    std::vector<Vec3f> samples{};
    std::size_t vertexSampleCount = 0;
    Vec3f boundsMinimum{};
    Vec3f boundsMaximum{};
    std::string identity{};

    static CollisionShape FromMesh(
        std::vector<Vec3f> vertices,
        const std::vector<std::vector<std::uint32_t>>& faces,
        std::string identity = {});
};

bool DecodeLegacyCollisionShape(
    const std::uint8_t* bytes,
    std::size_t byteCount,
    CollisionShape& shapeOut,
    std::string identity = {});

PhysicalProperties DeriveTankPhysicalProperties(
    const CollisionShape& shape,
    float density,
    float friction,
    float linearDrag,
    float angularDrag) noexcept;

} // namespace wulfram::physics
