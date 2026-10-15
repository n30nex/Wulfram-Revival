extends SceneTree
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")
const TerrainTextures = preload("res://terrain_textures.gd")

class BitmapAssets extends Assets:
	var bytes := PackedByteArray([131, 2, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
	func _init(palette: PackedByteArray) -> void:
		_palette = palette
	func _read(_archive: String, _name: String) -> PackedByteArray:
		return bytes

class FixtureAssets:
	extends OriginalAssets
	var fixture: Dictionary
	func _init(data: Dictionary) -> void:
		fixture = data
		_palette = fixture.palette.hex_decode()
		_names = {"landscape": {}, "base": {}, "res_640x480": {}}
		for name in fixture.images:
			_names.landscape[name] = name
			image_cache["landscape/" + name] = Image.create_from_data(128, 128, true, Image.FORMAT_RGBA8, fixture.images[name].hex_decode())
		for index in 6:
			var name := "quad%d" % index
			_names.landscape[name] = name
			var image := Image.create_empty(128, 128, false, Image.FORMAT_RGBA8)
			image.fill(Color(float(index) / 6.0, 0.0, 1.0))
			image.generate_mipmaps()
			image_cache["landscape/" + name] = image
	func texture(name: String, archive := "base") -> Texture2D:
		return ImageTexture.create_from_image(image_cache.get(archive + "/" + name, image_cache.get("landscape/" + name)))
	func _read(archive: String, name: String) -> PackedByteArray:
		if archive == "shapes":
			return fixture.model.hex_decode()
		if archive == "stripmaps2":
			var data: PackedByteArray = fixture.strip.hex_decode()
			if name == "truncated":
				data.resize(data.size() - 1)
			elif name == "inferred":
				data.encode_u16(4, 0)
				data.encode_u16(6, 0)
			return data
		return fixture.masks.get(name, "").hex_decode()

func _hash(data: PackedByteArray) -> String:
	var context := HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(data)
	return context.finish().hex_encode()

func _init() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json")).original_formats
	var bitmap := BitmapAssets.new(fixture.palette.hex_decode())
	var encoded := bitmap.bytes.duplicate()
	assert(bitmap.texture("mips") != null)
	assert(bitmap.bytes == encoded, "Import changed stored palette indices")
	var decoded: PackedByteArray = bitmap.image_cache["base/mips"].get_data()
	var expected := PackedByteArray()
	# On disk: one 1x1 pixel, four 2x2 pixels, then sixteen 4x4 pixels.
	for source in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3, 4, 0]:
		expected.append_array(PackedByteArray([source, 255 - source, source * 3, 0 if source == 0 else 255]))
	assert(decoded == expected, "Original stored mip order differs from Godot's base-first packing")
	bitmap.bytes.resize(bitmap.bytes.size() - 1)
	assert(bitmap.texture("truncated") == null)
	bitmap.bytes = PackedByteArray([129, 2, 0, 1, 0, 0, 0, 0, 0, 0, 7])
	assert(bitmap.texture("standalone") != null)
	assert(bitmap.image_cache["base/standalone"].get_data() == PackedByteArray([0, 255, 0, 0, 7, 248, 21, 255]))
	var assets := FixtureAssets.new(fixture)
	var compositor := TerrainTextures.new()
	var result := compositor.compose("+0template unknown001 14 0template canyon001 13 0template 4sand001 3", assets)
	assert(not result.is_empty(), compositor.error)
	assert(_hash(result.image.get_data()) == fixture.composed_sha256, "Original binary masks/mips or base-family selection changed")
	for name in fixture.images:
		assert(assets.image_cache["landscape/" + name].get_data() == fixture.images[name].hex_decode(), "Composition modified a source bitmap")
	var model := assets.model("fixture")
	assert(not model.is_empty())
	var face: Array = model.mesh.surface_get_arrays(0)
	for normal in face[Mesh.ARRAY_NORMAL]:
		assert(normal.dot(Vector3.UP) > .99, "Original model exterior faces were imported inside out")
	for index in face[Mesh.ARRAY_VERTEX].size():
		var position: Vector3 = face[Mesh.ARRAY_VERTEX][index]
		assert(face[Mesh.ARRAY_TEX_UV][index].distance_to(Vector2(position.x, -position.z) * 10) < .00001, "Face orientation correction changed UV bindings")
	for name in ["normal", "inferred"]:
		assert(assets.stripmap(name) != null)
		assert(_hash(assets.image_cache["stripmaps2/" + name].get_data()) == fixture.strip_sha256, "Strip positions, palette or transparency changed")
	assert(assets.stripmap("truncated") == null)
	# A non-square grid separates vertex stride from quad stride. Tail IDs are
	# deliberately invalid: the retail reader discards them, not terrain heights.
	var land := "4x3\n30x20\n"
	for index in 12:
		land += "%d %d\n" % [index if index < 6 else 99, 100 + index]
	var path := "user://format-check.land"
	var file := FileAccess.open(path, FileAccess.WRITE)
	file.store_string(land)
	file.close()
	file = FileAccess.open("user://format-check.tagmap2", FileAccess.WRITE)
	file.store_string("quad0\nquad1\nquad2\nquad3\nquad4\nquad5\n")
	file.close()
	var terrain := Terrain.new()
	var valid := terrain.build(path, assets)
	DirAccess.remove_absolute(ProjectSettings.globalize_path(path))
	DirAccess.remove_absolute(ProjectSettings.globalize_path("user://format-check.tagmap2"))
	assert(valid, terrain.error)
	var arrays := terrain.mesh.surface_get_arrays(0)
	var vertices: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var indices: PackedFloat32Array = arrays[Mesh.ARRAY_CUSTOM0]
	assert(vertices.size() == 36)
	for quad in 6:
		assert(indices[quad * 6 * 4] == quad, "Quad texture stride differs from the original")
	assert(vertices[24].distance_to(Vector3(1, 10.5, -1)) < .00001, "Texture correction shifted terrain heights")
	assert(terrain.overview.get_size() == Vector2(12, 8))
	terrain.free()
	print("MODERN_ORIGINAL_FORMATS=PASS")
	quit()
