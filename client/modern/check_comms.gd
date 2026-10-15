extends SceneTree
## Engine GUI events and a captured transport; never joins a server.
const Main = preload("res://main.gd")
const Network = preload("res://network.gd")
const Wire = preload("res://wire.gd")

class CaptureNetwork extends Network:
	var sent: Array[PackedByteArray] = []
	func _send_udp(packet: PackedByteArray) -> void:
		sent.append(packet.duplicate())

func _init() -> void:
	call_deferred("_run")

func _key(code: int, pressed: bool, character := 0, shift := false) -> void:
	var event := InputEventKey.new()
	event.keycode = code
	event.physical_keycode = code
	event.unicode = character
	event.pressed = pressed
	event.shift_pressed = shift
	Input.parse_input_event(event)
	await process_frame

func _click(control: Control, position: Vector2) -> void:
	var point := root.get_final_transform() * control.get_global_transform_with_canvas() * position
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		root.push_input(event)
		await process_frame

func _run() -> void:
	create_timer(30.0).timeout.connect(func(): push_error("Communication GUI check timed out"); quit(1))
	var game := Main.new()
	game.network.free()
	var network := CaptureNetwork.new()
	game.network = network
	root.add_child(game)
	game.set_process(false)
	network.set_process(false)
	game.audio.force_quiet = true
	network.state = "ready"
	network.team = 1
	network.player_id = 1
	network.vehicle_id = 101
	network.map_name = "crossroads"
	network.entities = {101: {"unit": 0, "team": 1, "pos": Vector3(500, 900, 30), "rot": Vector3.ZERO, "health": 1.0}}
	for id in range(1, 81):
		network.roster[id] = {"name": "Pilot %02d" % id, "tag": "CANADA", "team": 1 if id <= 40 else 2,
			"kills": id, "deaths": id / 3, "round_kills": id % 9}
	network.players_by_entity[101] = 1
	game.connection_panel.hide()
	game.deployment_panel.hide()
	await process_frame
	await process_frame
	game._set_menu(true)
	await _click(game.chat_button, game.chat_button.size * .5)
	assert(game.comms.mode == "chat")
	game.comms.close()
	game._set_menu(false)
	await _key(KEY_ENTER, true, 0, true)
	await _key(KEY_ENTER, false)
	assert(game.comms.mode == "chat" and game.comms.channel.get_selected_id() == 4)
	game.comms.close()
	await _key(KEY_F4, true)
	await _key(KEY_F4, false)
	assert(game.comms.mode == "players")
	game.comms.close()
	var dimensions := [Vector2i(800, 600), Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440), Vector2i(3840, 2160)]
	for size in dimensions:
		root.size = size
		await process_frame
		await process_frame
		game.comms.open_chat(true)
		await process_frame
		await process_frame
		assert(root.gui_get_focus_owner() == game.comms.entry)
		assert(not game._driving() and Input.mouse_mode != Input.MOUSE_MODE_CAPTURED)
		assert(game.comms.chat_panel.get_global_rect().position.x >= 0 and game.comms.chat_panel.get_global_rect().end.y <= game.ui.size.y)
		assert(game.comms.feed.get_global_rect().end.y <= game.cockpit_frame.instruments.get_global_rect().end.y)
		game.comms.channel.select(0)
		await _click(game.comms.channel, game.comms.channel.size * .5)
		var popup := game.comms.channel.get_popup()
		assert(game.comms.mode == "chat" and popup.visible, "Channel menu closed the communication panel")
		var navigation: Array = []
		# A mouse-opened menu may start with no keyboard-focused item.
		for step in range(1 - popup.get_focused_item()):
			navigation.append(KEY_DOWN)
		navigation.append(KEY_ENTER)
		for key in navigation:
			for pressed in [true, false]:
				var event := InputEventKey.new()
				event.keycode = key
				event.pressed = pressed
				root.push_input(event)
				await process_frame
		assert(game.comms.channel.get_selected_id() == 4 and game.comms.mode == "chat", "Popup keyboard selection did not retain team scope: %d/%s" % [game.comms.channel.get_selected_id(), game.comms.mode])
		game.comms.entry.clear()
		await _key(KEY_W, true, 119)
		assert(game.comms.entry.text == "w" and Input.is_physical_key_pressed(KEY_W))
		game._input_at = 0
		game._process(.04)
		var controls: PackedByteArray = network.sent.back()
		var reader := Wire.new(controls)
		assert(reader.take(8) == 0x0a)
		assert(reader.take(8) == 11)
		var tick := reader.take(32)
		assert(controls == Network.control_packet(tick, 0, 0, 0, false, false, game.vehicle_input.tilt, game.vehicle_input.jet))
		game.comms.close()
		game._process(.04)
		assert(game._input_rearm and not game._driving(), "Typed key must be released before driving resumes")
		await _key(KEY_W, false)
		game._process(.04)
		assert(not game._input_rearm)
		game.comms.open_chat(true)
		game.comms.entry.text = "[b]Defend the pad[/b]"
		await _key(KEY_ENTER, true)
		await _key(KEY_ENTER, false)
		assert(game.comms.mode.is_empty() and game.comms.entry.text.is_empty())
		var sequence := network.reliable_sequence
		var outgoing := Wire.new(network._pending[sequence].packet)
		assert(outgoing.take(8) == 0x20)
		outgoing.take(16)
		outgoing.take(16)
		assert(outgoing.take(16) == 4)
		outgoing.take(16)
		assert(outgoing.read_text() == "[b]Defend the pad[/b]")
		network.message_received.emit("[b]Defend the pad[/b]", 1, 4, 5)
		assert(not game.comms.pending.has(sequence))
		assert(game.comms.transcript.get_parsed_text().contains("Team · Pilot 01: [b]Defend the pad[/b]"))
		network._pending.clear()
		game.comms.toggle_players()
		await process_frame
		await process_frame
		assert(game.comms._rows.size() == 80)
		assert(game.comms.heading.text.contains("40 Crimson / 40 Azure"))
		var row: TreeItem = game.comms.tree.get_root().get_first_child()
		await _click(game.comms.tree, game.comms.tree.get_item_area_rect(row).get_center())
		assert(game.comms.tree.get_selected() == row, "Scoreboard row click missed at " + str(size))
		game.comms._refresh_players()
		assert(game.comms.tree.get_selected() == row, "Score refresh discarded keyboard selection")
		var last: TreeItem = game.comms._rows[80]
		game.comms.tree.scroll_to_item(last)
		await process_frame
		var scroll := game.comms.tree.get_scroll()
		assert(scroll.y > 0)
		game.comms._refresh_players()
		await process_frame
		assert(game.comms.tree.get_scroll().is_equal_approx(scroll), "Score refresh reset the scroll position")
		await _key(KEY_F4, true)
		await _key(KEY_F4, false)
		assert(game.comms.mode.is_empty())
	game.comms.open_chat()
	game.comms.entry.text = "draft"
	await _key(KEY_ESCAPE, true)
	await _key(KEY_ESCAPE, false)
	assert(game.comms.mode.is_empty() and game.comms.entry.text == "draft")
	game.comms.open_chat()
	game.comms._submit("/s help")
	var command := network.reliable_sequence
	assert(game.comms.pending[command].scope == 1)
	game.comms._acknowledged(command, false)
	assert(game.comms.history.back().contains("could not be confirmed"))
	network._pending.clear()
	for index in 150:
		network.message_received.emit("History %d\n[b]literal[/b]" % index, 2, 0, 5)
	assert(game.comms.history.size() == game.comms.HISTORY_LIMIT)
	assert(not game.comms.history.back().contains("\n") and game.comms.history.back().contains("[b]literal[/b]"))
	assert(game.comms.transcript.get_parsed_text().split("\n", false).size() == game.comms.HISTORY_LIMIT)
	root.size = Vector2i(1920, 1080)
	game.comms.open_chat()
	await process_frame
	await process_frame
	game.comms.transcript.get_v_scroll_bar().value = 0
	network.message_received.emit("A new message must not interrupt reading older messages.", 2, 0, 5)
	await process_frame
	assert(game.comms.transcript.get_v_scroll_bar().value == 0)
	game.comms.transcript.get_v_scroll_bar().value = game.comms.transcript.get_v_scroll_bar().max_value
	if DisplayServer.get_name() != "headless":
		await game._capture()
		game.comms.toggle_players()
		await process_frame
		await process_frame
		await game._capture()
	game.comms.clear()
	assert(game.comms.history.is_empty() and game.comms._rows.is_empty())
	network.disconnect_game()
	game.feedback.reset()
	await create_timer(.08).timeout
	game.queue_free()
	await process_frame
	print("MODERN_COMMS=PASS sizes=5 roster=80 scope=team text_is_plain=true controls_released=true physical_mouse_qualified=false")
	quit()
