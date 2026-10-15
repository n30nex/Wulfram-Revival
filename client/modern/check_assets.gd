extends SceneTree
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")
const OriginalSky = preload("res://original_sky.gd")

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
	for pair in [["p2Rlanding1", "54e225d8858282549a5fb7c62030b05d17b5aebe5699de5d7c8c5c4d3023b4a5"],
		["gunblast_front1", "8c52a49c86a90230a080d78386a56c1753f97d22d9375bfd93b0e08257469b7a"]]:
		hash.start(HashingContext.HASH_SHA256)
		hash.update(assets._read("base", pair[0]))
		if hash.finish().hex_encode() != pair[1]:
			assets.errors.append("Did not retain the original replacement member: " + pair[0])
	for map_name in ["crossroads", "mayhem", "frontier"]:
		var terrain := Terrain.new()
		var passed := terrain.build("res://content/maps/" + map_name + ".land", assets)
		print("ORIGINAL_TERRAIN " + JSON.stringify({"map": map_name, "passed": passed, "error": terrain.error, "build_msec": terrain.build_msec, "texture_bytes": terrain.texture_bytes}))
		if not passed:
			assets.errors.append(terrain.error)
		terrain.free()
	var sky_pixels := {"2starset": "ea69a4dadde5f8523ec648c720e415641cf8c7e2d9dcd378575d12945c804158",
		"aurora": "18d6a6b624f210b211dc0de562358750ef99d8e4138e6dba3f8ce598f17a6f7e",
		"sunset": "db265e399594ff8192f195292da1f535572fbbd654080e03a499590b9ca73579"}
	for theme in sky_pixels:
		var sky := OriginalSky.new()
		var passed := sky.build('sky_names "' + theme + '"', Vector2(5600, 5600), assets)
		if passed:
			hash.start(HashingContext.HASH_SHA256)
			for tile in range(1, 33):
				hash.update(assets.image_cache["skies/" + theme + "%03d" % tile].get_data())
			if hash.finish().hex_encode() != sky_pixels[theme]:
				assets.errors.append("Sky pixels differ from the independent preserved-archive decode: " + theme)
		print("ORIGINAL_SKY " + JSON.stringify({"theme": theme, "passed": passed, "error": sky.error, "panels": sky.mesh.get_surface_count() if passed else 0}))
		if not passed:
			assets.errors.append(sky.error)
		sky.free()
	quit(0 if assets.errors.is_empty() and count == 39 and strips == 10 else 1)
