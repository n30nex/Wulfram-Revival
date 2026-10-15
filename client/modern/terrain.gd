extends MeshInstance3D
## Original land heights and tagmap2 references, using the preserved bitmap masks.
const ShaderSource = preload("res://terrain.gdshader")
const Assets = preload("res://original_assets.gd")
var world_size := Vector2.ZERO
var error := ""

func build(land_path: String, assets: Assets) -> bool:
	mesh = null
	error = ""
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
	var indices: Dictionary = {}
	var images: Array[Image] = []
	for recipe in FileAccess.get_file_as_string(tags_path).split("\n", false):
		var tokens := recipe.strip_edges().trim_prefix("+").split(" ", false)
		var layers := Color(0, 0, 0, 0)
		var masks := Color(0, 0, 0, 0)
		var special: StandardMaterial3D = null
		var count := tokens.size() / 3 if recipe.begins_with("+") else 1
		if count < 1 or count > 4 or (recipe.begins_with("+") and tokens.size() % 3 != 0):
			return _fail("Unsupported terrain composition.")
		for slot in int(count):
			var name: String = tokens[slot * 3 + 1] if recipe.begins_with("+") else tokens[0]
			var key := name.to_lower()
			if not indices.has(key):
				var archive := "landscape" if assets._names.landscape.has(key) else "base" if assets._names.base.has(key) else "res_640x480"
				if assets.texture(name, archive) == null:
					return _fail("Missing original terrain texture: " + name)
				var image: Image = assets.image_cache[archive + "/" + key]
				if image.get_size() != Vector2i(128, 128) or not image.has_mipmaps():
					if count != 1:
						return _fail("Unsupported mixed bitmap dimensions: " + name)
					# Preserve a non-square/non-mipped original at its own size.
					# Mayhem references a UI bitmap as a standalone terrain tile.
					special = assets.material(name, archive)
					break
				indices[key] = images.size()
				images.append(image)
			layers[slot] = indices[key]
			masks[slot] = 15 ^ int(tokens[slot * 3 + 2]) if recipe.begins_with("+") else 15
			if masks[slot] < 0 or masks[slot] > 15:
				return _fail("Invalid original terrain mask.")
		records.append([layers, masks, special])
	var tiles := Texture2DArray.new()
	if images.is_empty() or tiles.create_from_images(images) != OK:
		return _fail("Could not load the original terrain textures.")
	var mask_images: Array[Image] = []
	# Retail table at 0x577008 maps file suffixes to coverage bits.
	const PERMUTATION := [0, 1, 3, 2, 5, 10, 4, 12, 8, 14, 13, 11, 7, 9, 6, 15]
	for mask in 16:
		var pixels := PackedByteArray()
		if mask in [0, 15]:
			pixels.resize(21845)
			pixels.fill(255 if mask == 15 else 0)
		else:
			var bytes := assets._read("base", "1template%03d" % PERMUTATION.find(mask))
			if bytes.size() != 21848:
				return _fail("Missing original terrain blend mask.")
			pixels = bytes.slice(3)
		mask_images.append(Image.create_from_data(128, 128, true, Image.FORMAT_R8, pixels))
	var mask_texture := Texture2DArray.new()
	if mask_texture.create_from_images(mask_images) != OK:
		return _fail("Could not load terrain blend masks.")
	var vertices := PackedVector3Array()
	var tags := PackedInt32Array()
	for y in rows:
		for x in columns:
			var point := lines[2 + y * columns + x].strip_edges().split(" ", false)
			if point.size() != 2 or not point[0].is_valid_int() or not point[1].is_valid_float():
				return _fail("Invalid terrain cell.")
			tags.append(int(point[0]))
			vertices.append(Vector3(float(x) * world_size.x / (columns - 1), float(point[1]), -float(y) * world_size.y / (rows - 1)) * 0.1)
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	surface.set_custom_format(0, SurfaceTool.CUSTOM_RGBA_FLOAT)
	surface.set_custom_format(1, SurfaceTool.CUSTOM_RGBA_FLOAT)
	var special_surfaces: Dictionary = {}
	var uv := [Vector2.ZERO, Vector2.RIGHT, Vector2.DOWN, Vector2.ONE]
	for y in rows - 1:
		for x in columns - 1:
			var cell := y * columns + x
			if tags[cell] < 0 or tags[cell] >= records.size():
				return _fail("Terrain references an unknown original texture.")
			var record: Array = records[tags[cell]]
			var target: SurfaceTool = surface
			if record[2] != null:
				if not special_surfaces.has(record[2]):
					var extra := SurfaceTool.new()
					extra.begin(Mesh.PRIMITIVE_TRIANGLES)
					extra.set_material(record[2])
					special_surfaces[record[2]] = extra
				target = special_surfaces[record[2]]
			var corners := [cell, cell + 1, cell + columns, cell + columns + 1]
			# Same alternating diagonal as the authoritative original terrain.
			var triangles := [0, 2, 3, 1, 0, 3] if (((~x) ^ y) & 1) != 0 else [0, 2, 1, 3, 1, 2]
			for corner in triangles:
				target.set_uv(uv[corner])
				if record[2] == null:
					target.set_custom(0, record[0])
					target.set_custom(1, record[1])
				target.set_normal(Vector3.UP)
				target.add_vertex(vertices[corners[corner]])
	mesh = surface.commit()
	var material := ShaderMaterial.new()
	material.shader = ShaderSource
	material.set_shader_parameter("original_tiles", tiles)
	material.set_shader_parameter("original_masks", mask_texture)
	mesh.surface_set_material(0, material)
	for extra in special_surfaces.values():
		extra.commit(mesh)
	return true

func _fail(message: String) -> bool:
	error = message
	return false
