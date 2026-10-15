extends SceneTree
## Native-contact pickup and authoritative cargo requests, private loopback only.
const Network = preload("res://network.gd")
const Wire = preload("res://wire.gd")
var network := Network.new()
var confirmed_releases := 0
var saw_cargo := false

func _init() -> void:
	call_deferred("_run")

func _run() -> void:
	Engine.max_fps = 120
	root.add_child(network)
	var port := int(OS.get_environment("WULFRAM_TEST_PORT"))
	if port < 1024 or not OS.has_environment("WULFRAM_TEST_JOIN_CODE"):
		quit(1)
		return
	network.changed.connect(func():
		if saw_cargo and not network.carrying:
			confirmed_releases += 1
		saw_cargo = network.carrying)
	network.connect_game("127.0.0.1", port, "ModernCargoCheck", OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
	var started := Network.now()
	var retry_at := 0.0
	var input_at := 0.0
	var sent := 0
	var packets: Array[PackedByteArray] = []
	var completed: Array = []
	var forged_at := 0.0
	var locked_retained := false
	while Network.now() - started < 25.0:
		await process_frame
		if network.state == "offline":
			break
		if network.state != "ready":
			continue
		if network.team != 1:
			network.choose_team(1)
			continue
		if network.vehicle_id == 0:
			if Network.now() >= retry_at:
				for id in network.entities:
					var item: Dictionary = network.entities[id]
					if item.get("unit") == 27 and item.get("team") == 1:
						network.spawn_at(id, 0)
						break
				retry_at = Network.now() + .5
			continue
		if Network.now() >= input_at:
			input_at = Network.now() + .04
			network.controls(.1, 0, 0, false, false, 0, .8)
		if confirmed_releases > completed.size():
			completed.append({"phase": completed.size(), "state_confirmed": network.cargo_request_sequence == -1})
			# Replay the exact accepted request. It must not act on later cargo.
			for repeat in 2:
				network._send_udp(packets.back())
		if completed.size() == 3:
			network.controls(0, 0, 0, false, false, 0, .8)
			# Let the simulation's next observation see the final created crate
			# before disconnect cleanup removes the test session.
			await create_timer(.2).timeout
			break
		if not network.carrying or sent > completed.size():
			continue
		var index := completed.size()
		if index == 2:
			if network.cargo_item != 13 or network.release_cargo(true) != -1:
				break
			if forged_at == 0.0:
				# Bypass the UI check once to exercise server authority.
				network.reliable(0x2b, Wire.new().put(1, 32).data)
				forged_at = Network.now()
				continue
			if Network.now() - forged_at < .3:
				continue
			locked_retained = network.carrying and network.cargo_item == 13
		elif network.cargo_item != (2 if index == 0 else 5):
			break
		var sequence := network.release_cargo(index == 1)
		if sequence < 0:
			break
		packets.append(network._pending[sequence].packet)
		sent += 1
	var passed := completed.size() == 3 and locked_retained and network.native_lifecycle and network.malformed == 0
	for row in completed:
		passed = passed and row.state_confirmed
	print("MODERN_SESSION " + JSON.stringify({"passed": passed, "journey": "cargo", "completed": completed,
		"locked_retained": locked_retained, "native_lifecycle": network.native_lifecycle,
		"malformed": network.malformed, "snapshots": network.snapshots, "seconds": Network.now() - started}))
	network.disconnect_game()
	network.queue_free()
	await process_frame
	quit(0 if passed else 1)
