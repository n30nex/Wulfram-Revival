extends SceneTree
## Fixed original-model gallery, independent of the live server or desktop focus.
const Main = preload("res://main.gd")

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	var game := Main.new()
	root.add_child(game)
	game.set_process(false)
	game.network.set_process(false)
	game.ui.hide()
	game.network.entities = {
		100: {"unit": 27, "team": 1, "pos": Vector3(-30, 0, 0), "rot": Vector3.ZERO},
		101: {"unit": 0, "team": 1, "pos": Vector3.ZERO, "rot": Vector3(0, 0, PI * .5)},
		102: {"unit": 1, "team": 2, "pos": Vector3(25, 0, 0), "rot": Vector3(0, 0, PI * .5)},
		103: {"unit": 26, "team": 1, "pos": Vector3(-30, 40, 0), "rot": Vector3.ZERO}}
	game._sync_visuals(1.0)
	game.camera.position = Vector3(0, 4, 8)
	game.camera.look_at(Vector3(0, 0, -2))
	await process_frame
	await process_frame
	await game._capture()
	assert(game.visuals.size() == 4 and game.assets.errors.is_empty())
	print("MODERN_MODELS=PASS")
	game.queue_free()
	await process_frame
	quit()
