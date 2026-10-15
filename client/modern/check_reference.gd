extends SceneTree
## Fixed-pose visual reference. Uses original local assets; never joins a server.
const Main = preload("res://main.gd")

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	var game := Main.new()
	root.add_child(game)
	game.set_process(false)
	game.network.set_process(false)
	game.connection_panel.hide()
	game.deployment_panel.hide()
	game._first_person = true
	game._load_map("crossroads")
	if not game.terrain_loaded:
		push_error(game.terrain.error)
		quit(1)
		return
	game.network.vehicle_id = 1
	game.network.entities = {1: {"unit": 0, "team": 1, "pos": Vector3(486.03, 966.28, 40.0), "rot": Vector3(0, 0, PI * .5)}}
	game._sync_visuals(1.0)
	print("REFERENCE_CAMERA " + JSON.stringify({"position": game.camera.position, "attachments": game.assets.model("tank_2").attachments}))
	print("REFERENCE_TERRAIN " + JSON.stringify({"build_msec": game.terrain.get("build_msec"), "texture_bytes": game.terrain.get("texture_bytes")}))
	game.status_label.text = "Original Crossroads reference · fixed deployment position"
	await process_frame
	await process_frame
	await game._capture()
	print("MODERN_REFERENCE=PASS")
	game.queue_free()
	await process_frame
	quit()
