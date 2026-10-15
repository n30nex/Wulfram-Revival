extends SceneTree
const Wire = preload("res://wire.gd")
const Network = preload("res://network.gd")
const VehicleInput = preload("res://vehicle_input.gd")

func _init() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json"))
	var network := Network.new()
	network.state = "ready"
	network.player_id = 7
	network._handle(fixture.translation.hex_decode())
	assert(network.state == "ready")
	assert(network.action_maximum == 1000.0)
	network._handle(fixture.precise_translation.hex_decode())
	assert(network.state == "ready" and network.action_maximum == 1.0)
	network._handle(fixture.behavior.hex_decode())
	assert(network.weapons.size() == 4 and network.weapons[0][4].enabled)
	assert(network.weapons[1][1].enabled and not network.weapons[1][4].enabled)
	assert(network.vehicle_settings.size() == 2)
	assert(network.weapons[0][0].cooldown > 0.0)
	var events: Array = []
	network.transient.connect(func(event: Dictionary): events.append(event))
	network._handle(fixture.transients.hex_decode())
	assert(events.size() == 3 and events[0].entity == 42 and events[2].unit == 6)
	assert(events[1].pos.distance_to(Vector3(100, -200, 10)) < 2.0)
	network._handle(fixture.combat_events.hex_decode())
	assert(events.size() == 6 and events[3].type == 0x100 and events[3].secondary == 7 and events[5].secondary == 42)
	network._handle(fixture.snapshot.hex_decode())
	assert(network.entities.size() == 6)
	assert(network.entities[100].pos.distance_to(Vector3(100.5, -200.25, 8.75)) < 0.5)
	assert(network.entities[103].unit == 30)
	assert(absf(network.health - .75) < .002)
	assert(absf(network.fuel - .5) < .002)
	assert(network.weapon_table == 1 and network.repair_charge > .99)
	network._handle(fixture.older_remote.hex_decode())
	assert(network.entities.has(200), "Owner stream suppressed another entity")
	assert(network.entities[100].pos.x < 101, "Old update rewound a newer pose")
	assert(absf(network.health - .75) < .002, "Old update rewound vitals")
	network._handle(fixture.delete_remote.hex_decode())
	network._handle(fixture.older_remote.hex_decode())
	assert(not network.entities.has(200), "Late UDP update resurrected a deleted vehicle")
	network._handle(fixture.tank.hex_decode())
	assert(network.vehicle_id == 42)
	assert(network.entities[42].pos == Vector3(10.5, -20.25, 6))
	assert(absf(network.health - .8) < .002)
	network._handle(fixture.team.hex_decode())
	assert(network.team == 2)
	network._handle(fixture.delete.hex_decode())
	assert(not network.entities.has(42))
	assert(Network.control_packet(1234, 1.0, -.5, .25, true, true, .001, .8, true, false, true).hex_encode() == fixture.controls)
	assert(Network.control_packet(1234, 1.0, -.5, .25, true, true, .001, .8, true, false, true, 1.0).hex_encode() == fixture.precise_controls)
	var sequence := network.send_chat("/s vehicle scout", 1)
	assert(sequence > 0 and network._pending.size() == 1)
	var ack := Wire.new().put(2, 8).put(5, 16).put(9, 16).put(1, 8).put(0x20, 8).put(sequence, 16).data
	network._handle(ack)
	assert(network._pending.is_empty(), "Reliable command acknowledgement was not decoded")
	assert(network.send_chat("invalid\ntext") == -1)
	network.free()
	var truncated_checks := 0
	for name in ["snapshot", "tank", "translation", "message", "behavior", "transients", "combat_events"]:
		var bytes: PackedByteArray = fixture[name].hex_decode()
		for size_value in range(1, bytes.size()):
			var broken := Network.new()
			broken.state = "ready"
			broken._handle(bytes.slice(0, size_value))
			assert(broken.malformed == 1, "Accepted truncated " + name + " at " + str(size_value))
			assert(broken.entities.is_empty())
			broken.free()
			truncated_checks += 1
	# The same physical mouse distance over the same time must produce the
	# same accumulated rotation across different rendering/input sample rates.
	var input_model := VehicleInput.new()
	var total_turn := 0.0
	for frame in 60:
		input_model.mouse_motion(Vector2(1, 1))
		total_turn += input_model.sample(1.0 / 60.0, 0.0).turn / 60.0
	assert(is_equal_approx(total_turn, .06) and is_equal_approx(input_model.tilt, -.06))
	input_model.reset()
	input_model.mouse_motion(Vector2(60, 60))
	assert(is_equal_approx(input_model.sample(1.0, 0.0).turn, total_turn))
	input_model.clear_motion()
	assert(input_model.sample(.04, 0.0).turn == 0.0)
	for rotation in [Vector3.ZERO, Vector3(.2, -.3, .4), Vector3(-.8, .6, -1.1)]:
		var forward := VehicleInput.world_basis(rotation) * Vector3.RIGHT
		var expected := Vector3(cos(rotation.z) * cos(rotation.y), -sin(rotation.y), -sin(rotation.z) * cos(rotation.y))
		assert(forward.distance_to(expected) < .00001, "Camera/model forward differs from server combat ray")
	print("MODERN_WIRE=PASS truncated_packets=%d" % truncated_checks)
	quit()
