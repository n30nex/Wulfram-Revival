extends SceneTree
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")

func _init() -> void:
	var assets := Assets.new()
	if not assets.open_directory("res://content/original"):
		push_error(str(assets.errors))
		quit(1)
		return
	var count := 0
	var triangles := 0
	for name in assets._archives.shapes.get_files():
		if name.ends_with("_s"):
			continue
		var model := assets.model(name)
		if model.is_empty():
			continue
		count += 1
		triangles += model.triangles
	print("ORIGINAL_ASSETS " + JSON.stringify({"models": count, "triangles": triangles, "textures": assets.texture_cache.size(), "errors": assets.errors}))
	var strips := 0
	for name in assets._archives.stripmaps2.get_files():
		if assets.stripmap(name) != null:
			strips += 1
	var hash := HashingContext.new()
	hash.start(HashingContext.HASH_SHA256)
	hash.update(assets.image_cache["stripmaps2/shockforce_cockpit"].get_data())
	var cockpit_pixels := hash.finish().hex_encode()
	if cockpit_pixels != "31b0f57425fe8c53693292852ab2297c3e4fa0ba0d9b6c5fd0160387f9508c93":
		assets.errors.append("Cockpit pixels differ from the independent preserved-archive decode.")
	print("ORIGINAL_STRIPMAPS " + JSON.stringify({"decoded": strips, "cockpit_sha256": cockpit_pixels}))
	for map_name in ["crossroads", "mayhem", "frontier"]:
		var terrain := Terrain.new()
		var passed := terrain.build("res://content/maps/" + map_name + ".land", assets)
		print("ORIGINAL_TERRAIN " + JSON.stringify({"map": map_name, "passed": passed, "error": terrain.error, "build_msec": terrain.build_msec, "texture_bytes": terrain.texture_bytes}))
		if not passed:
			assets.errors.append(terrain.error)
		terrain.free()
	quit(0 if assets.errors.is_empty() and count == 39 and strips == 10 else 1)
