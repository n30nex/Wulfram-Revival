extends Node3D

const Network = preload("res://network.gd")
const Radar = preload("res://radar.gd")
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")
const VehicleInput = preload("res://vehicle_input.gd")
const Cockpit = preload("res://cockpit.gd")
const OriginalAudio = preload("res://original_audio.gd")
const CombatFeedback = preload("res://combat_feedback.gd")
const OriginalSky = preload("res://original_sky.gd")
const PlayerComms = preload("res://player_comms.gd")
const SCALE := 0.1
var network := Network.new()
var camera := Camera3D.new()
var terrain := Terrain.new()
var original_sky := OriginalSky.new()
var comms := PlayerComms.new()
var chat_button: Button
var players_button: Button
var _input_rearm := false
var visuals: Dictionary = {}
var assets := Assets.new()
var assets_loaded := false
var audio := OriginalAudio.new()
var feedback := CombatFeedback.new()
var sound_sliders: Array[HSlider] = []
var mute_boxes: Array[CheckBox] = []
var ui := Control.new()
var connection_panel: Control
var deployment_panel: Control
var host_input := LineEdit.new()
var name_input := LineEdit.new()
var code_input := LineEdit.new()
var pad_choice := OptionButton.new()
var vehicle_choice := OptionButton.new()
var deploy_button: Button
var resume_button: Button
var _asset_error := ""
var _map_error := ""
var _closing := false
var status_label := Label.new()
var telemetry_label := Label.new()
var health_bar := ProgressBar.new()
var fuel_bar := ProgressBar.new()
var charge_bar := ProgressBar.new()
var charge_label := Label.new()
var reticle := Label.new()
var vehicle_input := VehicleInput.new()
var server_port := 2627
var map_control: Control
var radar_control: Control
var cockpit_frame := Cockpit.new()
var terrain_loaded := false
var selected_pad := 0
var world_size := Vector2(5600, 5600)
var _input_at := 0.0
var _last_input_time := 0.0
var _refresh_at := 0.0
var _spawn_retry_at := 0.0
var _spawn_until := 0.0
var _smoke := false
var _combat_smoke := false
var _smoke_started := 0.0
var _first_position := Vector3.ZERO
var _moved := 0.0
var _deployed_at := 0.0
var _smoke_pads: Array = []
var _smoke_attempt := 0
var _menu_open := false
var _first_person := false
var _capture_dir := "user://screenshots"

