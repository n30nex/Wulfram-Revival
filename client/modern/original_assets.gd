class_name OriginalAssets
extends RefCounted
## Read the preserved visual mesh, UVs, palette pixels and original mip levels.
## Collision-only *_s meshes are deliberately not used as visual substitutes.

var directory := ""
var errors: Array[String] = []
var model_cache: Dictionary = {}
var texture_cache: Dictionary = {}
var image_cache: Dictionary = {}
var material_cache: Dictionary = {}
var _archives: Dictionary = {}
var _names: Dictionary = {}
var _palette := PackedByteArray()

class Reader:
	extends RefCounted
	var data: PackedByteArray
	var offset := 0
	var valid := true
	func _init(bytes: PackedByteArray) -> void:
		data = bytes
	func word() -> int:
		if offset + 2 > data.size():
			valid = false
			return 0
		var value := data.decode_u16(offset)
		offset += 2
		return value
	func fixed() -> float:
		if offset + 4 > data.size():
			valid = false
			return 0.0
		var value := float(data.decode_s32(offset)) / 65536.0
		offset += 4
		return value
	func text() -> String:
		var end := data.find(0, offset)
		if end < offset or end - offset > 1024:
			valid = false
			return ""
		var value := data.slice(offset, end).get_string_from_ascii()
		offset = end + 1
		return value

func open_directory(path: String) -> bool:
	directory = path
	_palette = FileAccess.get_file_as_bytes(path.path_join("palette0"))
	if _palette.size() != 768:
		errors.append("Missing original palette0.")
		return false
	for name in ["shapes", "base", "landscape", "skies", "res_640x480", "stripmaps2"]:
		var archive := ZIPReader.new()
		if archive.open(path.path_join(name + ".zip")) != OK:
			errors.append("Missing original " + name + ".zip")
			return false
		_archives[name] = archive
		var lookup: Dictionary = {}
		for entry in archive.get_files():
			if lookup.has(entry.to_lower()) and not FileAccess.file_exists(path.path_join("resolved/" + name + "/" + entry.to_lower())):
				errors.append("Original texture data is incomplete. Extract the complete client package.")
				return false
			lookup[entry.to_lower()] = entry
		_names[name] = lookup
	return true

func _read(archive: String, name: String) -> PackedByteArray:
	# Original packs append replacements under existing names. ZIPReader
	# returns the first match; imported last-member bytes retain retail overrides.
	var resolved := directory.path_join("resolved/" + archive + "/" + name.to_lower())
	if FileAccess.file_exists(resolved):
		return FileAccess.get_file_as_bytes(resolved)
	var entry: String = _names.get(archive, {}).get(name.to_lower(), "")
	if entry.is_empty():
		errors.append("Missing original asset: " + archive + "/" + name)
		return PackedByteArray()
	return _archives[archive].read_file(entry)

func stripmap(name: String) -> Texture2D:
	var key := "stripmaps2/" + name.to_lower()
	if texture_cache.has(key):
		return texture_cache[key]
	var bytes := _read("stripmaps2", name)
	if bytes.size() < 12:
		return null
	var strips := bytes.decode_u32(0)
	var width := bytes.decode_u16(4)
	var height := bytes.decode_u16(6)
	var count := bytes.decode_u32(8)
	if strips > 65536 or count > 16777216 or bytes.size() != 12 + count + strips * 6:
		errors.append("Invalid original stripmap: " + name)
		return null
	var bounds := Vector2i.ZERO
	var total := 0
	for index in strips:
		var at := 12 + count + index * 6
		bounds.x = maxi(bounds.x, bytes.decode_u16(at) + bytes.decode_u16(at + 4))
		bounds.y = maxi(bounds.y, bytes.decode_u16(at + 2) + 1)
		total += bytes.decode_u16(at + 4)
	width = bounds.x if width == 0 else width
	height = bounds.y if height == 0 else height
	if total != count or width < bounds.x or height < bounds.y or width < 1 or height < 1 or width > 4096 or height > 4096:
		errors.append("Original stripmap bounds mismatch: " + name)
		return null
	var pixels := PackedByteArray()
	pixels.resize(width * height * 4)
	var source := 12
	for index in strips:
		var at := 12 + count + index * 6
		var x := bytes.decode_u16(at)
		var y := bytes.decode_u16(at + 2)
		var length := bytes.decode_u16(at + 4)
		for column in length:
			var value: int = bytes[source]
			source += 1
			var target := ((y * width) + x + column) * 4
			for channel in 3:
				pixels[target + channel] = _palette[value * 3 + channel]
			pixels[target + 3] = 255
	var image := Image.create_from_data(width, height, false, Image.FORMAT_RGBA8, pixels)
	var result := ImageTexture.create_from_image(image)
	image_cache[key] = image
	texture_cache[key] = result
	return result

