#include "wulfram/physics/terrain.hpp"

#include <cmath>
#include <cstring>
#include <limits>
#include <utility>

namespace wulfram::physics {
namespace {

class Reader {
public:
    Reader(const std::uint8_t* bytes, std::size_t size) noexcept
        : bytes_(bytes), size_(size) {}

    bool SkipString() noexcept {
        while (offset_ < size_) {
            if (bytes_[offset_++] == 0) {
                return true;
            }
        }
        return false;
    }

    bool ReadU16(std::uint16_t& value) noexcept {
        if (size_ - offset_ < 2) return false;
        value = static_cast<std::uint16_t>(bytes_[offset_]) |
            static_cast<std::uint16_t>(bytes_[offset_ + 1] << 8U);
        offset_ += 2;
        return true;
    }

    bool ReadI32(std::int32_t& value) noexcept {
        if (size_ - offset_ < 4) return false;
        std::uint32_t bits = static_cast<std::uint32_t>(bytes_[offset_]) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 1]) << 8U) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 2]) << 16U) |
            (static_cast<std::uint32_t>(bytes_[offset_ + 3]) << 24U);
        std::memcpy(&value, &bits, sizeof(value));
        offset_ += 4;
        return true;
    }

    std::size_t Remaining() const noexcept {
        return size_ - offset_;
    }

private:
    const std::uint8_t* bytes_ = nullptr;
    std::size_t size_ = 0;
    std::size_t offset_ = 0;
};

bool ReadFixed(Reader& reader, float& value) noexcept {
    std::int32_t fixed = 0;
    if (!reader.ReadI32(fixed)) return false;
    value = static_cast<float>(fixed) / 65536.0F;
    return true;
}

bool ReadMesh(
    Reader& reader,
    std::vector<Vec3f>& vertices,
    std::vector<std::vector<std::uint32_t>>& faces) {
    std::uint16_t vertexCount = 0;
    if (!reader.ReadU16(vertexCount)) return false;
    vertices.clear();
    vertices.reserve(vertexCount);
    for (std::uint16_t index = 0; index < vertexCount; ++index) {
        Vec3f vertex{};
        if (!ReadFixed(reader, vertex.x) || !ReadFixed(reader, vertex.y) || !ReadFixed(reader, vertex.z)) {
            return false;
        }
        vertices.push_back(vertex);
    }
    std::uint16_t faceCount = 0;
    if (!reader.ReadU16(faceCount)) return false;
    faces.clear();
    faces.reserve(faceCount);
    for (std::uint16_t faceIndex = 0; faceIndex < faceCount; ++faceIndex) {
        std::uint16_t material = 0;
        std::uint16_t cornerCount = 0;
        if (!reader.ReadU16(material) || !reader.ReadU16(cornerCount)) return false;
        (void)material;
        std::vector<std::uint32_t> face{};
        face.reserve(cornerCount);
        for (std::uint16_t corner = 0; corner < cornerCount; ++corner) {
            std::uint16_t vertexIndex = 0;
            float ignoredU = 0.0F;
            float ignoredV = 0.0F;
            if (!reader.ReadU16(vertexIndex) || !ReadFixed(reader, ignoredU) || !ReadFixed(reader, ignoredV)) {
                return false;
            }
            if (vertexIndex >= vertices.size()) return false;
            face.push_back(vertexIndex);
        }
        faces.push_back(std::move(face));
    }
    std::uint16_t namedPointCount = 0;
    if (!reader.ReadU16(namedPointCount)) return false;
    for (std::uint16_t index = 0; index < namedPointCount; ++index) {
        float ignored = 0.0F;
        if (!reader.SkipString() || !ReadFixed(reader, ignored) ||
            !ReadFixed(reader, ignored) || !ReadFixed(reader, ignored)) {
            return false;
        }
    }
    return true;
}