func _ready() -> void:
	Engine.max_fps = 120
	get_window().min_size = Vector2i(800, 600)
	get_tree().auto_accept_quit = false
	get_window().close_requested.connect(_quit_safely)
	add_child(network)
	add_child(camera)
	add_child(terrain)
	add_child(original_sky)
	add_child(audio)
	audio.listener = camera
	feedback.network = network
	feedback.audio = audio
	feedback.assets = assets
	feedback.camera = camera
	feedback.visuals = visuals
	add_child(feedback)
	camera.far = 1800
	camera.fov = 72
	camera.position = Vector3(280, 180, -50)
	camera.look_at(Vector3(280, 0, -280))
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-42, -32, 0)
	sun.light_energy = 0.65
	sun.shadow_enabled = true
	add_child(sun)
	var environment_node := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color.BLACK
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("a9bcc8")
	environment.ambient_light_energy = 0.25
	environment_node.environment = environment
	add_child(environment_node)
	_build_ui()
	comms.mode_changed.connect(_social_mode_changed)
	comms.incoming_chat.connect(func(): audio.play("MESSAGE_HAIL"))
	get_window().focus_exited.connect(_focus_exited)
	var asset_path := "res://content/original"
	if not FileAccess.file_exists(asset_path.path_join("palette0")):
		asset_path = OS.get_executable_path().get_base_dir().path_join("original")
	if FileAccess.file_exists(asset_path.path_join("palette0")):
		assets_loaded = assets.open_directory(asset_path)
	if not assets_loaded:
		_asset_error = "Original graphics are missing. Extract the complete client package and reopen it."
	else:
		cockpit_frame.artwork = assets.stripmap("shockforce_cockpit")
		if not audio.open_directory(asset_path.path_join("audio")):
			_asset_error = "Original sounds are missing. Extract the complete client package and reopen it."
		if not feedback.configure():
			_asset_error = "Original effects are missing. Extract the complete client package and reopen it."
	_display_status(status_label.text)
	network.status_changed.connect(_display_status)
	network.world_changed.connect(_load_map)
	network.deployed.connect(_on_deployed)
	var args := OS.get_cmdline_user_args()
	for value in args:
		if value.begins_with("--capture-dir="):
			_capture_dir = value.trim_prefix("--capture-dir=")
		elif value.begins_with("--port="):
			server_port = int(value.trim_prefix("--port="))
	if "--fullscreen" in args:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	_smoke = "--online-smoke" in args
	_combat_smoke = _smoke and "--combat-smoke" in args
	audio.force_quiet = _smoke or "--quiet-test" in args or "--ui-check" in args
	_smoke_started = Network.now()
	if "--connect" in args or _smoke:
		for value in args:
			if value.begins_with("--server="):
				host_input.text = value.trim_prefix("--server=")
		# Private integration tests use a disposable local player code. Never
		# accept this override for an internet host or read an admin credential.
		if host_input.text in ["127.0.0.1", "::1"] and OS.has_environment("WULFRAM_TEST_JOIN_CODE"):
			code_input.text = OS.get_environment("WULFRAM_TEST_JOIN_CODE")
		name_input.text = "ModernCheck" + str(Time.get_unix_time_from_system()).replace(".", "").right(8) if _smoke else "ModernPilot"
		_connect()
	if "--ui-check" in args:
		call_deferred("_ui_check")
	if "--capture-start" in args:
		get_tree().create_timer(3.0).timeout.connect(_capture)

func _label(text_value: String, font_size := 18) -> Label:
	var label := Label.new()
	label.text = text_value
	label.add_theme_font_size_override("font_size", font_size)
	return label

func _panel(parent: Node, minimum: Vector2) -> VBoxContainer:
	var panel := PanelContainer.new()
	panel.custom_minimum_size = minimum
	var style := StyleBoxFlat.new()
	style.bg_color = Color(0.035, 0.055, 0.075, 0.96)
	style.border_color = Color("536a77")
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	style.content_margin_left = 22
	style.content_margin_right = 22
	style.content_margin_top = 18
	style.content_margin_bottom = 18
	panel.add_theme_stylebox_override("panel", style)
	parent.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	panel.add_child(box)
	return box

