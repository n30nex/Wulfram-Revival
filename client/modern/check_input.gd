extends SceneTree
## Exercise the real GUI event route with stretched window coordinates.
const Main = preload("res://main.gd")

func _init() -> void:
	call_deferred("_run")

func _click(control: Control, local_point: Vector2) -> void:
	var point := root.get_final_transform() * control.get_global_transform_with_canvas() * local_point
	var move := InputEventMouseMotion.new()
	move.position = point
	root.push_input(move)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		root.push_input(event)
		await process_frame

func _button(node: Node, text_value: String) -> Button:
	if node is Button and node.text == text_value:
		return node
	for child in node.get_children():
		var found := _button(child, text_value)
		if found:
			return found
	return null

func _run() -> void:
	var game := Main.new()
	root.add_child(game)
	game.set_process(false)
	game.network.set_process(false)
	var cases := 0
	for dimensions in [Vector2i(800, 600), Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440), Vector2i(3840, 2160)]:
		root.size = dimensions
		game.connection_panel.show()
		game.deployment_panel.hide()
		await process_frame
		await process_frame
		assert(game.connection_panel.get_global_rect().position.y >= 0)
		assert(game.connection_panel.get_global_rect().end.y <= game.ui.size.y)
		await _click(game.host_input, game.host_input.size * .5)
		assert(root.gui_get_focus_owner() == game.host_input, "Scaled login click missed at " + str(dimensions))
		game.connection_panel.hide()
		game.deployment_panel.show()
		game.network.state = "ready"
		game.network.team = 0
		game.network._team_requested = 0
		await process_frame
		var crimson := _button(game.ui, "CRIMSON")
		await _click(crimson, crimson.size * .5)
		assert(game.network._team_requested == 1, "Scaled team click missed at " + str(dimensions))
		game.network._confirm_team(1)
		game.network.entities = {101: {"unit": 27, "team": 1, "pos": Vector3(1200, 1000, 0), "health": 1.0},
			102: {"unit": 27, "team": 1, "pos": Vector3(4200, 4000, 0), "health": 1.0}}
		game._refresh_pads()
		# Independently compute the visible second pad's coordinate from the
		# published map rectangle; the GUI must select it through normal routing.
		var map_point := Vector2(12, 32) + Vector2(4200.0 / 5600.0, 4000.0 / 5600.0) * (game.map_control.size - Vector2(24, 44))
		await process_frame
		await process_frame
		if DisplayServer.get_name() != "headless":
			await RenderingServer.frame_post_draw
			await _click(game.map_control, map_point)
			assert(game.selected_pad == 102, "Scaled tactical map click missed at " + str(dimensions))
		cases += 1
	print("MODERN_INPUT=PASS sizes=%d physical_mouse_qualified=false" % cases)
	game.network.disconnect_game()
	game.queue_free()
	await process_frame
	quit()
