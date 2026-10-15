extends MeshInstance3D
## Original 32-tile sky geometry, texture order and UV rotations.
const Assets = preload("res://original_assets.gd")
const SCALE := 0.1
var theme := ""
var error := ""

static func themes(script: String) -> PackedStringArray:
	# Read only this data directive. Never evaluate the original startup script.
	if script.length() > 65536:
		return PackedStringArray()
	var pattern := RegEx.new()
	pattern.compile('(?m)^\\s*sky_names[ \\t]+"([a-zA-Z0-9_, ]{1,256})"[ \\t]*\\r?$')
	var found := pattern.search(script)
	if found == null:
		return PackedStringArray()
	var result := PackedStringArray()
	for name_value in found.get_string(1).split(","):
		var name_clean := name_value.strip_edges().to_lower()
		if name_clean.is_empty() or name_clean.contains(" "):
			return PackedStringArray()
		result.append(name_clean)
	return result

static func quads(world_size: Vector2) -> Array:
	var result: Array = []
	var low := -world_size
	var high := world_size * 2.0
	var step := world_size * 0.75
	for x in 4:
		for y in 4:
			var a := low + Vector2(x, y) * step
			var b := a + step
			result.append({"tile": 29 + x - y * 4, "rotation": 0, "positions": [
				Vector3(a.x, a.y, 3990), Vector3(a.x, b.y, 3990),
				Vector3(b.x, b.y, 3990), Vector3(b.x, a.y, 3990)]})
	var sides := [
		[Vector2(high.x, low.y), high, 8, 1],
		[Vector2(low.x, high.y), low, 16, 3],
		[low, Vector2(high.x, low.y), 12, 0],
		[high, Vector2(low.x, high.y), 4, 2]]
	for side in sides:
		for part in 4:
			var a: Vector2 = side[0].lerp(side[1], part * 0.25)
			var b: Vector2 = side[0].lerp(side[1], (part + 1) * 0.25)
			result.append({"tile": side[2] - part, "rotation": side[3], "positions": [
				Vector3(a.x, a.y, -10), Vector3(a.x, a.y, 3990),
				Vector3(b.x, b.y, 3990), Vector3(b.x, b.y, -10)]})
	return result

static func uv(corner: int, rotation: int) -> Vector2:
	# Retail's small inset avoids sampling a neighbouring repeated edge.
	var corners := [Vector2(.001, .999), Vector2(.001, .001),
		Vector2(.999, .001), Vector2(.999, .999)]
	return corners[posmod(corner - rotation, 4)]

func build(script: String, world_size: Vector2, assets: Assets) -> bool:
	mesh = null
	theme = ""
	error = ""
	var choices := themes(script)
	if choices.is_empty():
		error = "Original map sky settings are missing. Extract the complete client package."
		return false
	if not world_size.is_finite() or world_size.x <= 0 or world_size.y <= 0 or world_size.x > 8192 or world_size.y > 8192:
		error = "Unsupported sky bounds."
		return false
	# Use the map's first declared original theme. Theme cycling is not qualified.
	var selected := choices[0]
	for tile in range(1, 33):
		if not assets._names.get("skies", {}).has(selected + "%03d" % tile):
			error = "Original sky textures are missing. Extract the complete client package."
			return false
	var result := ArrayMesh.new()
	for quad in quads(world_size):
		var material := assets.material(selected + "%03d" % quad.tile, "skies")
		if material == null:
			error = "Could not read the original sky textures."
			return false
		material = material.duplicate()
		material.texture_repeat = false
		material.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED
		material.disable_fog = true
		var surface := SurfaceTool.new()
		surface.begin(Mesh.PRIMITIVE_TRIANGLES)
		surface.set_material(material)
		# Original inward-facing CCW quads become Godot clockwise triangles.
		for corner in [0, 2, 1, 0, 3, 2]:
			var point: Vector3 = quad.positions[corner]
			surface.set_uv(uv(corner, quad.rotation))
			surface.add_vertex(Vector3(point.x, point.z, -point.y) * SCALE)
		surface.commit(result)
	mesh = result
	theme = selected
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	return true