func _button(parent: Node, text_value: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text_value
	button.custom_minimum_size.y = 42
	button.add_theme_font_size_override("font_size", 18)
	button.pressed.connect(func():
		if not _closing:
			audio.play("CLICK_MINOR")
			action.call())
	parent.add_child(button)
	return button

func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	layer.add_child(ui)
	ui.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	ui.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var title := _label("WULFRAM II  /  REVIVAL", 25)
	ui.add_child(title)
	title.position = Vector2(28, 22)
	var badge := _label("MODERN CLIENT · DEVELOPMENT PREVIEW", 14)
	ui.add_child(badge)
	badge.position = Vector2(28, 57)
	badge.modulate = Color("9eb5c5")
	var menu_button := _button(ui, "DEPLOYMENT / F1", func(): _set_menu(not _menu_open))
	menu_button.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	menu_button.offset_left = -200
	menu_button.offset_right = -28
	menu_button.offset_top = 22
	menu_button.offset_bottom = 64
	players_button = _button(ui, "PLAYERS / F4", comms.toggle_players)
	chat_button = _button(ui, "CHAT / ENTER", comms.open_chat)
	for pair in [[players_button, -400, -212], [chat_button, -590, -412]]:
		pair[0].set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
		pair[0].offset_left = pair[1]
		pair[0].offset_right = pair[2]
		pair[0].offset_top = 22
		pair[0].offset_bottom = 64
	var center := CenterContainer.new()
	ui.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.offset_bottom = -Cockpit.HEIGHT - 20
	center.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var screens := VBoxContainer.new()
	center.add_child(screens)
	var connection := _panel(screens, Vector2(520, 0))
	connection_panel = connection.get_parent()
	connection.add_child(_label("Return to the battlefield", 28))
	connection.add_child(_label("A new cockpit. The same war.", 18))
	for pair in [["Server", host_input, "wulfram.canadaverse.org"], ["Callsign", name_input, "Pilot"], ["Public join code", code_input, "canadaverse"]]:
		connection.add_child(_label(pair[0], 15))
		pair[1].text = pair[2]
		pair[1].custom_minimum_size.y = 38
		connection.add_child(pair[1])
	_button(connection, "CONNECT", _connect)
	_sound_controls(connection)
	var deployment := _panel(screens, Vector2(520, 0))
	deployment_panel = deployment.get_parent()
	deployment_panel.hide()
	deployment.add_child(_label("Choose your deployment", 26))
	var sides := HBoxContainer.new()
	deployment.add_child(sides)
	for pair in [["CRIMSON", 1], ["AZURE", 2]]:
		var side: int = pair[1]
		var button := _button(sides, pair[0], func(): network.choose_team(side); _refresh_pads())
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	deployment.add_child(_label("Select a friendly pad here or on the tactical map.", 15))
	pad_choice.custom_minimum_size.y = 36
	deployment.add_child(pad_choice)
	pad_choice.item_selected.connect(func(index: int): selected_pad = pad_choice.get_item_id(index); map_control.selected = selected_pad)
	vehicle_choice.add_item("Tank", 0)
	vehicle_choice.add_item("Scout", 1)
	vehicle_choice.custom_minimum_size.y = 36
	deployment.add_child(vehicle_choice)
	deploy_button = _button(deployment, "DEPLOY", _request_spawn)
	resume_button = _button(deployment, "RESUME / F1", func(): _set_menu(false))
	_button(deployment, "DISCONNECT", func(): network.disconnect_game(); status_label.text = "Disconnected.")
	_sound_controls(deployment)
	var footer := cockpit_frame
	ui.add_child(footer)
	footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	footer.offset_top = -Cockpit.HEIGHT
	var radar := Radar.new()
	radar.network = network
	radar.local_view = true
	radar.classic = true
	radar_control = radar
	footer.add_child(radar)
	footer.radar = radar
	var cockpit := _panel(footer, Vector2.ZERO)
	cockpit.add_theme_constant_override("separation", 4)
	var cockpit_style := StyleBoxFlat.new()
	cockpit_style.bg_color = Color(0.015, 0.015, 0.02, 0.97)
	cockpit_style.set_content_margin_all(10)
	cockpit.get_parent().add_theme_stylebox_override("panel", cockpit_style)
	footer.instruments = cockpit.get_parent()
	var meters := HBoxContainer.new()
	cockpit.add_child(meters)
	for pair in [["ARMOUR", health_bar], ["FUEL", fuel_bar]]:
		var box := VBoxContainer.new()
		box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		meters.add_child(box)
		box.add_child(_label(pair[0], 12))
		pair[1].custom_minimum_size = Vector2(100, 16)
		pair[1].show_percentage = false
		box.add_child(pair[1])
	var charge_box := VBoxContainer.new()
	charge_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	meters.add_child(charge_box)
	charge_label.add_theme_font_size_override("font_size", 12)
	charge_box.add_child(charge_label)
	charge_bar.custom_minimum_size = Vector2(100, 16)
	charge_bar.show_percentage = false
	charge_box.add_child(charge_bar)
	status_label.text = "Connect to join the public battlefield."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.max_lines_visible = 2
	status_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	status_label.add_theme_font_size_override("font_size", 15)
	cockpit.add_child(status_label)
	telemetry_label.add_theme_font_size_override("font_size", 13)
	cockpit.add_child(telemetry_label)
	comms.network = network
	cockpit.add_child(comms)
	map_control = Radar.new()
	map_control.network = network
	map_control.classic = true
	map_control.pad_selected.connect(func(id: int): selected_pad = id; _refresh_pads())
	footer.add_child(map_control)
	footer.tactical_map = map_control
	reticle.text = "+"
	reticle.add_theme_font_size_override("font_size", 28)
	ui.add_child(reticle)
	reticle.mouse_filter = Control.MOUSE_FILTER_IGNORE

func _display_status(message: String) -> void:
	status_label.text = _asset_error if not _asset_error.is_empty() else _map_error if not _map_error.is_empty() else message

func _sound_controls(parent: Node) -> void:
	parent.add_child(_label("Sound volume", 15))
	var slider := HSlider.new()
	slider.min_value = 0
	slider.max_value = 100
	slider.value = audio.volume * 100.0
	slider.custom_minimum_size.y = 24
	parent.add_child(slider)
	sound_sliders.append(slider)
	slider.value_changed.connect(func(value: float):
		audio.set_volume(value / 100.0)
		for other in sound_sliders:
			other.set_value_no_signal(value))
	var box := CheckBox.new()
	box.text = "Mute when this window is in the background"
	box.button_pressed = audio.mute_unfocused
	parent.add_child(box)
	mute_boxes.append(box)
	box.toggled.connect(func(value: bool):
		audio.mute_unfocused = value
		audio.save_settings()
		for other in mute_boxes:
			other.set_pressed_no_signal(value))

func _connect() -> void:
	comms.clear()
	_spawn_until = 0.0
	selected_pad = 0
	network.connect_game(host_input.text.strip_edges(), server_port, name_input.text.strip_edges(), code_input.text)

func _refresh_pads() -> void:
	pad_choice.clear()
	_smoke_pads.clear()
	for id in network.entities:
		var item: Dictionary = network.entities[id]
		if item.get("unit") == 27 and item.get("team") == network.team and item.get("health", 0.0) > 0:
			pad_choice.add_item("Repair pad %d" % id, id)
			_smoke_pads.append(id)
			if id == selected_pad:
				pad_choice.select(pad_choice.item_count - 1)
	if not _smoke_pads.has(selected_pad):
		selected_pad = _smoke_pads[0] if not _smoke_pads.is_empty() else 0
	map_control.selected = selected_pad
	deploy_button.disabled = selected_pad == 0 or not terrain_loaded or not assets_loaded or not audio.loaded or not feedback.configured or network.vehicle_id != 0

func _request_spawn() -> void:
	if not terrain_loaded or not assets_loaded or selected_pad == 0:
		return
	_spawn_until = Network.now() + 20.0
	_spawn_retry_at = 0.0
	status_label.text = "Requesting deployment. Waiting for a clear repair pad…"

func _on_deployed() -> void:
	_spawn_until = 0.0
	vehicle_input.reset()
	var unit: int = network.entities[network.vehicle_id].unit
	if network.vehicle_settings.size() > unit:
		vehicle_input.jet = network.vehicle_settings[unit].jet_start
	_set_menu(not get_window().has_focus() and not _smoke)
	_deployed_at = Network.now()
	_last_input_time = _deployed_at
	_first_position = network.entities[network.vehicle_id].pos
	status_label.text = "Mouse aim · Left fire · Right/1 pulse or repair · 2 piercer · Space jump · F1 menu · F2 view"
	print("MODERN_DEPLOYED team=%d vehicle=%d" % [network.team, network.entities[network.vehicle_id].unit])
	if "--capture-deployment" in OS.get_cmdline_user_args():
		get_tree().create_timer(1.0).timeout.connect(_capture)

func _process(delta: float) -> void:
	if _input_rearm and not _menu_open and comms.mode.is_empty() and not _held_controls():
		_input_rearm = false
	audio.focused = get_window().has_focus()
	feedback.first_person = _first_person
	connection_panel.visible = network.state == "offline"
	deployment_panel.visible = network.state == "ready" and (network.vehicle_id == 0 or _menu_open)
	resume_button.disabled = network.vehicle_id == 0
	chat_button.disabled = network.state != "ready"
	players_button.disabled = network.state != "ready"
	health_bar.value = network.health * 100.0
	fuel_bar.value = network.fuel * 100.0
	charge_bar.value = (network.repair_charge if network.weapon_table == 1 else network.pulse_charge) * 100.0
	charge_label.text = "REPAIR" if network.weapon_table == 1 else "PULSE"
	reticle.visible = network.vehicle_id != 0 and not _menu_open and comms.mode.is_empty()
	if network.vehicle_id == 0 and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		vehicle_input.clear_motion()
	telemetry_label.text = "%s · %s · %d ms" % [{1: "Crimson", 2: "Azure"}.get(network.team, "Unassigned"), network.map_name.capitalize(), network.ping_ms] if network.state == "ready" else ""
	if Network.now() >= _refresh_at:
		_refresh_pads()
		_refresh_at = Network.now() + 1.0
	_sync_visuals(delta)
	if _spawn_until > Network.now() and Network.now() >= _spawn_retry_at and network.vehicle_id == 0:
		network.spawn_at(selected_pad, vehicle_choice.get_selected_id())
		_spawn_retry_at = Network.now() + 1.0
	elif _spawn_until > 0.0 and Network.now() >= _spawn_until:
		_spawn_until = 0.0
		status_label.text = "That pad remains blocked. Choose another friendly pad and retry."
	if Network.now() >= _input_at and network.vehicle_id != 0:
		_input_at = Network.now() + 0.04
		var focused := _driving()
		var forward := float(Input.is_physical_key_pressed(KEY_W)) - float(Input.is_physical_key_pressed(KEY_S)) if focused else 0.0
		var turn := float(Input.is_physical_key_pressed(KEY_E)) - float(Input.is_physical_key_pressed(KEY_Q)) if focused else 0.0
		turn *= 1.0 if Input.is_physical_key_pressed(KEY_SHIFT) else 0.6
		var strafe := float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)) if focused else 0.0
		var aim := vehicle_input.sample(Network.now() - _last_input_time, turn)
		_last_input_time = Network.now()
		var fire := focused and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT)
		var secondary := focused and (Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT) or Input.is_physical_key_pressed(KEY_1))
		var scout := network.weapon_table == 1
		var exercise := Network.now() - _deployed_at
		if _combat_smoke:
			fire = exercise > .3 and exercise < .8
			secondary = exercise > 1.2 and exercise < 1.4
		network.controls(0.7 if _smoke else forward, aim.turn if focused else 0.0, strafe, fire,
			focused and Input.is_physical_key_pressed(KEY_SPACE), aim.tilt, aim.jet,
			secondary and not scout, focused and scout and (secondary or Input.is_physical_key_pressed(KEY_R)),
			(not scout and focused and Input.is_physical_key_pressed(KEY_2)) or (_combat_smoke and exercise > 2.0 and exercise < 2.4))
	if _smoke:
		_smoke_step()

