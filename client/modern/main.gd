extends Node3D

const Network = preload("res://network.gd")
const Radar = preload("res://radar.gd")
const Assets = preload("res://original_assets.gd")
const Terrain = preload("res://terrain.gd")
const SCALE := 0.1
var network := Network.new()
var camera := Camera3D.new()
var terrain := Terrain.new()
var visuals: Dictionary = {}
var assets := Assets.new()
var assets_loaded := false
var ui := Control.new()
var connection_panel: Control
var deployment_panel: Control
var host_input := LineEdit.new()
var name_input := LineEdit.new()
var code_input := LineEdit.new()
var pad_choice := OptionButton.new()
var vehicle_choice := OptionButton.new()
var deploy_button: Button
var status_label := Label.new()
var telemetry_label := Label.new()
var health_bar := ProgressBar.new()
var fuel_bar := ProgressBar.new()
var map_control: Control
var terrain_loaded := false
var selected_pad := 0
var world_size := Vector2(5600, 5600)
var _input_at := 0.0
var _refresh_at := 0.0
var _spawn_retry_at := 0.0
var _spawn_until := 0.0
var _smoke := false
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
	add_child(network)
	add_child(camera)
	add_child(terrain)
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
	environment.background_color = Color("7992a3")
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color("a9bcc8")
	environment.ambient_light_energy = 0.25
	environment_node.environment = environment
	add_child(environment_node)
	_build_ui()
	var asset_path := "res://content/original"
	if not FileAccess.file_exists(asset_path.path_join("palette0")):
		asset_path = OS.get_executable_path().get_base_dir().path_join("original")
	if FileAccess.file_exists(asset_path.path_join("palette0")):
		assets_loaded = assets.open_directory(asset_path)
	if not assets_loaded:
		status_label.text = "Original graphics are required. Import the preserved assets before deployment."
	network.status_changed.connect(func(message: String): status_label.text = message)
	network.world_changed.connect(_load_map)
	network.deployed.connect(_on_deployed)
	var args := OS.get_cmdline_user_args()
	for value in args:
		if value.begins_with("--capture-dir="):
			_capture_dir = value.trim_prefix("--capture-dir=")
	if "--fullscreen" in args:
		DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)
	_smoke = "--online-smoke" in args
	_smoke_started = Network.now()
	if "--connect" in args or _smoke:
		for value in args:
			if value.begins_with("--server="):
				host_input.text = value.trim_prefix("--server=")
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
	button.pressed.connect(action)
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
	var menu_button := _button(ui, "DEPLOYMENT", func(): _menu_open = not _menu_open)
	menu_button.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT)
	menu_button.offset_left = -200
	menu_button.offset_right = -28
	menu_button.offset_top = 22
	menu_button.offset_bottom = 64
	var center := CenterContainer.new()
	ui.add_child(center)
	center.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	center.offset_bottom = -190
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
	_button(deployment, "DISCONNECT", func(): network.disconnect_game(); status_label.text = "Disconnected.")
	var footer := HBoxContainer.new()
	ui.add_child(footer)
	footer.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_WIDE)
	footer.offset_left = 20
	footer.offset_right = -20
	footer.offset_top = -182
	footer.offset_bottom = -18
	footer.add_theme_constant_override("separation", 12)
	var radar := Radar.new()
	radar.network = network
	radar.local_view = true
	footer.add_child(radar)
	var cockpit := _panel(footer, Vector2(0, 164))
	cockpit.get_parent().size_flags_horizontal = Control.SIZE_EXPAND_FILL
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
	status_label.text = "Connect to join the public battlefield."
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	status_label.add_theme_font_size_override("font_size", 15)
	cockpit.add_child(status_label)
	telemetry_label.add_theme_font_size_override("font_size", 13)
	cockpit.add_child(telemetry_label)
	map_control = Radar.new()
	map_control.network = network
	map_control.custom_minimum_size.x = 236
	map_control.pad_selected.connect(func(id: int): selected_pad = id; _refresh_pads())
	footer.add_child(map_control)
	var reticle := _label("+", 28)
	ui.add_child(reticle)
	reticle.set_anchors_and_offsets_preset(Control.PRESET_CENTER)
	reticle.offset_top = -70
	reticle.mouse_filter = Control.MOUSE_FILTER_IGNORE

func _connect() -> void:
	_spawn_until = 0.0
	selected_pad = 0
	network.connect_game(host_input.text.strip_edges(), 2627, name_input.text.strip_edges(), code_input.text)

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
	deploy_button.disabled = selected_pad == 0 or not terrain_loaded or not assets_loaded

func _request_spawn() -> void:
	if not terrain_loaded or not assets_loaded or selected_pad == 0:
		return
	_spawn_until = Network.now() + 20.0
	_spawn_retry_at = 0.0
	status_label.text = "Requesting deployment. Waiting for a clear repair pad…"

func _on_deployed() -> void:
	_spawn_until = 0.0
	_menu_open = false
	_deployed_at = Network.now()
	_first_position = network.entities[network.vehicle_id].pos
	status_label.text = "W/S move · A/D strafe · Q/E turn · Space jump · Left mouse fire · F2 camera · F12 screenshot"
	print("MODERN_DEPLOYED team=%d vehicle=%d" % [network.team, network.entities[network.vehicle_id].unit])
	if "--capture-deployment" in OS.get_cmdline_user_args():
		get_tree().create_timer(1.0).timeout.connect(_capture)