bool ReadHierarchy(
    Reader& reader,
    const std::vector<std::vector<std::uint32_t>>& faces,
    CollisionShape& shape) {
    std::uint16_t nodeCount = 0;
    std::uint16_t referenceCount = 0;
    if (!reader.ReadU16(nodeCount) || !reader.ReadU16(referenceCount) || nodeCount == 0) {
        return false;
    }

    std::vector<std::size_t> faceTriangleStarts{};
    faceTriangleStarts.reserve(faces.size() + 1);
    std::size_t triangleCount = 0;
    for (const auto& face : faces) {
        faceTriangleStarts.push_back(triangleCount);
        if (face.size() >= 3) {
            triangleCount += face.size() - 2;
        }
    }
    faceTriangleStarts.push_back(triangleCount);

    std::vector<CollisionShape::HierarchyNode> serializedNodes{};
    serializedNodes.reserve(nodeCount);
    std::size_t referencesRead = 0;
    for (std::uint16_t nodeIndex = 0; nodeIndex < nodeCount; ++nodeIndex) {
        std::int32_t ignoredPlaneDistance = 0;
        std::uint16_t positiveChild = 0;
        std::uint16_t negativeChild = 0;
        std::uint16_t firstFaceCount = 0;
        std::uint16_t secondFaceCount = 0;
        if (!reader.ReadI32(ignoredPlaneDistance) ||
            !reader.ReadU16(positiveChild) || !reader.ReadU16(negativeChild) ||
            !reader.ReadU16(firstFaceCount) || !reader.ReadU16(secondFaceCount)) {
            return false;
        }
        (void)ignoredPlaneDistance;

        CollisionShape::HierarchyNode node{};
        node.negativeChild = negativeChild == 0xffffU
            ? -1 : static_cast<std::int32_t>(negativeChild);
        node.positiveChild = positiveChild == 0xffffU
            ? -1 : static_cast<std::int32_t>(positiveChild);
        if (node.negativeChild >= nodeCount || node.positiveChild >= nodeCount) {
            return false;
        }
        const std::size_t nodeFaceCount =
            static_cast<std::size_t>(firstFaceCount) + secondFaceCount;
        if (nodeFaceCount > reader.Remaining() / 2) return false;
        for (std::size_t faceOffset = 0; faceOffset < nodeFaceCount; ++faceOffset) {
            std::uint16_t faceIndex = 0;
            if (!reader.ReadU16(faceIndex) || faceIndex >= faces.size()) return false;
            const std::size_t triangleBegin = faceTriangleStarts[faceIndex];
            const std::size_t triangleEnd = faceTriangleStarts[faceIndex + 1];
            for (std::size_t triangleIndex = triangleBegin;
                 triangleIndex < triangleEnd;
                 ++triangleIndex) {
                node.triangles.push_back(static_cast<std::uint32_t>(triangleIndex));
            }
        }
        referencesRead += nodeFaceCount;
        serializedNodes.push_back(std::move(node));
    }
    if (referencesRead != referenceCount) return false;

    // CompileCollisionHierarchyNodeDepthFirst (0x00502780) does not preserve
    // serialized node indices. It emits the current node, then its serialized
    // +0x04 child, then its +0x06 child, assigning new runtime indices as it
    // descends. The collision traversal consumes those compiled indices.
    std::vector<std::size_t> compiledToSerialized{};
    compiledToSerialized.reserve(nodeCount);
    std::vector<bool> visited(nodeCount, false);
    std::vector<std::size_t> pending{0};
    while (!pending.empty()) {
        const std::size_t sourceIndex = pending.back();
        pending.pop_back();
        if (sourceIndex >= serializedNodes.size() || visited[sourceIndex]) return false;
        visited[sourceIndex] = true;
        compiledToSerialized.push_back(sourceIndex);
        const CollisionShape::HierarchyNode& source = serializedNodes[sourceIndex];
        // Push in reverse visit order because this is a LIFO stack.
        if (source.negativeChild >= 0) {
            pending.push_back(static_cast<std::size_t>(source.negativeChild));
        }
        if (source.positiveChild >= 0) {
            pending.push_back(static_cast<std::size_t>(source.positiveChild));
        }
    }
    if (compiledToSerialized.size() != nodeCount) return false;

    std::vector<std::int32_t> serializedToCompiled(nodeCount, -1);
    for (std::size_t compiledIndex = 0; compiledIndex < nodeCount; ++compiledIndex) {
        serializedToCompiled[compiledToSerialized[compiledIndex]] =
            static_cast<std::int32_t>(compiledIndex);
    }
    shape.hierarchy.clear();
    shape.hierarchy.reserve(nodeCount);
    for (const std::size_t sourceIndex : compiledToSerialized) {
        CollisionShape::HierarchyNode node = std::move(serializedNodes[sourceIndex]);
        if (node.negativeChild >= 0) {
            node.negativeChild = serializedToCompiled[static_cast<std::size_t>(node.negativeChild)];
        }
        if (node.positiveChild >= 0) {
            node.positiveChild = serializedToCompiled[static_cast<std::size_t>(node.positiveChild)];
        }
        shape.hierarchy.push_back(std::move(node));
    }

    // FinalizeCollisionHierarchyNodeBounds (0x00502650) runs after both
    // children have been compiled. Its conservative subtree AABB is consumed
    // by FUN_004FFAE0 before a node's splitting plane or triangles are tested.
    for (std::size_t reverseIndex = shape.hierarchy.size(); reverseIndex-- > 0;) {
        CollisionShape::HierarchyNode& node = shape.hierarchy[reverseIndex];
        Vec3f minimum{
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
            std::numeric_limits<float>::max(),
        };
        Vec3f maximum{
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
            std::numeric_limits<float>::lowest(),
        };
        const auto includePoint = [&minimum, &maximum](const Vec3f& point) {
            minimum.x = std::min(minimum.x, point.x);
            minimum.y = std::min(minimum.y, point.y);
            minimum.z = std::min(minimum.z, point.z);
            maximum.x = std::max(maximum.x, point.x);
            maximum.y = std::max(maximum.y, point.y);
            maximum.z = std::max(maximum.z, point.z);
        };
        for (const std::uint32_t triangleIndex : node.triangles) {
            if (triangleIndex >= shape.triangles.size()) continue;
            const auto& triangle = shape.triangles[triangleIndex];
            includePoint(shape.vertices[triangle[0]]);
            includePoint(shape.vertices[triangle[1]]);
            includePoint(shape.vertices[triangle[2]]);
        }
        const auto includeChild = [&shape, &includePoint](std::int32_t childIndex) {
            if (childIndex < 0 || static_cast<std::size_t>(childIndex) >= shape.hierarchy.size()) return;
            const CollisionShape::HierarchyNode& child =
                shape.hierarchy[static_cast<std::size_t>(childIndex)];
            includePoint(child.boundsCenter - child.boundsExtents);
            includePoint(child.boundsCenter + child.boundsExtents);
        };
        includeChild(node.positiveChild);
        includeChild(node.negativeChild);
        node.boundsCenter = (minimum + maximum) * 0.5F;
        node.boundsExtents = (maximum - minimum) * 0.5F;
        node.boundsRadius = static_cast<float>(std::sqrt(
            static_cast<double>(node.boundsExtents.x) * node.boundsExtents.x +
            static_cast<double>(node.boundsExtents.y) * node.boundsExtents.y +
            static_cast<double>(node.boundsExtents.z) * node.boundsExtents.z));
    }
    return true;
}

} // namespace