func _driving() -> bool:
	return network.vehicle_id != 0 and get_window().has_focus() and not _smoke and not _menu_open and comms.mode.is_empty() and not _input_rearm and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED

static func _held_controls() -> bool:
	for key in [KEY_W, KEY_A, KEY_S, KEY_D, KEY_Q, KEY_E, KEY_R, KEY_SPACE, KEY_1, KEY_2]:
		if Input.is_physical_key_pressed(key):
			return true
	return Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT) or Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT)

func _social_mode_changed(_mode: String) -> void:
	_refresh_input_capture()

func _focus_exited() -> void:
	# An owned OptionButton popup also takes window focus. Hiding its parent
	# during that transition destroys the popup while Godot is registering it.
	if comms.mode.is_empty():
		_set_menu(true)
	else:
		_refresh_input_capture()

func _refresh_input_capture() -> void:
	vehicle_input.clear_motion()
	# A click on Send/Resume must be released before it can fire a weapon.
	_input_rearm = true
	var capture := not _menu_open and comms.mode.is_empty() and network.vehicle_id != 0 and get_window().has_focus() and not _smoke
	if capture:
		var focus := get_viewport().gui_get_focus_owner()
		if focus != null:
			focus.release_focus()
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED if capture else Input.MOUSE_MODE_VISIBLE
	network.controls(0.0, 0.0, 0.0, false, false, vehicle_input.tilt, vehicle_input.jet)

