extends SceneTree
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")
const TerrainTextures = preload("res://terrain_textures.gd")

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
		return ImageTexture.create_from_image(image_cache[archive + "/" + name])
	func _read(archive: String, name: String) -> PackedByteArray:
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
	var assets := FixtureAssets.new(fixture)
	var compositor := TerrainTextures.new()
	var result := compositor.compose("+0template unknown001 14 0template canyon001 13 0template 4sand001 3", assets)
	assert(not result.is_empty(), compositor.error)
	assert(_hash(result.image.get_data()) == fixture.composed_sha256, "Original binary masks/mips or base-family selection changed")
	for name in fixture.images:
		assert(assets.image_cache["landscape/" + name].get_data() == fixture.images[name].hex_decode(), "Composition modified a source bitmap")
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
