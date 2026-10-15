extends SceneTree
const Network = preload("res://network.gd")
const Scope = preload("res://native_world.gd")
const Wire = preload("res://wire.gd")

func _init() -> void:
	var fixtures: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://test-fixtures.json"))
	var data: Dictionary = fixtures.native_lifecycle
	assert(Scope.encode(fixtures.precise_controls.hex_decode(), 1, 42, 7, 1).hex_encode() == data.outgoing)
	assert(Scope.newer(1, 0xffffffff) and not Scope.newer(0xfffffffe, 1))
	assert(Scope.decode(Scope.encode(fixtures.precise_controls.hex_decode(), 1, 42, 7, 0x7fffffffffffffff)).connection == 0x7fffffffffffffff)
	assert(Network._older(0xfffffffe, 1) and not Network._older(1, 0xfffffffe))
	var network := Network.new()
	network.state = "ready"
	var births: Array = []
	network.deployed.connect(func(): births.append(network.vehicle_id))
	network._handle(data.world1.hex_decode(), true)
	assert(network.native_lifecycle and network.world_epoch == 1 and network.map_name == "crossroads")
	var request := Scope.decode(network.outgoing.slice(2))
	assert(request.epoch == 1 and request.owner == 0 and request.payload == PackedByteArray([0x39, 1]))
	network._handle(data.tank.hex_decode(), false)
	assert(network.vehicle_id == 0, "UDP must not create a native owner")
	network._handle(data.tank.hex_decode(), true)
	network._handle(data.tank.hex_decode(), true)
	assert(network.vehicle_id == 42 and births == [42], "Duplicate TANK reset deployment")
	var sequence := network.reliable(0x2b, Wire.new().put(0, 32).data)
	var frozen: PackedByteArray = network._pending[sequence].packet
	assert(Scope.decode(frozen).owner == 42)
	network.action_maximum = 1.0
	network._handle(fixtures.translation.hex_decode())
	assert(network.action_maximum == 1.0, "UDP configuration changed the negotiated action format")
	var ack := Wire.new().put(2, 8).put(5, 16).put(9, 16).put(1, 8).put(0x2b, 8).put(sequence, 16).data
	network._handle(ack)
	network._handle(Scope.encode(ack, 0, 0, 0, 99), true)
	assert(network._pending.has(sequence), "An old or unscoped acknowledgement cleared a new command")
	network._handle(Scope.encode(ack, 0, 0, 0, 1), true)
	assert(not network._pending.has(sequence))
	network._handle(data.delete.hex_decode(), true)
	assert(network.vehicle_id == 0 and not network.entities.has(42))
	network._handle(data.next_tank.hex_decode(), true)
	assert(network.vehicle_id == 43 and network.health > .99)
	network._handle(data.tank.hex_decode(), true)
	assert(network.vehicle_id == 43 and births == [42, 43])
	network._handle(data.old_owner.hex_decode())
	assert(network.health > .99 and network.entities.has(200), "Old owner vitals must not replace a respawn's vitals")
	network._handle(data.current_owner.hex_decode())
	assert(absf(network.health - .25) < .002)
	network.outgoing.clear()
	network._send_udp(frozen)
	assert(Scope.decode(network.outgoing.slice(2)).owner == 42, "Retry was rebound to a new vehicle")
	network._handle(data.world2.hex_decode())
	assert(network.world_epoch == 1 and network.vehicle_id == 43, "UDP world switch was accepted")
	var cancelled: Array = []
	network.reliable_delivered.connect(func(id: int, success: bool): cancelled.append([id, success]))
	var pending := network.send_chat("Map-bound request")
	network._handle(data.world2.hex_decode(), true)
	assert(network.world_epoch == 2 and network.vehicle_id == 0 and network.entities.is_empty() and network._pending.is_empty())
	assert(cancelled == [[pending, false]])
	for packet in [data.tank, data.old_owner, data.raw_snapshot]:
		network._handle(packet.hex_decode(), true)
	assert(network.entities.is_empty() and network.vehicle_id == 0 and network.ignored_world_packets >= 5)
	var old_connection := Scope.encode(data.raw_snapshot.hex_decode(), 2, 0, 0, 99)
	network._handle(old_connection)
	assert(network.entities.is_empty() and network.native_generation == 1, "Old connection data entered a reconnect")
	network.free()
	var malformed := 0
	for packet in [data.world1, data.tank, data.old_owner]:
		var bytes: PackedByteArray = packet.hex_decode()
		for length in range(1, bytes.size()):
			var broken := Network.new()
			broken.state = "ready"
			broken._handle(bytes.slice(0, length), true)
			assert(broken.malformed == 1 and broken.entities.is_empty())
			broken.free()
			malformed += 1
	print("MODERN_NATIVE_WORLD=PASS truncated_scopes=%d old_epochs_rejected=true respawn_owner_preserved=true" % malformed)
	quit()