func _set_menu(open: bool) -> void:
	_menu_open = open
	if open:
		comms.close()
	_refresh_input_capture()

func _input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and _driving():
		vehicle_input.mouse_motion(event.screen_relative)
		get_viewport().set_input_as_handled()
	elif event is InputEventMouseButton and event.pressed and _driving():
		if event.button_index in [MOUSE_BUTTON_WHEEL_UP, MOUSE_BUTTON_WHEEL_DOWN]:
			var minimum := 0.0
			var unit: int = network.entities.get(network.vehicle_id, {}).get("unit", 0)
			if network.vehicle_settings.size() > unit:
				minimum = network.vehicle_settings[unit].jet_minimum
			vehicle_input.jet = clampf(vehicle_input.jet + (0.05 if event.button_index == MOUSE_BUTTON_WHEEL_UP else -0.05), minimum, 1.0)
			get_viewport().set_input_as_handled()

func _unhandled_key_input(event: InputEvent) -> void:
	if _closing:
		return
	if not event.is_pressed() or event.is_echo():
		return
	if event.keycode in [KEY_ESCAPE, KEY_F1]:
		if not comms.mode.is_empty() and event.keycode == KEY_ESCAPE:
			comms.close()
		else:
			_set_menu(not _menu_open)
		get_viewport().set_input_as_handled()
	elif event.keycode in [KEY_ENTER, KEY_KP_ENTER] and network.state == "ready" and comms.mode.is_empty():
		comms.open_chat(event.shift_pressed)
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_F4:
		comms.toggle_players()
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_F2:
		_first_person = not _first_person
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_F12:
		_capture()
		get_viewport().set_input_as_handled()

