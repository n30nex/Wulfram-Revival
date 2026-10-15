extends SceneTree
const OriginalSky = preload("res://original_sky.gd")
const Assets = preload("res://original_assets.gd")

class FixtureAssets extends Assets:
	func _init() -> void:
		_names = {"skies": {}}
		for index in range(1, 33):
			_names.skies["fixture%03d" % index] = "fixture"
	func texture(_name: String, _archive := "base") -> Texture2D:
		var pixels := Image.create_empty(1, 1, false, Image.FORMAT_RGBA8)
		pixels.fill(Color.WHITE)
		return ImageTexture.create_from_image(pixels)

func _init() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://sky-fixture.json"))
	var dimensions := Vector2(fixture.world_size[0], fixture.world_size[1])
	var actual := OriginalSky.quads(dimensions)
	assert(actual.size() == 32 and fixture.quads.size() == 32)
	var tiles: Dictionary = {}
	var centre := Vector3(dimensions.x * .5, dimensions.y * .5, 100)
	for index in actual.size():
		var quad: Dictionary = actual[index]
		var reference: Dictionary = fixture.quads[index]
		assert(quad.tile == int(reference.texture.right(3)) and quad.rotation == reference.rotation)
		tiles[quad.tile] = true
		for corner in 4:
			var expected: Array = reference.positions[corner]
			assert(quad.positions[corner].is_equal_approx(Vector3(expected[0], expected[1], expected[2])))
			var expected_uv: Array = reference.uv[corner]
			assert(OriginalSky.uv(corner, quad.rotation).is_equal_approx(Vector2(expected_uv[0], expected_uv[1])))
		var normal: Vector3 = (quad.positions[1] - quad.positions[0]).cross(quad.positions[2] - quad.positions[0])
		assert(normal.dot(centre - quad.positions[0]) > 0, "Original sky faces must point inward")
	assert(tiles.size() == 32)
	assert(OriginalSky.themes('sky_names "2starset, Aurora"\r\nmap_name "Crossroads"') == PackedStringArray(["2starset", "aurora"]))
	for malformed in ['', 'sky_names "../file"', 'sky_names "sunset,,aurora"', 'sky_names "two words"', 'sky_names "sunset"; run_something', 'x'.repeat(65537)]:
		assert(OriginalSky.themes(malformed).is_empty())
	var assets := FixtureAssets.new()
	var sky := OriginalSky.new()
	assert(sky.build('sky_names "fixture"', dimensions, assets))
	assert(sky.theme == "fixture" and sky.mesh.get_surface_count() == 32)
	for index in 32:
		var material: StandardMaterial3D = sky.mesh.surface_get_material(index)
		assert(not material.texture_repeat and material.disable_fog and material.shading_mode == BaseMaterial3D.SHADING_MODE_UNSHADED)
		var surface := sky.mesh.surface_get_arrays(index)
		var points: PackedVector3Array = surface[Mesh.ARRAY_VERTEX]
		var coordinates: PackedVector2Array = surface[Mesh.ARRAY_TEX_UV]
		for vertex in 6:
			var corner: int = [0, 2, 1, 0, 3, 2][vertex]
			var point: Vector3 = actual[index].positions[corner]
			assert(points[vertex].is_equal_approx(Vector3(point.x, point.z, -point.y) * .1))
			assert(coordinates[vertex].is_equal_approx(OriginalSky.uv(corner, actual[index].rotation)))
	assert(not sky.build('sky_names "missing"', dimensions, assets) and sky.mesh == null and sky.theme.is_empty())
	for invalid in [Vector2.ZERO, Vector2(NAN, 5), Vector2(9000, 20), Vector2(-1, 20)]:
		assert(not sky.build('sky_names "fixture"', invalid, assets))
	sky.free()
	print("MODERN_ORIGINAL_SKY=PASS panels=32 original_uvs=true")
	quit()