func _process(delta: float) -> void:
	connection_panel.visible = network.state == "offline"
	deployment_panel.visible = network.state == "ready" and (network.vehicle_id == 0 or _menu_open)
	health_bar.value = network.health * 100.0
	fuel_bar.value = network.fuel * 100.0
	telemetry_label.text = "%s  /  %s  /  %d ms  /  %d objects" % [network.map_name.to_upper(), network.state.to_upper(), network.ping_ms, network.entities.size()]
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
		var focused := get_window().has_focus() and not _smoke and not _menu_open
		var forward := float(Input.is_physical_key_pressed(KEY_W)) - float(Input.is_physical_key_pressed(KEY_S)) if focused else 0.0
		var turn := float(Input.is_physical_key_pressed(KEY_E)) - float(Input.is_physical_key_pressed(KEY_Q)) if focused else 0.0
		var strafe := float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)) if focused else 0.0
		var fire := focused and Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT) and get_viewport().gui_get_hovered_control() == null
		network.controls(0.7 if _smoke else forward, turn, strafe, fire, focused and Input.is_physical_key_pressed(KEY_SPACE))
	if _smoke:
		_smoke_step()

func _unhandled_key_input(event: InputEvent) -> void:
	if not event.is_pressed() or event.is_echo():
		return
	if event.keycode == KEY_ESCAPE:
		_menu_open = not _menu_open
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_F2:
		_first_person = not _first_person
		get_viewport().set_input_as_handled()
	elif event.keycode == KEY_F12:
		_capture()
		get_viewport().set_input_as_handled()

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
			visuals[id].rotation.y = lerp_angle(visuals[id].rotation.y, item.rot.z, 1.0 - exp(-18.0 * delta))
	if network.entities.has(network.vehicle_id) and visuals.has(network.vehicle_id):
		var item: Dictionary = network.entities[network.vehicle_id]
		var target: Vector3 = visuals[network.vehicle_id].position
		var yaw: float = item.get("rot", Vector3.ZERO).z
		var direction := Vector3(cos(yaw), 0, -sin(yaw))
		var original: Dictionary = assets.model(Assets.model_name(item.unit, item.team))
		var eye: Vector3 = original.get("attachments", {}).get("eye", Vector3.ZERO)
		camera.position = target + Basis(Vector3.UP, yaw) * eye if _first_person else target - direction * 7.5 + Vector3.UP * 3.8
		camera.look_at(target + direction * 12 + Vector3.UP * 0.6)
		visuals[network.vehicle_id].visible = not _first_person

func _load_map(name_value: String) -> void:
	terrain_loaded = false
	terrain.mesh = null
	var path := "res://content/maps/" + name_value + ".land"
	if not FileAccess.file_exists(path):
		path = OS.get_executable_path().get_base_dir().path_join("maps/" + name_value + ".land")
	if not FileAccess.file_exists(path):
		status_label.text = "Map content missing. Import the preserved maps before deployment."
		return
	if not assets_loaded or not terrain.build(path, assets):
		status_label.text = terrain.error if assets_loaded else "Original graphics are missing."
		return
	world_size = terrain.world_size
	map_control.world_size = world_size
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
		if _moved > 3.0 and terrain_loaded and assets_loaded and Network.now() - _deployed_at > 3.0:
			print("MODERN_ONLINE " + JSON.stringify({"passed": true, "map": network.map_name, "entities": network.entities.size(), "snapshots": network.snapshots, "movement": _moved, "malformed": network.malformed, "terrain_loaded": terrain_loaded}))
			_smoke = false
			network.disconnect_game()
			get_tree().quit()
			return
	if Network.now() - _smoke_started > 35.0 or (network.state == "offline" and Network.now() - _smoke_started > 2.0):
		print("MODERN_ONLINE " + JSON.stringify({"passed": false, "state": network.state, "map": network.map_name, "entities": network.entities.size(), "malformed": network.malformed, "message": status_label.text}))
		_smoke = false
		network.disconnect_game()
		get_tree().quit(1)

func _ui_check() -> void:
	for dimensions in [Vector2i(800, 600), Vector2i(1280, 720), Vector2i(1920, 1080), Vector2i(2560, 1440)]:
		get_window().size = dimensions
		await get_tree().process_frame
		await get_tree().process_frame
		assert(connection_panel.get_global_rect().size.x <= ui.size.x)
		assert(map_control.get_global_rect().end.x <= ui.size.x)
		assert(host_input.get_global_rect().intersects(connection_panel.get_global_rect()))
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
	record["original_textures"] = assets.texture_cache.size()
	record["asset_errors"] = assets.errors
	record["movement_packets"] = network.movement_packets
	record["firing_packets"] = network.firing_packets
	record["position"] = network.entities.get(network.vehicle_id, {}).get("pos", Vector3.ZERO)
	var file := FileAccess.open(path + ".json", FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(record, "  "))
	print("MODERN_CAPTURE " + path + ".png")