func _quit_safely(code := 0) -> void:
	if _closing:
		return
	_closing = true
	set_process(false)
	network.disconnect_game()
	feedback.reset()
	# Give the audio mixer a bounded moment to release stopped playback queues.
	await get_tree().create_timer(.08).timeout
	get_tree().quit(code)

static func world_position(p: Vector3) -> Vector3:
	return Vector3(p.x, p.z, -p.y) * SCALE

func _sync_visuals(delta: float) -> void:
	for id in visuals.keys():
		if not network.entities.has(id):
			visuals[id].queue_free()
			visuals.erase(id)
	for id in network.entities:
		var item: Dictionary = network.entities[id]
		if not item.has("pos") or not item.has("unit"):
			continue
		if not visuals.has(id):
			if not assets_loaded:
				continue
			var model_name: String = Assets.model_name(item.unit, item.get("team", 0))
			if model_name.is_empty():
				continue
			var original: Dictionary = assets.model(model_name)
			if original.is_empty():
				status_label.text = "Could not load original graphics: " + model_name
				continue
			var mesh := MeshInstance3D.new()
			mesh.mesh = original.mesh
			add_child(mesh)
			mesh.position = world_position(item.pos)
			visuals[id] = mesh
		var target: Vector3 = world_position(item.pos)
		visuals[id].position = visuals[id].position.lerp(target, 1.0 - exp(-18.0 * delta))
		if item.has("rot"):
			visuals[id].basis = Basis(visuals[id].basis.get_rotation_quaternion().slerp(VehicleInput.world_basis(item.rot).get_rotation_quaternion(), 1.0 - exp(-18.0 * delta)))
	if network.entities.has(network.vehicle_id) and visuals.has(network.vehicle_id):
		var item: Dictionary = network.entities[network.vehicle_id]
		var target: Vector3 = visuals[network.vehicle_id].position
		var orientation: Basis = visuals[network.vehicle_id].basis
		var direction := orientation * Vector3.RIGHT
		var original: Dictionary = assets.model(Assets.model_name(item.unit, item.team))
		var eye: Vector3 = original.get("attachments", {}).get("eye", Vector3.ZERO)
		camera.position = target + orientation * eye if _first_person else target - direction * 7.5 + Vector3.UP * 3.8
		camera.look_at(camera.position + direction if _first_person else target + direction * 12, orientation * Vector3.UP)
		var aim_point := target + direction * 100.0
		if not camera.is_position_behind(aim_point):
			reticle.position = camera.unproject_position(aim_point) - reticle.size * 0.5
		visuals[network.vehicle_id].visible = not _first_person

