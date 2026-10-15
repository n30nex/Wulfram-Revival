# Original graphics format evidence

Reference executable: Wulfram II 2.1.5B, SHA-256
`94990864ab1db2ddbe2652cfdbca726356b19dd3fb7597945e297a43973d99d4`.
The following describes recovered file/renderer behavior; the executable and
original artwork are not included in this repository.

## Model exterior faces

The original visual meshes wind exterior faces counter-clockwise. The coordinate
rotation `(x, y, z) -> (x, z, -y)` preserves handedness, while Godot's SurfaceTool
uses clockwise fronts. Import triangles as `(0, next, current)` rather than
`(0, current, next)`. This restores exterior surfaces and outward generated
normals without changing original vertex positions, UV associations or textures.
The earlier winding exposed interiors and hid top panels. A synthetic original
+Z face is required to retain an outward +Y normal and its UV bindings after
import. That regression failed before the correction and passes afterward.
`check_models.gd` captures a fixed original repair/refuel/Tank/Scout gallery.

## LAND contains independent streams

Each line after the dimensions/extents contains a texture ID and a vertex
height, but these are **different flattened arrays**. Heights contain W*H
vertices. Only the first (W-1)*(H-1) texture IDs belong to terrain squares;
remaining texture fields are padding. Vertex rows have W entries; texture rows
have W-1. The native physics height grid is unchanged by the renderer correction.

The reader at `0x4ef91a` allocates the smaller texture array. At `0x4ef9b7` it
continues assigning vertex heights while stopping texture writes at that count.
The writer independently computes the smaller count at `0x42cf87` and writes
padding after it. Crossroads' 129x129 LAND has 16,384 square IDs and 257 padded
texture fields. Using the vertex stride for textures shifted road and structure
materials farther out of alignment on successive rows.

## Compose before filtering

The `tagmap2` reader at `0x465e90` reads up to four triples and XORs stored corner
coverage with 15. Its first token is discarded. `0x465c70` calls `0x49cc50`, which
chooses the first highest-priority registered texture family as the base and
selects that family's mask bank. The recovered family registry at `0x49cf20`
assigns priority 1 to every registered family; bank choices are preserved in
`terrain_textures.gd`. `0x577008` maps mask filename suffixes to corner coverage.

`0x4663e0` starts from the chosen base and composites other layers in recipe
order, separately at every stored mip level. Its inner operation at `0x466480`
is `(source & mask) | (destination & ~mask)` on palette bytes. Masks are binary
0/255. Copying complete palette-derived RGBA pixels with those binary masks is
equivalent, and lets Godot filter the finished image. Blending independently
filtered layers changes the seams and mip appearance.

Completed images are uploaded in pages of 256 array layers, requiring one
texture sample per terrain fragment. Crossroads' 4,227 records use 369,355,260
uncompressed RGBA texture bytes including original mips. Local GTX 1060 builds
take about 3.3 seconds. Other hardware, broad scene performance and full visual
parity remain unqualified.

The retail family selector may randomly choose another original variant when
loading a map. This client currently retains the variant names recorded in
`tagmap2`. Random variant/seed behavior remains a comparison item; no synthesized
or recolored textures are used. Skies, decorative assets and effects also remain
open fidelity work.

## Stripped cockpit/menu artwork

`stripmaps2.zip` entries contain little-endian strip count (u32), declared width
and height (u16 each), palette-byte count (u32), that many palette bytes, then
one `(x, y, length)` u16 triple per strip. Pixels follow strip order; gaps are
transparent. Zero dimensions in the two square borders are inferred from run
bounds. Declared lengths, total pixels and bounds are checked before decoding.

All ten preserved entries decode. The cockpit's 640x480 RGBA pixel hash matches
an independent decoder:
`31b0f57425fe8c53693292852ab2297c3e4fa0ba0d9b6c5fd0160387f9508c93`.
The source frame is split across its empty central area for widescreen layout;
radar and map frames retain their proportions. Terrain overview pixels come
from the completed original 4x4 stored mips, with a rotating local radar and
clickable tactical map sharing marker coordinates with input.

`check_original_formats.gd` uses independent Python byte fixtures to check all
eight composed mip levels, source-image immutability, palette/strip transparency,
inferred bounds, truncation rejection, non-square LAND texture/height strides,
and overview dimensions. `check_reference.gd` renders a fixed Crossroads pose
without a network connection. GPU GUI checks verify scaled login/team/map clicks
and long-status containment; they do not certify physical mouse/DPI operation.
