extends SceneTree
const Wire = preload("res://wire.gd")
const Network = preload("res://network.gd")

func _init() -> void:
	var fixture: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json"))
	var network := Network.new()
	network.state = "ready"
	network.player_id = 7
	network._handle(fixture.translation.hex_decode())
	assert(network.state == "ready")
	network._handle(fixture.snapshot.hex_decode())
	assert(network.entities.size() == 6)
	assert(network.entities[100].pos.distance_to(Vector3(100.5, -200.25, 8.75)) < 0.5)
	assert(network.entities[103].unit == 30)
	assert(absf(network.health - .75) < .002)
	assert(absf(network.fuel - .5) < .002)
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
	assert(Network.control_packet(1234, 1.0, -.5, .25, true, true).hex_encode() == fixture.controls)
	network.free()
	var truncated_checks := 0
	for name in ["snapshot", "tank", "translation", "message"]:
		var bytes: PackedByteArray = fixture[name].hex_decode()
		for size_value in range(1, bytes.size()):
			var broken := Network.new()
			broken.state = "ready"
			broken._handle(bytes.slice(0, size_value))
			assert(broken.malformed == 1, "Accepted truncated " + name + " at " + str(size_value))
			assert(broken.entities.is_empty())
			broken.free()
			truncated_checks += 1
	print("MODERN_WIRE=PASS truncated_packets=%d" % truncated_checks)
	quit()