func _load_map(name_value: String) -> void:
	_map_error = ""
	for visual in visuals.values():
		visual.queue_free()
	visuals.clear()
	terrain_loaded = false
	terrain.mesh = null
	original_sky.mesh = null
	original_sky.theme = ""
	map_control.overview = null
	radar_control.overview = null
	var path := "res://content/maps/" + name_value + ".land"
	if not FileAccess.file_exists(path):
		path = OS.get_executable_path().get_base_dir().path_join("maps/" + name_value + ".land")
	if not FileAccess.file_exists(path):
		_map_error = "Map content is missing. Extract the complete client package and reopen it."
		_display_status(_map_error)
		return
	if not assets_loaded or not terrain.build(path, assets):
		_map_error = terrain.error if assets_loaded else "Original graphics are missing."
		_display_status(_map_error)
		return
	world_size = terrain.world_size
	var sky_path := path.trim_suffix(".land") + ".start_script"
	if not FileAccess.file_exists(sky_path) or not original_sky.build(FileAccess.get_file_as_string(sky_path), world_size, assets):
		_map_error = original_sky.error if not original_sky.error.is_empty() else "Original map sky settings are missing. Extract the complete client package."
		_display_status(_map_error)
		return
	camera.far = maxf(1800, world_size.length() * SCALE * 2.0 + 400)
	map_control.world_size = world_size
	radar_control.world_size = world_size
	map_control.overview = terrain.overview
	radar_control.overview = terrain.overview
	terrain_loaded = true
	camera.position = Vector3(world_size.x * SCALE * 0.5, 160, -world_size.y * SCALE * 0.25)
	camera.look_at(Vector3(world_size.x * SCALE * 0.5, 0, -world_size.y * SCALE * 0.5))

func _smoke_step() -> void:
	if network.state == "ready" and network.team == 0:
		network.choose_team(1)
		_refresh_pads()
	if network.state == "ready" and network.vehicle_id == 0 and not _smoke_pads.is_empty() and Network.now() >= _spawn_retry_at:
		selected_pad = _smoke_pads[_smoke_attempt % _smoke_pads.size()]
		_smoke_attempt += 1
		network.spawn_at(selected_pad)
		_spawn_retry_at = Network.now() + 1.0
	if network.vehicle_id != 0 and network.entities.has(network.vehicle_id):
		var position: Vector3 = network.entities[network.vehicle_id].pos
		_moved = maxf(_moved, position.distance_to(_first_position))
		if _moved > 3.0 and terrain_loaded and assets_loaded and audio.loaded and feedback.configured and Network.now() - _deployed_at > 3.0:
			var passed := not _combat_smoke or (feedback.shot_events > 0 and network.firing_packets > 0)
			print("MODERN_ONLINE " + JSON.stringify({"passed": passed, "map": network.map_name, "entities": network.entities.size(), "snapshots": network.snapshots, "movement": _moved, "malformed": network.malformed, "terrain_loaded": terrain_loaded, "audio_loaded": audio.loaded, "audio_started": audio.started, "feedback_events": feedback.events_played, "shot_events": feedback.shot_events, "firing_packets": network.firing_packets}))
			_smoke = false
			_quit_safely(0 if passed else 1)
			return
	if Network.now() - _smoke_started > 35.0 or (network.state == "offline" and Network.now() - _smoke_started > 2.0):
		print("MODERN_ONLINE " + JSON.stringify({"passed": false, "state": network.state, "map": network.map_name, "entities": network.entities.size(), "malformed": network.malformed, "message": status_label.text}))
		_smoke = false
		_quit_safely(1)

