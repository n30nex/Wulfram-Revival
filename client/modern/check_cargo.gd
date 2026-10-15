extends SceneTree
## Recorded transport plus actual GUI routing; no public match mutations.
const Main = preload("res://main.gd")
const Network = preload("res://network.gd")
const Scope = preload("res://native_world.gd")
const Wire = preload("res://wire.gd")

class CaptureNetwork extends Network:
	var sent: Array[PackedByteArray] = []
	func _send_udp(packet: PackedByteArray) -> void:
		sent.append(packet.duplicate())

func _init() -> void:
	call_deferred("_run")

func _key(code: int, character := 0) -> void:
	for pressed in [true, false]:
		var event := InputEventKey.new()
		event.keycode = code
		event.physical_keycode = code
		event.unicode = character
		event.pressed = pressed
		root.push_input(event)
		await process_frame

func _click(button: Button) -> void:
	var point := root.get_final_transform() * button.get_global_transform_with_canvas() * (button.size * .5)
	for pressed in [true, false]:
		var event := InputEventMouseButton.new()
		event.position = point
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		root.push_input(event)
		await process_frame

func _run() -> void:
	create_timer(30.0).timeout.connect(func(): push_error("Cargo check timed out"); quit(1))
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json"))
	var peer := Network.new()
	peer.state = "ready"
	peer.player_id = 7
	var cargo_sounds: Array = []
	peer.cargo_changed.connect(func(holding: bool): cargo_sounds.append(holding))
	peer._handle(fixture.native_lifecycle.world1.hex_decode(), true)
	peer._handle(fixture.native_lifecycle.tank.hex_decode(), true)
	peer._handle(Scope.encode(fixture.carrying.hex_decode(), 1, 42, 0, 1), true)
	peer._handle(Scope.encode(fixture.carrying.hex_decode(), 1, 42, 0, 1), true)
	assert(peer.carrying and peer.cargo_description() == "Cargo: Repair Pad")
	assert(cargo_sounds == [true], "Duplicate carrying update replayed pickup feedback")
	var sequence := peer.release_cargo(true)
	var pending := Scope.decode(peer._pending[sequence].packet)
	assert(pending.owner == 42 and pending.epoch == 1 and pending.connection == 1)
	assert(pending.payload.hex_encode() == "2b0001000900000001")
	assert(peer.carrying and peer.release_cargo(false) == -1, "An unconfirmed action must not free the cargo slot")
	var ack := Wire.new().put(2, 8).put(5, 16).put(9, 16).put(1, 8).put(0x2b, 8).put(sequence, 16).data
	peer._handle(Scope.encode(ack, 0, 0, 0, 1), true)
	assert(peer.carrying and peer.cargo_request_sequence == sequence, "Receipt is not confirmation of a cargo state change")
	peer._handle(Scope.encode(fixture.not_carrying.hex_decode(), 1, 41, 0, 1), true)
	assert(peer.carrying, "Previous owner's cargo state changed the current vehicle")
	peer._handle(Scope.encode(fixture.not_carrying.hex_decode(), 1, 42, 0, 1), true)
	assert(not peer.carrying and peer.cargo_request_sequence == -1)
	peer._handle(Scope.encode(fixture.carrying_enemy.hex_decode(), 1, 42, 0, 1), true)
	assert(peer.release_cargo(true) == -1 and peer.can_release_cargo(false))
	assert(peer.release_cargo(false) >= 0)
	peer._cargo_deadline = 0.0
	peer._check_cargo_timeout()
	assert(peer.carrying and peer.cargo_request_sequence == -1 and peer._pending.is_empty())
	peer.release_cargo(false)
	peer._handle(fixture.native_lifecycle.delete.hex_decode(), true)
	assert(not peer.carrying and peer.cargo_request_sequence == -1 and peer._pending.is_empty())
	peer._handle(fixture.native_lifecycle.next_tank.hex_decode(), true)
	peer._handle(Scope.encode(fixture.carrying.hex_decode(), 1, 42, 0, 1), true)
	assert(not peer.carrying and peer.carried_by_player.is_empty())
	peer._handle(Scope.encode(fixture.carrying.hex_decode(), 1, 43, 0, 1), true)
	peer.release_cargo(false)
	peer._handle(fixture.native_lifecycle.world2.hex_decode(), true)
	assert(not peer.carrying and peer.cargo_request_sequence == -1 and peer.carried_by_player.is_empty())
	peer.disconnect_game()
	assert(peer.cargo_item == 0 and peer.docking_pad == 0)
	peer.free()
	var game := Main.new()
	game.network.free()
	var network := CaptureNetwork.new()
	game.network = network
	root.add_child(game)
	game.set_process(false)
	network.set_process(false)
	game.audio.force_quiet = true
	game._input_at = INF
	network.state = "ready"
	network.map_name = "crossroads"
	network.player_id = 7
	network._handle(fixture.tank.hex_decode())
	network._handle(fixture.birth.hex_decode())
	network._handle(fixture.carrying.hex_decode())
	network._handle(fixture.carrying_other.hex_decode())
	assert(network.carried_by_player[8] == 13, "Enemy cargo identity must stay redacted")
	game._process(0)
	var original_attachment_checked := false
	if game.assets_loaded:
		var carried := game.visuals[42].get_node_or_null("CarriedCargo") as MeshInstance3D
		assert(carried != null and carried.mesh == game.assets.model("cargo").mesh)
		assert(carried.position == game.assets.model("tank_2").attachments.cargo_pos)
		original_attachment_checked = true
	for dimensions in [Vector2i(800, 600), Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440), Vector2i(3840, 2160)]:
		root.size = dimensions
		game._set_menu(true)
		network._handle(fixture.carrying.hex_decode())
		game._process(0)
		await process_frame
		await process_frame
		assert(game.comms.feed.get_global_rect().end.y <= game.cockpit_frame.instruments.get_global_rect().end.y)
		assert(game.cargo_deploy_button.get_global_rect().end.x <= game.cockpit_frame.instruments.get_global_rect().end.x)
		for deploy in [false, true]:
			network._handle(fixture.carrying.hex_decode())
			game._process(0)
			await _click(game.cargo_deploy_button if deploy else game.cargo_drop_button)
			assert(network.cargo_request_sequence >= 0, "Cargo click missed at " + str(dimensions))
			var packet := Wire.new(network._pending[network.cargo_request_sequence].packet)
			assert(packet.take(8) == 0x2b)
			packet.take(16)
			assert(packet.take(16) == 9 and packet.take(32) == int(deploy))
			game._process(0)
			assert(game.cargo_drop_button.disabled and game.cargo_deploy_button.disabled and network.carrying)
			network._handle(fixture.not_carrying.hex_decode())
		network._handle(fixture.carrying.hex_decode())
		game.comms.open_chat()
		await process_frame
		await process_frame
		await _key(KEY_COMMA, 44)
		await _key(KEY_PERIOD, 46)
		assert(game.comms.entry.text.ends_with(",.") and network.cargo_request_sequence == -1)
		game.comms.close()
		await _key(KEY_PERIOD)
		assert(network.cargo_request_sequence == -1, "Cargo shortcut fired from a menu")
		network._handle(fixture.carrying_enemy.hex_decode())
		game._process(0)
		assert(game.cargo_deploy_button.disabled and not game.cargo_drop_button.disabled)
	game._set_menu(false)
	game._input_rearm = false
	network._handle(fixture.carrying.hex_decode())
	var keyboard_checked := false
	if game._driving():
		await _key(KEY_PERIOD)
		assert(network.cargo_request_sequence >= 0, "Driving cargo shortcut missed")
		keyboard_checked = true
		network._handle(fixture.not_carrying.hex_decode())
	root.size = Vector2i(1920, 1080)
	network._handle(fixture.carrying.hex_decode())
	game._set_menu(false)
	if game.assets_loaded and DisplayServer.get_name() != "headless":
		game._load_map("crossroads")
		network.entities[42].pos = Vector3(486, 1010, 35)
		game._sync_visuals(1.0)
	game._process(0)
	await process_frame
	await process_frame
	if DisplayServer.get_name() != "headless":
		await game._capture()
	if "--require-keyboard" in OS.get_cmdline_user_args():
		assert(keyboard_checked, "The test window did not receive focus for driving shortcuts")
	network._handle(fixture.not_carrying.hex_decode())
	game._process(0)
	if game.assets_loaded:
		assert(game.visuals[42].get_node_or_null("CarriedCargo") == null)
	network.disconnect_game()
	game.feedback.reset()
	await create_timer(.08).timeout
	game.queue_free()
	await process_frame
	print("MODERN_CARGO=PASS sizes=5 pending_state_confirmed=true original_attachment=%s driving_shortcuts=%s physical_mouse_qualified=false" % [original_attachment_checked, keyboard_checked])
	quit()
