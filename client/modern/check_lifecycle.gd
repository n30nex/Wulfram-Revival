extends SceneTree
## Short private-server death/redeployment check; no public endpoint is allowed.
const Network = preload("res://network.gd")

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	Engine.max_fps = 120
	var port := int(OS.get_environment("WULFRAM_TEST_PORT"))
	if port < 1024 or not OS.has_environment("WULFRAM_TEST_JOIN_CODE"):
		quit(1)
		return
	var network := Network.new()
	root.add_child(network)
	var spawned: Array = []
	var spawn_at := [0.0]
	network.deployed.connect(func():
		if network.vehicle_id not in spawned:
			spawned.append(network.vehicle_id)
			spawn_at[0] = Network.now())
	network.connect_game("127.0.0.1", port, "ModernLifecycleCheck", OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
	var started := Network.now()
	var retry := 0.0
	var input_at := 0.0
	var cleared := false
	var next_map := OS.get_environment("WULFRAM_TEST_NEXT_MAP")
	var map_requested := false
	var old_entities: Array = []
	var old_player := 0
	var old_generation := 0
	var replay_count := 0
	var reconnected := false
	var map_clean := false
	var passed := false
	var spawn_attempt := 0
	while Network.now() - started < (45.0 if not next_map.is_empty() else 18.0):
		await process_frame
		if network.state == "offline":
			break
		if network.state != "ready":
			continue
		if network.team != 1:
			network.choose_team(1)
			continue
		if not spawned.is_empty() and network.vehicle_id == 0:
			cleared = true
		var awaiting_map := map_requested and network.map_name != next_map
		if network.vehicle_id == 0 and not awaiting_map and Network.now() >= retry:
			var pads: Array = []
			for id in network.entities:
				var item: Dictionary = network.entities[id]
				if item.get("unit") == 27 and item.get("team") == 1:
					pads.append(id)
			if not pads.is_empty():
				network.spawn_at(pads[spawn_attempt % pads.size()])
				spawn_attempt += 1
			retry = Network.now() + .4
		if network.vehicle_id != 0 and Network.now() >= input_at:
			var movement := 0.0
			if spawned.size() >= 2:
				movement = -.35 if Network.now() - spawn_at[0] < .2 else .6
			network.controls(movement, 0, 0, false, false)
			input_at = Network.now() + .04
		if spawned.size() == 2 and next_map.is_empty():
			passed = cleared and network.health > .99
			break
		if spawned.size() == 2 and not map_requested and Network.now() - spawn_at[0] > 1.2:
			old_entities = network.entities.keys()
			map_requested = network.send_chat("/s lifecycle-map", 1) > 0
		if spawned.size() == 3 and not reconnected and Network.now() - spawn_at[0] > 1.0:
			map_clean = network.map_name == next_map
			for id in old_entities:
				map_clean = map_clean and not network.entities.has(id)
			replay_count = network.ignored_world_packets
			old_player = network.player_id
			old_generation = network.native_generation
			network.disconnect_game()
			await create_timer(.3).timeout
			network.connect_game("127.0.0.1", port, "ModernLifecycleCheck", OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
			reconnected = true
		if spawned.size() == 4 and Network.now() - spawn_at[0] > 1.0:
			passed = (cleared and map_clean and replay_count >= 3 and network.player_id != old_player
				and network.native_generation != old_generation and network.native_lifecycle
				and network.ignored_world_packets > 0 and network.map_name == next_map and network.health > .99)
			for id in spawned.slice(0, 3):
				passed = passed and not network.entities.has(id)
			break
	passed = passed and network.malformed == 0
	print("MODERN_LIFECYCLE " + JSON.stringify({"passed": passed, "spawned": spawned, "cleared": cleared,
		"vehicle": network.vehicle_id, "state": network.state, "health": network.health, "malformed": network.malformed,
		"native_lifecycle": network.native_lifecycle, "map": network.map_name, "map_clean": map_clean,
		"reconnected": reconnected, "new_player_id": network.player_id != old_player, "new_generation": network.native_generation != old_generation,
		"ignored_before_reconnect": replay_count, "ignored_after_reconnect": network.ignored_world_packets,
		"seconds": Network.now() - started}))
	network.disconnect_game()
	network.queue_free()
	await process_frame
	quit(0 if passed else 1)