func _ui_check() -> void:
	for dimensions in [Vector2i(800, 600), Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440)]:
		get_window().size = dimensions
		await get_tree().process_frame
		await get_tree().process_frame
		assert(connection_panel.get_global_rect().size.x <= ui.size.x)
		assert(map_control.get_global_rect().end.x <= ui.size.x)
		assert(host_input.get_global_rect().intersects(connection_panel.get_global_rect()))
		assert(cockpit_frame.instruments.get_global_rect().end.y <= ui.size.y - 16)
	print("MODERN_UI_LAYOUT=PASS")
	get_tree().quit()

func _capture() -> void:
	if DisplayServer.get_name() == "headless":
		return
	await RenderingServer.frame_post_draw
	var directory := ProjectSettings.globalize_path(_capture_dir)
	if DirAccess.make_dir_recursive_absolute(directory) != OK:
		status_label.text = "Could not create the screenshot folder."
		return
	var path := directory.path_join("frame-%d" % Time.get_ticks_msec())
	var image := get_viewport().get_texture().get_image()
	if image.save_png(path + ".png") != OK:
		status_label.text = "Could not save the screenshot."
		return
	var record := {"image": image.get_size(), "window": get_window().size, "canvas": ui.size,
		"state": network.state, "team": network.team, "vehicle_id": network.vehicle_id,
		"health": network.health, "fuel": network.fuel, "entities": network.entities.size(),
		"terrain_loaded": terrain_loaded, "map": network.map_name, "malformed": network.malformed,
		"deployment": deployment_panel.get_global_rect(), "map_rect": map_control.get_global_rect(),
		"selected_pad": selected_pad, "snapshots": network.snapshots, "fps": Engine.get_frames_per_second()}
	record["original_models"] = assets.model_cache.size()
	record["original_sky"] = original_sky.theme
	record["original_textures"] = assets.texture_cache.size()
	record["asset_errors"] = assets.errors
	record["terrain_build_msec"] = terrain.build_msec
	record["terrain_texture_bytes"] = terrain.texture_bytes
	record["cockpit_instruments"] = cockpit_frame.instruments.get_global_rect()
	record["audio_loaded"] = audio.loaded
	record["audio_started"] = audio.started
	record["audio_peak_voices"] = audio.peak_voices
	record["feedback_events"] = feedback.events_played
	record["movement_packets"] = network.movement_packets
	record["firing_packets"] = network.firing_packets
	record["position"] = network.entities.get(network.vehicle_id, {}).get("pos", Vector3.ZERO)
	record["rotation"] = network.entities.get(network.vehicle_id, {}).get("rot", Vector3.ZERO)
	record["aim_tilt"] = vehicle_input.tilt
	record["jet"] = vehicle_input.jet
	record["mouse_captured"] = Input.mouse_mode == Input.MOUSE_MODE_CAPTURED
	record["action_maximum"] = network.action_maximum
	record["pulse_charge"] = network.pulse_charge
	record["repair_charge"] = network.repair_charge
	var file := FileAccess.open(path + ".json", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(record, "  "))
	print("MODERN_CAPTURE " + path + ".png")
