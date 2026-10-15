extends SceneTree
## Short private-server combat journey. Never connects to a public endpoint.
const Network = preload("res://network.gd")
const Assets = preload("res://original_assets.gd")
const Audio = preload("res://original_audio.gd")
const Feedback = preload("res://combat_feedback.gd")
var network := Network.new()
var phase := "tank"
var spawned_at := 0.0
var first_position := Vector3.ZERO
var retry_at := 0.0
var input_at := 0.0
var command_ack := false
var completed: Array = []
var combat_events: Dictionary = {}
var projectile_events: Array = []

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	Engine.max_fps = 120
	root.add_child(network)
	var assets := Assets.new()
	var sound := Audio.new()
	var feedback := Feedback.new()
	var camera := Camera3D.new()
	root.add_child(sound)
	root.add_child(camera)
	sound.force_quiet = true
	sound.listener = camera
	assert(assets.open_directory("res://content/original"))
	assert(sound.open_directory("res://content/original/audio"))
	feedback.assets = assets
	feedback.audio = sound
	feedback.network = network
	feedback.camera = camera
	root.add_child(feedback)
	assert(feedback.configure())
	network.transient.connect(func(event: Dictionary):
		if event.type >= 0x100:
			combat_events[str(event.type)] = int(combat_events.get(str(event.type), 0)) + 1
			if event.type in [0x102, 0x103]:
				projectile_events.append(event.get("secondary", 0)))
	var port := int(OS.get_environment("WULFRAM_TEST_PORT"))
	if port < 1024 or not OS.has_environment("WULFRAM_TEST_JOIN_CODE"):
		quit(1)
		return
	network.deployed.connect(func(): spawned_at = Network.now(); first_position = network.entities[network.vehicle_id].pos)
	network.reliable_delivered.connect(func(_sequence: int, success: bool): command_ack = success)
	network.connect_game("127.0.0.1", port, "ModernCombatCheck", OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
	var started := Network.now()
	var requested_command := false
	while Network.now() - started < 30.0:
		await process_frame
		if network.state == "offline":
			break
		if network.state != "ready":
			continue
		if not requested_command:
			requested_command = network.send_chat("/s vehicle auto", 1) > 0
		if not command_ack:
			continue
		var desired_team := 1 if phase == "tank" else 2
		if network.team != desired_team:
			network.choose_team(desired_team)
			continue
		if network.vehicle_id == 0:
			if Network.now() >= retry_at:
				for id in network.entities:
					var item: Dictionary = network.entities[id]
					if item.get("unit") == 27 and item.get("team") == desired_team:
						network.spawn_at(id, 0 if phase == "tank" else 1)
						break
				retry_at = Network.now() + 0.5
			continue
		var elapsed := Network.now() - spawned_at
		camera.position = Feedback.world(network.entities[network.vehicle_id].pos) + Vector3(0, 2, 5)
		if Network.now() >= input_at:
			input_at = Network.now() + .04
			network.controls(.5, -.15, .1, elapsed < .8, elapsed > .8 and elapsed < 1.0,
				.001 if elapsed < 1.0 else .2, .8,
				phase == "tank" and elapsed > 1.2 and elapsed < 1.4,
				phase == "scout" and elapsed > 1.0,
				phase == "tank" and elapsed > 2.0 and elapsed < 2.8)
		if elapsed > 3.5:
			var distance: float = network.entities[network.vehicle_id].pos.distance_to(first_position)
			completed.append({"vehicle": phase, "movement": distance, "fuel": network.fuel,
				"unit": network.entities[network.vehicle_id].unit, "weapon_table": network.weapon_table,
				"charge": network.pulse_charge if phase == "tank" else network.repair_charge})
			if phase == "tank":
				phase = "scout"
				network.controls(0, 0, 0, false, false)
				network.choose_team(2)
			else:
				break
	var passed := completed.size() == 2 and command_ack and network.action_maximum == 1.0 and network.malformed == 0 and sound.started > 0 and feedback.events_played > 0
	for kind in [0x100, 0x101, 0x102, 0x103]:
		passed = passed and combat_events.has(str(kind))
	for row in completed:
		var expected := 0 if row.vehicle == "tank" else 1
		passed = passed and row.movement > 3.0 and row.fuel < 1.0 and row.unit == expected and row.weapon_table == expected
	print("MODERN_SESSION " + JSON.stringify({"passed": passed, "journeys": completed, "command_ack": command_ack,
		"snapshots": network.snapshots, "malformed": network.malformed, "action_maximum": network.action_maximum,
		"combat_events": combat_events, "projectile_event_ids": projectile_events, "audio_voice_requests": sound.started,
		"peak_audio_voices": sound.peak_voices, "effect_events": feedback.events_played}))
	network.disconnect_game()
	feedback.reset()
	feedback.queue_free()
	sound.queue_free()
	camera.queue_free()
	network.queue_free()
	await process_frame
	quit(0 if passed else 1)
