extends SceneTree
## Three real native sessions on the private test host, never public chat.
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
	var messages: Array = [[], [], []]
	for index in 3:
		var peer := Network.new()
		peers.append(peer)
		root.add_child(peer)
		peer.message_received.connect(func(message: String, source: int, scope: int, kind: int):
			if kind == 5:
				messages[index].append({"text": message, "source": source, "scope": scope}))
		peer.connect_game("127.0.0.1", port, "ModernComms%d" % index, OS.get_environment("WULFRAM_TEST_JOIN_CODE"))
	var started := Network.now()
	var ready := false
	while Network.now() - started < 20.0:
		await process_frame
		ready = true
		for index in 3:
			var desired := 1 if index < 2 else 2
			if peers[index].state == "ready" and peers[index].team != desired:
				peers[index].choose_team(desired)
			ready = ready and peers[index].state == "ready" and peers[index].team == desired and peers[index].roster.size() >= 67
		if ready:
			break
	var passed := ready
	var acknowledgements: Array = []
	for peer in peers:
		peer.reliable_delivered.connect(func(sequence: int, success: bool): acknowledgements.append([sequence, success]))
	if ready:
		peers[0].send_chat("Private team check [b]literal[/b]", 4)
		peers[1].send_chat("Private global check", 0)
		peers[0].send_chat("/s help", 1)
		var until := Network.now() + 2.0
		while Network.now() < until:
			await process_frame
		for index in 3:
			var team_messages := 0
			var global_messages := 0
			for message in messages[index]:
				if message.text == "Private team check [b]literal[/b]" and message.scope == 4 and message.source == peers[0].player_id:
					team_messages += 1
				if message.text == "Private global check" and message.scope == 0 and message.source == peers[1].player_id:
					global_messages += 1
			passed = passed and team_messages == (1 if index < 2 else 0) and global_messages == 1
			passed = passed and peers[index].roster.get(peers[0].player_id, {}).get("team") == 1
			passed = passed and peers[index].roster.get(peers[2].player_id, {}).get("team") == 2
		var leaving := peers[2].player_id
		peers[2].disconnect_game()
		until = Network.now() + 2.0
		while Network.now() < until and (peers[0].roster.has(leaving) or peers[1].roster.has(leaving)):
			await process_frame
		passed = passed and not peers[0].roster.has(leaving) and not peers[1].roster.has(leaving)
		passed = passed and not peers[0]._roster_stats.has(leaving) and not peers[1]._roster_stats.has(leaving)
	passed = passed and acknowledgements.size() == 3
	for ack in acknowledgements:
		passed = passed and ack[1]
	var malformed := 0
	for peer in peers:
		malformed += peer.malformed
		peer.disconnect_game()
		peer.queue_free()
	passed = passed and malformed == 0
	print("MODERN_SESSION " + JSON.stringify({"passed": passed, "journey": "communications", "team_recipients": 2,
		"global_recipients": 3, "enemy_team_excluded": passed, "acknowledgements": acknowledgements.size(),
		"malformed": malformed, "seconds": Network.now() - started}))
	await process_frame
	quit(0 if passed else 1)
