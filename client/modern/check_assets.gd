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
	for map_name in ["crossroads", "mayhem", "frontier"]:
		var terrain := Terrain.new()
		var passed := terrain.build("res://content/maps/" + map_name + ".land", assets)
		print("ORIGINAL_TERRAIN " + JSON.stringify({"map": map_name, "passed": passed, "error": terrain.error}))
		if not passed:
			assets.errors.append(terrain.error)
		terrain.free()
	quit(0 if assets.errors.is_empty() and count == 39 else 1)
