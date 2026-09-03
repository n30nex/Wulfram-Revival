#include "wulfram/physics/terrain.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

namespace wulfram::physics {

TerrainGrid::TerrainGrid(
    std::size_t countX,
    std::size_t countY,
    float spacingX,
    float spacingY,
    std::vector<float> heights,
    std::string identity)
    : countX_(countX),
      countY_(countY),
      spacingX_(spacingX),
      spacingY_(spacingY),
      heights_(std::move(heights)),
      identity_(std::move(identity)) {}

bool TerrainGrid::IsValid() const noexcept {
    return countX_ >= 2 && countY_ >= 2 && spacingX_ > 0.0F && spacingY_ > 0.0F &&
        heights_.size() == countX_ * countY_;
}

float TerrainGrid::Height(std::size_t x, std::size_t y) const noexcept {
    if (!IsValid()) {
        return 0.0F;
    }
    x = std::min(x, countX_ - 1);
    y = std::min(y, countY_ - 1);
    return heights_[x * countY_ + y];
}

TerrainHit TerrainGrid::Evaluate(float x, float y) const noexcept {
    TerrainHit result{};
    if (!IsValid()) {
        result.point = {x, y, 0.0F};
        return result;
    }

    // MapWorldPointToTerrainCellClamped (0x004F0010) multiplies by the
    // grid's stored float reciprocal and converts the still-extended x87
    // result to an integer. At exact-looking float cell boundaries, rounding
    // the product back to float first can select the neighboring cell and
    // therefore a different terrain normal.
    const float inverseSpacingX = 1.0F / spacingX_;
    const float inverseSpacingY = 1.0F / spacingY_;
    const double cellXValue = static_cast<double>(x) * inverseSpacingX;
    const double cellYValue = static_cast<double>(y) * inverseSpacingY;
    const auto maximumX = static_cast<std::int32_t>(countX_ - 2);
    const auto maximumY = static_cast<std::int32_t>(countY_ - 2);
    const std::int32_t ix = std::clamp(static_cast<std::int32_t>(cellXValue), 0, maximumX);
    const std::int32_t iy = std::clamp(static_cast<std::int32_t>(cellYValue), 0, maximumY);
    const float x0 = static_cast<float>(ix) * spacingX_;
    const float y0 = static_cast<float>(iy) * spacingY_;
    const float x1 = x0 + spacingX_;
    const float y1 = y0 + spacingY_;
    const Vec3f v00{x0, y0, Height(static_cast<std::size_t>(ix), static_cast<std::size_t>(iy))};
    const Vec3f v10{x1, y0, Height(static_cast<std::size_t>(ix + 1), static_cast<std::size_t>(iy))};
    const Vec3f v01{x0, y1, Height(static_cast<std::size_t>(ix), static_cast<std::size_t>(iy + 1))};
    const Vec3f v11{x1, y1, Height(static_cast<std::size_t>(ix + 1), static_cast<std::size_t>(iy + 1))};
    Vec3f a{};
    Vec3f b{};
    Vec3f c{};
    std::int32_t triangle = 0;

    const std::int32_t parity = ((~ix) ^ iy) & 1;
    if (parity != 0) {
        if ((y - y0) - (x - x0) < 0.0F) {
            a = v00;
            b = v10;
            c = v11;
        } else {
            a = v01;
            b = v00;
            c = v11;
            triangle = 1;
        }
    } else if ((y - y0) - (x1 - x) < 0.0F) {
        a = v01;
        b = v00;
        c = v10;
    } else {
        a = v10;
        b = v11;
        c = v01;
        triangle = 1;
    }

    // CalculateSelectedTerrainTriangleHeightAndNormal (0x004FA050), through
    // its normalized-plane helper at 0x0045F220, keeps the selected triangle's
    // cross product, normalized coefficients, plane offset, and height solve
    // above float precision. Its coefficient outputs are stored as doubles;
    // only the returned normal and height are rounded to floats. Keeping that
    // boundary matters on sloped terrain because hover feedback amplifies an
    // otherwise tiny early float-rounding difference. The original x87
    // temporaries have greater precision than portable double on some builds,
    // but double preserves the observed storage boundary without requiring an
    // architecture-specific arithmetic implementation.
    const double cbx = static_cast<double>(c.x) - b.x;
    const double cby = static_cast<double>(c.y) - b.y;
    const double cbz = static_cast<double>(c.z) - b.z;
    const double abx = static_cast<double>(a.x) - b.x;
    const double aby = static_cast<double>(a.y) - b.y;
    const double abz = static_cast<double>(a.z) - b.z;
    const double planeX = cby * abz - cbz * aby;
    const double planeY = cbz * abx - cbx * abz;
    const double planeZ = cbx * aby - cby * abx;
    const double planeLength = std::sqrt(
        planeX * planeX + planeY * planeY + planeZ * planeZ);
    const double normalX = planeLength > 0.0 ? planeX / planeLength : 0.0;
    const double normalY = planeLength > 0.0 ? planeY / planeLength : 0.0;
    const double normalZ = planeLength > 0.0 ? planeZ / planeLength : 1.0;
    const double planeOffset = -(
        static_cast<double>(a.x) * normalX +
        static_cast<double>(a.y) * normalY +
        static_cast<double>(a.z) * normalZ);
    const float height = std::fabs(normalZ) > std::numeric_limits<double>::epsilon()
        ? static_cast<float>(-((static_cast<double>(x) * normalX + planeOffset) +
              static_cast<double>(y) * normalY) / normalZ)
        : a.z;
    const Vec3f normal{
        static_cast<float>(normalX),
        static_cast<float>(normalY),
        static_cast<float>(normalZ),
    };
    result.point = {x, y, height};
    result.normal = normal.z < 0.0F ? -normal : normal;
    result.cellX = ix;
    result.cellY = iy;
    result.triangle = triangle;
    return result;
}

CollisionShape CollisionShape::FromMesh(
    std::vector<Vec3f> vertices,
    const std::vector<std::vector<std::uint32_t>>& faces,
    std::string identity) {
    CollisionShape result{};
    result.vertices = vertices;
    result.vertexSampleCount = vertices.size();
    result.samples = vertices;
    result.identity = std::move(identity);
    if (!vertices.empty()) {
        result.boundsMinimum = vertices.front();
        result.boundsMaximum = vertices.front();
        for (const Vec3f& vertex : vertices) {
            result.boundsMinimum.x = std::min(result.boundsMinimum.x, vertex.x);
            result.boundsMinimum.y = std::min(result.boundsMinimum.y, vertex.y);
            result.boundsMinimum.z = std::min(result.boundsMinimum.z, vertex.z);
            result.boundsMaximum.x = std::max(result.boundsMaximum.x, vertex.x);
            result.boundsMaximum.y = std::max(result.boundsMaximum.y, vertex.y);
            result.boundsMaximum.z = std::max(result.boundsMaximum.z, vertex.z);
        }
    }
    std::set<std::pair<std::uint32_t, std::uint32_t>> edges{};
    for (const auto& face : faces) {
        if (face.empty()) {
            continue;
        }
        Vec3f centroid{};
        std::size_t validCorners = 0;
        for (std::size_t corner = 0; corner < face.size(); ++corner) {
            const std::uint32_t a = face[corner];
            const std::uint32_t b = face[(corner + 1) % face.size()];
            if (a >= vertices.size()) {
                continue;
            }
            centroid += vertices[a];
            ++validCorners;
            if (b < vertices.size()) {
                const auto edge = std::minmax(a, b);
                if (edges.emplace(edge.first, edge.second).second) {
                    result.samples.push_back((vertices[a] + vertices[b]) * 0.5F);
                }
            }
        }
        if (face.size() >= 3) {
            for (std::size_t corner = 1; corner + 1 < face.size(); ++corner) {
                if (face[0] < vertices.size() && face[corner] < vertices.size() &&
                    face[corner + 1] < vertices.size()) {
                    result.triangles.push_back({face[0], face[corner], face[corner + 1]});
                }
            }
        }
        if (validCorners != 0) {
            result.samples.push_back(centroid / static_cast<float>(validCorners));
        }
    }
    return result;
}

} // namespace wulfram::physics
