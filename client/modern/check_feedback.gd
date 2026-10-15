extends SceneTree
## Original effect frames driven through the real packet decoder, offline.
const Main = preload("res://main.gd")

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	create_timer(20.0).timeout.connect(func(): quit(1))
	var game := Main.new()
	root.add_child(game)
	game.audio.force_quiet = true
	game.set_process(false)
	game.network.set_process(false)
	game.connection_panel.hide()
	game.deployment_panel.hide()
	game._first_person = true
	game._load_map("crossroads")
	assert(game.terrain_loaded and game.feedback.configured and game.audio.loaded)
	game.network.state = "ready"
	game.network.vehicle_id = 1
	game.network.health = 1
	game.network.fuel = 1
	game.network.entities = {1: {"unit": 0, "team": 1, "pos": Vector3(486.03, 966.28, 40), "rot": Vector3(0, 0, PI * .5)}}
	game._sync_visuals(1.0)
	game.status_label.text = "Original combat effects · offline packet reference"
	await process_frame
	await process_frame
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json"))
	game.network._handle(fixture.visual_feedback.hex_decode())
	assert(game.feedback.effects.size() == 3 and game.feedback.events_played == 3)
	game.network._handle(fixture.visual_feedback.hex_decode())
	assert(game.feedback.effects.size() == 3, "Duplicate packet duplicated effects")
	await game._capture()
	await create_timer(1.7).timeout
	assert(game.feedback.effects.is_empty(), "Finished effects leaked into later frames")
	game.feedback.reset()
	await create_timer(.08).timeout
	game.queue_free()
	await process_frame
	print("MODERN_FEEDBACK=PASS")
	quit()