bool DecodeLegacyCollisionShape(
    const std::uint8_t* bytes,
    std::size_t byteCount,
    CollisionShape& shapeOut,
    std::string identity) {
    if (bytes == nullptr || byteCount == 0) return false;
    Reader reader(bytes, byteCount);
    if (!reader.SkipString()) return false;
    std::uint16_t materialCount = 0;
    if (!reader.ReadU16(materialCount)) return false;
    for (std::uint16_t index = 0; index < materialCount; ++index) {
        if (!reader.SkipString()) return false;
    }
    std::vector<Vec3f> vertices{};
    std::vector<std::vector<std::uint32_t>> faces{};
    if (!ReadMesh(reader, vertices, faces)) return false;
    // The first mesh is the visible/basic stream. The second is the selected
    // collision mesh consumed by the original model assignment path.
    if (!ReadMesh(reader, vertices, faces) || vertices.empty()) return false;
    shapeOut = CollisionShape::FromMesh(std::move(vertices), faces, std::move(identity));
    if (!ReadHierarchy(reader, faces, shapeOut)) return false;
    return !shapeOut.vertices.empty() && !shapeOut.triangles.empty();
}

PhysicalProperties DeriveTankPhysicalProperties(
    const CollisionShape& shape,
    float density,
    float friction,
    float linearDrag,
    float angularDrag) noexcept {
    const Vec3f extents = shape.boundsMaximum - shape.boundsMinimum;
    const float xSquared = extents.x * extents.x;
    const float ySquared = extents.y * extents.y;
    const float zSquared = extents.z * extents.z;
    PhysicalProperties result{};
    result.mass = extents.x * extents.y * extents.z * density;
    result.inertia = {
        result.mass * ySquared * zSquared / 12.0F,
        result.mass * xSquared * zSquared / 12.0F,
        result.mass * xSquared * ySquared / 12.0F,
    };
    result.friction = friction;
    result.linearDrag = linearDrag;
    result.angularDrag = angularDrag;
    return result;
}

} // namespace wulfram::physics
