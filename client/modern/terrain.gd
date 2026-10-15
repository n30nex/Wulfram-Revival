extends MeshInstance3D
## Original land heights and tagmap2 references, using the preserved bitmap masks.
const ShaderSource = preload("res://terrain.gdshader")
const Assets = preload("res://original_assets.gd")
const TerrainTextures = preload("res://terrain_textures.gd")
const PAGE_LAYERS := 256
var world_size := Vector2.ZERO
var error := ""
var build_msec := 0
var texture_bytes := 0
var overview: Texture2D

func build(land_path: String, assets: Assets) -> bool:
	mesh = null
	error = ""
	overview = null
	texture_bytes = 0
	var started := Time.get_ticks_msec()
	var tags_path := land_path.trim_suffix(".land") + ".tagmap2"
	if not FileAccess.file_exists(tags_path):
		return _fail("Original terrain texture table is missing.")
	var lines := FileAccess.get_file_as_string(land_path).split("\n", false)
	if lines.size() < 3:
		return _fail("Invalid terrain header.")
	var dimensions := lines[0].split("x")
	var extents := lines[1].split("x")
	if dimensions.size() != 2 or extents.size() != 2:
		return _fail("Invalid terrain dimensions.")
	var columns := int(dimensions[0])
	var rows := int(dimensions[1])
	if columns < 2 or rows < 2 or columns * rows > 262144 or lines.size() != columns * rows + 2:
		return _fail("Unsupported terrain dimensions.")
	world_size = Vector2(float(extents[0]), float(extents[1]))
	var records: Array = []
	var compositor := TerrainTextures.new()
	var materials: Array[Material] = []
	var images: Array[Image] = []
	for recipe in FileAccess.get_file_as_string(tags_path).split("\n", false):
		var result := compositor.compose(recipe, assets)
		if result.is_empty():
			return _fail(compositor.error)
		if result.has("special"):
			var thumbnail: Image = result.special.albedo_texture.get_image().duplicate()
			thumbnail.resize(4, 4, Image.INTERPOLATE_BILINEAR)
			records.append([-1, 0, result.special, thumbnail])
			continue
		var pixels: PackedByteArray = result.image.get_data()
		var thumbnail := Image.create_from_data(4, 4, false, Image.FORMAT_RGBA8, pixels.slice(pixels.size() - 84, pixels.size() - 20))
		records.append([materials.size(), images.size(), null, thumbnail])
		images.append(result.image)
		texture_bytes += result.image.get_data_size()
		if images.size() == PAGE_LAYERS:
			var page := _page_material(images)
			if page == null:
				return false
			materials.append(page)
			images.clear()
	if not images.is_empty():
		var page := _page_material(images)
		if page == null:
			return false
		materials.append(page)
	var vertices := PackedVector3Array()
	var tags := PackedInt32Array()
	for y in rows:
		for x in columns:
			var point := lines[2 + y * columns + x].strip_edges().split(" ", false)
			if point.size() != 2 or not point[0].is_valid_int() or not point[1].is_valid_float():
				return _fail("Invalid terrain cell.")
			tags.append(int(point[0]))
			vertices.append(Vector3(float(x) * world_size.x / (columns - 1), float(point[1]), -float(y) * world_size.y / (rows - 1)) * 0.1)
	var surfaces: Dictionary = {}
	var map_image := Image.create_empty((columns - 1) * 4, (rows - 1) * 4, false, Image.FORMAT_RGBA8)
	var uv := [Vector2.ZERO, Vector2.RIGHT, Vector2.DOWN, Vector2.ONE]
	for y in rows - 1:
		for x in columns - 1:
			var cell := y * columns + x
			# LAND interleaves two independent flattened streams: (W*H) vertex
			# heights and the first ((W-1)*(H-1)) quad texture IDs. Texture rows
			# therefore have W-1 entries, despite sharing lines with heights.
			var tag: int = tags[y * (columns - 1) + x]
			if tag < 0 or tag >= records.size():
				return _fail("Terrain references an unknown original texture.")
			var record: Array = records[tag]
			map_image.blit_rect(record[3], Rect2i(0, 0, 4, 4), Vector2i(x * 4, y * 4))
			var material: Material = record[2] if record[2] != null else materials[record[0]]
			if not surfaces.has(material):
				var surface := SurfaceTool.new()
				surface.begin(Mesh.PRIMITIVE_TRIANGLES)
				surface.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)
				surface.set_material(material)
				surfaces[material] = surface
			var target: SurfaceTool = surfaces[material]
			var corners := [cell, cell + 1, cell + columns, cell + columns + 1]
			# Same alternating diagonal as the authoritative original terrain.
			var triangles := [0, 2, 3, 1, 0, 3] if (((~x) ^ y) & 1) != 0 else [0, 2, 1, 3, 1, 2]
			for corner in triangles:
				target.set_uv(uv[corner])
				target.set_custom(0, Color(record[1], 0, 0, 0))
				target.set_normal(Vector3.UP)
				target.add_vertex(vertices[corners[corner]])
	mesh = ArrayMesh.new()
	for surface in surfaces.values():
		surface.commit(mesh)
	overview = ImageTexture.create_from_image(map_image)
	build_msec = Time.get_ticks_msec() - started
	return true

func _page_material(images: Array[Image]) -> ShaderMaterial:
	var tiles := Texture2DArray.new()
	if tiles.create_from_images(images) != OK:
		_fail("Could not upload original terrain textures.")
		return null
	var result := ShaderMaterial.new()
	result.shader = ShaderSource
	result.set_shader_parameter("original_tiles", tiles)
	return result

func _fail(message: String) -> bool:
	error = message
	return false