func texture(name: String, archive := "base") -> Texture2D:
	var key := archive + "/" + name.to_lower()
	if texture_cache.has(key):
		return texture_cache[key]
	var bytes := _read(archive, name)
	if bytes.size() < 3:
		return null
	var kind := int(bytes[0]) & 0x7f
	var transparent := (int(bytes[0]) & 0x80) != 0
	var width := 0
	var height := 0
	var start := 0
	var mipmaps := kind == 3
	if kind == 3 and bytes.decode_u16(1) <= 11:
		width = 1 << bytes.decode_u16(1)
		height = width
		start = 3
	elif kind == 1 and bytes.size() >= 9:
		width = bytes.decode_u16(1)
		height = bytes.decode_u16(3)
		start = 9
	if width < 1 or height < 1 or width > 4096 or height > 4096:
		errors.append("Unsupported original bitmap: " + key)
		return null
	var count := width * height
	if mipmaps:
		var level := width >> 1
		while level > 0:
			count += level * level
			level >>= 1
	if bytes.size() != start + count:
		errors.append("Unexpected original bitmap length: " + key)
		return null
	var pixels := PackedByteArray()
	pixels.resize(count * 4)
	for index in count:
		var value := int(bytes[start + index])
		for channel in 3:
			pixels[index * 4 + channel] = _palette[value * 3 + channel]
		pixels[index * 4 + 3] = 0 if transparent and value == 0 else 255
	var image := Image.create_from_data(width, height, mipmaps, Image.FORMAT_RGBA8, pixels)
	if image == null:
		return null
	var result := ImageTexture.create_from_image(image)
	image_cache[key] = image
	texture_cache[key] = result
	return result

func material(name: String, archive := "base") -> StandardMaterial3D:
	var key := archive + "/" + name.to_lower()
	if material_cache.has(key):
		return material_cache[key]
	var bitmap := texture(name, archive)
	if bitmap == null:
		return null
	var result := StandardMaterial3D.new()
	result.albedo_texture = bitmap
	# Preserve the baked original colours while lighting parity is qualified.
	result.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	result.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	result.texture_repeat = true
	result.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	material_cache[key] = result
	return result

func model(name: String) -> Dictionary:
	if model_cache.has(name):
		return model_cache[name]
	var bytes := _read("shapes", name)
	if bytes.is_empty():
		return {}
	var reader := Reader.new(bytes)
	if reader.text() != name:
		errors.append("Original model name mismatch: " + name)
		return {}
	var materials: Array[String] = []
	for index in reader.word():
		materials.append(reader.text())
	var vertices := PackedVector3Array()
	for index in reader.word():
		var x := reader.fixed()
		var y := reader.fixed()
		var z := reader.fixed()
		vertices.append(Vector3(x, z, -y) * 0.1)
	var surfaces: Dictionary = {}
	var face_count := reader.word()
	var triangle_count := 0
	for face in face_count:
		var material_id := reader.word()
		var corners := reader.word()
		if material_id >= materials.size() or corners < 3 or corners > 64:
			reader.valid = false
			break
		var points: Array = []
		for corner in corners:
			var vertex := reader.word()
			var uv := Vector2(reader.fixed(), reader.fixed())
			if vertex >= vertices.size():
				reader.valid = false
				break
			points.append([vertices[vertex], uv])
		if not reader.valid:
			break
		if not surfaces.has(material_id):
			var surface := SurfaceTool.new()
			surface.begin(Mesh.PRIMITIVE_TRIANGLES)
			surfaces[material_id] = surface
		for triangle in range(1, corners - 1):
			# Original meshes are counter-clockwise from the exterior. The Z-up
			# to Y-up rotation preserves handedness; Godot wants clockwise fronts.
			# Reverse indices, retaining each corner's original position and UV.
			for corner in [0, triangle + 1, triangle]:
				surfaces[material_id].set_uv(points[corner][1])
				surfaces[material_id].add_vertex(points[corner][0])
			triangle_count += 1
	var attachments: Dictionary = {}
	if reader.valid:
		for point in reader.word():
			var label := reader.text()
			var x := reader.fixed()
			var y := reader.fixed()
			var z := reader.fixed()
			attachments[label] = Vector3(x, z, -y) * 0.1
	if not reader.valid:
		errors.append("Truncated original visual mesh: " + name)
		return {}
	var mesh := ArrayMesh.new()
	for material_id in surfaces:
		var original := material(materials[material_id])
		if original == null:
			return {}
		surfaces[material_id].generate_normals()
		surfaces[material_id].set_material(original)
		surfaces[material_id].commit(mesh)
	var result := {"mesh": mesh, "attachments": attachments, "vertices": vertices.size(),
		"faces": face_count, "triangles": triangle_count, "materials": materials}
	model_cache[name] = result
	return result

static func model_name(unit: int, team: int) -> String:
	var suffix := "_2" if team == 1 else "_1"
	var paired := {0: "tank", 1: "scout", 25: "energy", 26: "refuel", 27: "repair", 29: "flak_turret", 30: "gun_turret", 35: "darklight"}
	if paired.has(unit):
		return paired[unit] + suffix
	return {5: "flak_shell", 6: "pulse_shell", 19: "cargo", 20: "uplinkred" if team == 1 else "uplinkblue"}.get(unit, "")
