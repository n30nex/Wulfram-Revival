extends SceneTree
## Fifteen native peers plus the harness's legacy peer fill 16 human places.
const Network = preload("res://network.gd")

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	Engine.max_fps = 120
	var port := int(OS.get_environment("WULFRAM_TEST_PORT"))
	if port < 1024 or not OS.has_environment("WULFRAM_TEST_JOIN_CODE"):
		quit(1)
		return
	var peers: Array[Network] = []
	var starts: Dictionary = {}
	var retries: Dictionary = {}
	var attempts: Dictionary = {}
	var full_rosters: Dictionary = {}
	var started := Network.now()
	for index in 15:
		var peer := Network.new()
		peers.append(peer)
		root.add_child(peer)
		peer.deployed.connect(func(): starts[index] = peer.entities[peer.vehicle_id].pos)
		peer.connect_game("127.0.0.1", port, "NativeCapacity%02d" % index, OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
		# Respect the production limit on concurrent unauthenticated connections
		# from one IP; do not weaken that guard for a same-host capacity check.
		while peer.state not in ["ready", "offline"] and Network.now() - started < 25.0:
			await process_frame
		if peer.state != "ready":
			break
	var input_at := 0.0
	var passed := false
	var movements: Array = []
	while Network.now() - started < 35.0:
		await process_frame
		if peers.size() != 15 or peers.any(func(peer: Network): return peer.state == "offline"):
			break
		var all_moved := true
		movements.clear()
		for index in peers.size():
			var peer := peers[index]
			var side := 2 if index % 2 == 0 else 1
			if peer.roster.size() == 80:
				full_rosters[index] = true
			if peer.state != "ready":
				all_moved = false
				continue
			if peer.team != side:
				peer.choose_team(side)
			if peer.vehicle_id == 0 and peer.team == side and Network.now() >= retries.get(index, 0.0):
				var pads: Array = []
				for id in peer.entities:
					var item: Dictionary = peer.entities[id]
					if item.get("unit") == 27 and item.get("team") == side and item.get("health", 0.0) > 0:
						pads.append(id)
				if not pads.is_empty():
					var attempt: int = attempts.get(index, index)
					peer.spawn_at(pads[attempt % pads.size()], index % 2)
					attempts[index] = attempt + 1
				retries[index] = Network.now() + .5
			if peer.vehicle_id != 0 and Network.now() >= input_at:
				peer.controls(.55, 0, .1 if index % 2 else -.1, false, false)
			var distance := 0.0
			if starts.has(index) and peer.entities.has(peer.vehicle_id):
				distance = peer.entities[peer.vehicle_id].pos.distance_to(starts[index])
			movements.append(distance)
			all_moved = all_moved and distance > 5.0 and peer.native_lifecycle and peer.malformed == 0
		if Network.now() >= input_at:
			input_at = Network.now() + .04
		if all_moved and full_rosters.size() == 15:
			passed = true
			break
	var generations: Dictionary = {}
	var malformed := 0
	for peer in peers:
		generations[peer.native_generation] = true
		malformed += peer.malformed
		peer.disconnect_game()
		peer.queue_free()
	passed = passed and generations.size() == 15 and malformed == 0
	print("MODERN_SESSION " + JSON.stringify({"passed": passed, "journey": "capacity", "native_peers": 15,
		"full_rosters": full_rosters.size(), "unique_generations": generations.size(), "malformed": malformed,
		"movements": movements, "seconds": Network.now() - started}))
	await process_frame
	quit(0 if passed else 1)
