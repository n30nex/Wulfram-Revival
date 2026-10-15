class_name WulfNetwork
extends Node
## Native TCP/UDP client, compatible with the original and precise action tables.

signal status_changed(message: String)
signal world_changed(map_name: String)
signal deployed
signal changed
signal transient(event: Dictionary)
signal object_removed(id: int, explosion: bool, previous: Dictionary)
signal message_received(message: String, source: int, scope: int, kind: int)
signal roster_changed
signal reliable_delivered(sequence: int, success: bool)

const Wire = preload("res://wire.gd")
const NativeWorld = preload("res://native_world.gd")
const MAX_BUFFER := 262144
var tcp := StreamPeerTCP.new()
var udp := PacketPeerUDP.new()
var incoming := PackedByteArray()
var outgoing := PackedByteArray()
var entities: Dictionary = {}
var roster: Dictionary = {}
var _roster_stats: Dictionary = {}
var vehicle_id := 0
var player_id := 0
var team := 0
var health := 0.0
var fuel := 0.0
var weapon_table := 0
var weapon_mask := 0
var pulse_charge := 0.0
var repair_charge := 0.0
var pulse_minimum := 0.05
var weapons: Array = []
var vehicle_settings: Array = []
var docked := false
var docking_pad := 0
var carrying := false
var cargo_item := 0
var players_by_entity: Dictionary = {}
var map_name := ""
var state := "offline"
var ping_ms := 0
var malformed := 0
var snapshots := 0
var movement_packets := 0
var firing_packets := 0
var reliable_sequence := 0
var _callsign := ""
var _join_code := ""
var _key := ""
var _endpoint := ""
var _port := 0
var _stamp := 0
var _deadline := 0.0
var _retry_at := 0.0
var _ping_at := 0.0
var _last_packet := 0.0
var _entity_sequences: Dictionary = {}
var _deleted: Dictionary = {}
var _last_vitals_sequence := -1
var _team_requested := 0
var _team_retry_at := 0.0
var _team_deadline := 0.0
var _pending: Dictionary = {}
var action_maximum := 1000.0
var native_lifecycle := false
var native_generation := 0
var world_epoch := 0
var ignored_world_packets := 0
var _native_sequence := 0
var _last_tank_tick := -1

func connect_game(host: String, port: int, callsign: String, join_code: String) -> void:
	disconnect_game()
	var valid_name := RegEx.create_from_string("^[A-Za-z0-9 _.-]{1,24}$")
	if host.is_empty() or port < 1 or port > 65535 or valid_name.search(callsign) == null or join_code.length() > 128:
		status_changed.emit("Enter a server and a callsign of 1–24 letters, numbers or spaces.")
		return
	_callsign = callsign
	_join_code = join_code
	_port = port
	if tcp.connect_to_host(host, port) != OK:
		_fail("Could not connect to the server.")
		return
	state = "connecting"
	_deadline = now() + 20.0
	_last_packet = now()
	status_changed.emit("Connecting to " + host + "…")

func disconnect_game() -> void:
	tcp.disconnect_from_host()
	udp.close()
	state = "offline"
	incoming.clear()
	outgoing.clear()
	entities.clear()
	roster.clear()
	_roster_stats.clear()
	vehicle_id = 0
	player_id = 0
	team = 0
	map_name = ""
	_key = ""
	_join_code = ""
	_endpoint = ""
	_entity_sequences.clear()
	native_lifecycle = false
	native_generation = 0
	world_epoch = 0
	ignored_world_packets = 0
	_native_sequence = 0
	_last_tank_tick = -1
	_deleted.clear()
	_last_vitals_sequence = -1
	_pending.clear()
	players_by_entity.clear()
	weapons.clear()
	vehicle_settings.clear()
	weapon_mask = 0
	action_maximum = 1000.0
	pulse_charge = 0.0
	repair_charge = 0.0
	docked = false
	carrying = false
	reliable_sequence = 0
	snapshots = 0
	movement_packets = 0
	firing_packets = 0
	_team_requested = 0
	health = 0.0
	fuel = 0.0
	changed.emit()

func _fail(message: String) -> void:
	disconnect_game()
	status_changed.emit(message)

static func now() -> float:
	return Time.get_ticks_msec() / 1000.0

static func stamp() -> int:
	return Time.get_ticks_msec() & 0x7fffffff

func _scope_outgoing(payload: PackedByteArray) -> PackedByteArray:
	if not native_lifecycle or payload.is_empty() or payload[0] not in NativeWorld.CLIENT_WORLD:
		return payload
	_native_sequence = (_native_sequence + 1) & 0xffffffff
	var owner := vehicle_id if payload[0] in NativeWorld.CLIENT_OWNER else 0
	return NativeWorld.encode(payload, world_epoch, owner, _native_sequence, native_generation)

func _send_tcp(payload: PackedByteArray) -> void:
	payload = _scope_outgoing(payload)
	if outgoing.size() + payload.size() + 2 > MAX_BUFFER:
		_fail("The server is not accepting data. Reconnect to try again.")
		return
	outgoing.append_array(Wire.new().put(payload.size() + 2, 16).data)
	outgoing.append_array(payload)

func _send_udp(payload: PackedByteArray) -> void:
	payload = _scope_outgoing(payload)
	if payload[0] == NativeWorld.OPCODE and payload[NativeWorld.HEADER_SIZE] not in NativeWorld.ACTION_OPS:
		_send_tcp(payload)
		return
	if udp.is_socket_connected() and udp.put_packet(payload) != OK:
		_fail("The UDP connection failed. Reconnect to try again.")

func _process(_delta: float) -> void:
	if state == "offline":
		return
	tcp.poll()
	if tcp.get_status() in [StreamPeerTCP.STATUS_ERROR, StreamPeerTCP.STATUS_NONE]:
		_fail("Connection closed. You can reconnect without restarting the client.")
		return
	if state != "ready" and now() > _deadline:
		_fail("Connection timed out. Check the server address and TCP/UDP port.")
		return
	if tcp.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return
	if state == "connecting":
		state = "hello"
		tcp.set_no_delay(true)
	if not outgoing.is_empty():
		var sent := tcp.put_partial_data(outgoing)
		if sent[0] != OK:
			_fail("Could not send to the server.")
			return
		outgoing = outgoing.slice(sent[1])
	var available := tcp.get_available_bytes()
	if available > 0:
		var received := tcp.get_partial_data(mini(available, 65536))
		if received[0] != OK:
			_fail("Could not read from the server.")
			return
		incoming.append_array(received[1])
		if incoming.size() > MAX_BUFFER:
			_fail("The server sent too much buffered data.")
			return
	while incoming.size() >= 2:
		var length := (int(incoming[0]) << 8) | incoming[1]
		if length < 3 or length > 65535:
			_fail("Unsupported server packet.")
			return
		if incoming.size() < length:
			break
		var packet := incoming.slice(2, length)
		incoming = incoming.slice(length)
		_handle(packet, true)
	for index in mini(udp.get_available_packet_count(), 256):
		var packet := udp.get_packet()
		if packet.size() >= 3 and ((int(packet[0]) << 8) | packet[1]) == packet.size():
			packet = packet.slice(2)
		_handle(packet)
	if state == "key" and now() >= _retry_at:
		_send_udp(Wire.new().put(0x13, 8).put(1, 8).text(_key).data)
		_retry_at = now() + 1.0
	if state == "handshake" and now() >= _retry_at:
		_send_handshake()
		_retry_at = now() + 1.0
	if state == "ready" and now() >= _ping_at:
		_send_udp(Wire.new().put(0x0b, 8).put(stamp(), 32).put(0, 32).data)
		_ping_at = now() + 1.0
	if state == "ready" and _team_requested != 0 and now() >= _team_retry_at:
		if now() > _team_deadline:
			_team_requested = 0
			status_changed.emit("Team selection timed out. Choose a team to retry.")
		else:
			reliable_sequence = (reliable_sequence + 1) & 0xffff
			_send_udp(Wire.new().put(0x25, 8).put(reliable_sequence, 16).put(14, 16).put(1, 8).put(_team_requested, 32).put(0, 32).data)
			_team_retry_at = now() + 1.0
	if now() - _last_packet > 15.0:
		_fail("The server stopped responding. Reconnect to try again.")
	for sequence in _pending.keys():
		if not _pending.has(sequence):
			continue
		var delivery: Dictionary = _pending[sequence]
		if now() >= delivery.deadline:
			_pending.erase(sequence)
			reliable_delivered.emit(sequence, false)
		elif now() >= delivery.retry:
			_send_udp(delivery.packet)
			delivery.retry = now() + 0.5

func _send_handshake() -> void:
	# Both ROOT records share one datagram. Older servers finish on the known
	# greeting and retain precise actions/combat; newer servers also opt in.
	var packet := Wire.new().put(8, 8).text(NativeWorld.HELLO).put(8, 8).text("WulframRevival:actions-v1,combat-v1").put(3, 8).put(_stamp, 32).put(1, 32).put(4, 32)
	var names := ["Unreliable", "Reliable", "Stream 2", "Game Data"]
	for index in 4:
		packet.text(names[index]).put(1, 32).put(index, 32)
	packet.put(4, 32)
	for index in 4:
		packet.put(index, 32).put(1, 32)
	_send_udp(packet.data)

func _handle(packet: PackedByteArray, reliable_transport := false) -> void:
	if packet.is_empty():
		return
	if packet[0] in [0x17, 0x22, 0x24, 0x32] and not reliable_transport:
		ignored_world_packets += 1
		return
	var scoped_owner := -1
	if packet[0] == NativeWorld.OPCODE:
		var scope := NativeWorld.decode(packet)
		if scope.is_empty() or scope.sequence != 0:
			malformed += 1
			_fail("The server sent an invalid world update.")
			return
		packet = scope.payload
		var op: int = packet[0]
		if op not in NativeWorld.SERVER_WORLD and op not in NativeWorld.SERVER_UNSCOPED:
			malformed += 1
			_fail("The server sent an unsupported world update.")
			return
		if (not native_lifecycle and not reliable_transport) or (op in NativeWorld.SERVER_RELIABLE and not reliable_transport):
			ignored_world_packets += 1
			return
		if native_lifecycle and scope.connection != native_generation:
			ignored_world_packets += 1
			return
		if op in NativeWorld.SERVER_UNSCOPED:
			if scope.epoch != 0:
				malformed += 1
				_fail("The server sent invalid player metadata.")
				return
		elif op == 0x16:
			if scope.epoch == 0 or (world_epoch != 0 and not NativeWorld.newer(scope.epoch, world_epoch)):
				ignored_world_packets += 1
				return
			world_epoch = scope.epoch
		elif world_epoch == 0 or scope.epoch != world_epoch:
			ignored_world_packets += 1
			return
		native_lifecycle = true
		native_generation = scope.connection
		scoped_owner = scope.owner
	elif native_lifecycle and (packet[0] in NativeWorld.SERVER_WORLD or packet[0] in NativeWorld.SERVER_UNSCOPED):
		ignored_world_packets += 1
		return
	# A reconnect has no loaded world yet. Delayed raw packets from the previous
	# socket must not create vehicles before the new reliable announcement.
	if (packet[0] == 0x16 and not reliable_transport) or (map_name.is_empty() and packet[0] in NativeWorld.SERVER_WORLD and packet[0] != 0x16):
		ignored_world_packets += 1
		return
	_last_packet = now()
	var reader := Wire.new(packet)
	var opcode := reader.take(8)
	match opcode:
		0x02:
			# Server acknowledgements use the advertised reliable stream wrapper.
			if packet.size() == 9:
				var server_sequence := reader.take(16)
				var length := reader.take(16)
				var mode := reader.take(8)
				var acknowledged := reader.take(8)
				var sequence := reader.take(16)
				if reader.valid and length == 9 and mode == 1:
					_send_udp(Wire.new().put(2, 8).put(1, 8).put(2, 8).put(server_sequence, 16).data)
					if _pending.has(sequence) and _pending[sequence].opcode == acknowledged:
						_pending.erase(sequence)
						reliable_delivered.emit(sequence, true)
		0x13:
			var mode := reader.take(8)
			if mode == 1 and state == "hello":
				var port := reader.take(16)
				var count := reader.take(16)
				var host := reader.read_text()
				if not reader.valid or count != 1 or host != tcp.get_connected_host() or port != _port:
					_fail("The server advertised an unexpected UDP endpoint.")
					return
				_endpoint = host
			elif mode == 2 and state == "hello":
				_key = reader.read_text()
			elif mode == 3 and state in ["login", "handshake"]:
				state = "handshake"
				_stamp = stamp()
				_retry_at = 0.0
			if not _endpoint.is_empty() and not _key.is_empty() and state == "hello":
				if udp.connect_to_host(_endpoint, _port) != OK:
					_fail("Could not open the UDP connection.")
					return
				state = "key"
				_retry_at = 0.0
		0x4d:
			if state == "key":
				_send_tcp(Wire.new().put(0x21, 8).put(3, 8).text(_callsign).text(_join_code).data)
				_join_code = ""
				_key = ""
				state = "login"
		0x03:
			if state == "handshake":
				_send_udp(Wire.new().put(2, 8).put(0, 8).put(_stamp, 32).data)
				state = "bootstrap"
		0x22:
			reader.take(8)
			var code := reader.take(8)
			if code != 8:
				_fail("Join code rejected. Use the public player join code from the guide.")
		0x17:
			player_id = reader.take(32)
		0x25:
			var code := reader.take(8)
			if code == 17 and _team_requested != 0:
				_confirm_team(_team_requested)
			elif code == 4:
				_team_requested = 0
		0x1c:
			var id := reader.take(32)
			reader.take(32)
			var side := reader.take(16)
			reader.take(16)
			var stats := {"team": side, "kills": reader.take(16), "deaths": reader.take(16), "round_kills": reader.take(16)}
			reader.fixed()
			reader.fixed()
			reader.take(32)
			if reader.valid:
				if _roster_stats.has(id) or _roster_stats.size() < 256:
					_roster_stats[id] = stats
				if roster.has(id):
					roster[id].merge(stats, true)
				if id == player_id and side in [1, 2]:
					_confirm_team(side)
				roster_changed.emit()
		0x1b:
			var id := reader.take(32)
			if reader.valid:
				roster.erase(id)
				_roster_stats.erase(id)
				for entity in players_by_entity.keys():
					if players_by_entity[entity] == id:
						players_by_entity.erase(entity)
				roster_changed.emit()
		0x1f:
			var kind := reader.take(16)
			var source := reader.take(32)
			var scope := reader.take(16)
			reader.take(32)
			var message := reader.read_text()
			if reader.valid:
				if kind != 5:
					status_changed.emit(message)
				message_received.emit(message, source, scope, kind)
		0x24:
			_decode_behavior(reader)
		0x1e:
			var player := reader.take(32)
			var entity := reader.take(32)
			if reader.valid and (players_by_entity.has(entity) or players_by_entity.size() < 4096):
				for previous in players_by_entity.keys():
					if players_by_entity[previous] == player:
						players_by_entity.erase(previous)
				players_by_entity[entity] = player
		0x1d:
			var player := reader.take(32)
			# This notice has no entity ID/sequence. A delayed notice must not
			# destroy a later respawn; DELETE_OBJECT owns entity removal.
			if reader.valid and player == player_id and vehicle_id == 0:
				status_changed.emit("Vehicle lost. Choose a friendly repair pad to redeploy.")
		0x29:
			var player := reader.take(32)
			var has_cargo := reader.take(8) != 0
			reader.take(8)
			var item := reader.take(8)
			if reader.valid and player == player_id and (scoped_owner < 0 or scoped_owner == vehicle_id):
				carrying = has_cargo
				cargo_item = item
		0x38:
			reader.take(32)
			var pad := reader.take(32)
			var docking := reader.take(8) != 0
			if reader.valid and (scoped_owner < 0 or scoped_owner == vehicle_id):
				docked = docking
				docking_pad = pad
		0x0d:
			_decode_transients(reader)
		0x32:
			_validate_translation(reader)
		0x16:
			var new_map := reader.read_text()
			if not reader.valid or RegEx.create_from_string("^[a-zA-Z0-9_-]{1,64}$").search(new_map) == null:
				_fail("Unsupported map name.")
				return
			map_name = new_map
			entities.clear()
			players_by_entity.clear()
			for pending_sequence in _pending.keys():
				reliable_delivered.emit(pending_sequence, false)
			_pending.clear()
			_team_requested = 0
			_last_tank_tick = -1
			docked = false
			carrying = false
			vehicle_id = 0
			_entity_sequences.clear()
			_deleted.clear()
			_last_vitals_sequence = -1
			world_changed.emit(map_name)
			_send_tcp(PackedByteArray([0x39, 1]))
		0x1a:
			var id := reader.take(32)
			reader.take(32)
			var side := reader.take(16)
			reader.take(16)
			var name_text := reader.read_text()
			var tag := reader.read_text()
			var kills := reader.take(16)
			var deaths := reader.take(16)
			reader.fixed()
			reader.take(32)
			if reader.valid and (roster.has(id) or roster.size() < 256):
				roster[id] = {"name": name_text, "tag": tag, "team": side, "kills": kills, "deaths": deaths}
				roster[id].merge(_roster_stats.get(id, {}), true)
				roster_changed.emit()
		0x0e, 0x0f:
			_decode_updates(reader, opcode == 0x0f, scoped_owner)
		0x18:
			var tick := reader.take(32)
			var stats := reader.vitals()
			var unit := reader.take(32)
			var id := reader.take(32)
			var side := reader.take(8)
			var position := reader.fixed_vector()
			var rotation := reader.fixed_vector()
			if reader.valid and unit in [0, 1] and not _older(tick, _last_tank_tick) and not _deleted.has(id):
				if scoped_owner >= 0 and scoped_owner != id:
					reader.valid = false
				else:
					_accept_tank(id, unit, side, position, rotation, stats, tick)
		0x15:
			reader.take(32)
			for index in reader.take(8):
				var id := reader.take(32)
				var explosion := reader.take(8) != 0
				if reader.valid:
					object_removed.emit(id, explosion, entities.get(id, {}).duplicate())
					entities.erase(id)
					players_by_entity.erase(id)
					_entity_sequences.erase(id)
					_deleted[id] = true
					if _deleted.size() > 4096:
						_deleted.erase(_deleted.keys()[0])
					if vehicle_id == id:
						vehicle_id = 0
						docked = false
						carrying = false
						status_changed.emit("Vehicle lost. Choose a friendly repair pad to redeploy.")
		0x0b:
			var tick := reader.take(32)
			if reader.valid:
				_send_udp(Wire.new().put(0x0c, 8).put(tick, 32).put(0, 32).data)
		0x0c:
			ping_ms = maxi(0, stamp() - reader.take(32))
	if not reader.valid:
		malformed += 1
		_fail("The server sent an incomplete or unsupported packet.")
	changed.emit()

func _accept_tank(id: int, unit: int, side: int, position: Vector3, rotation: Vector3, stats: Dictionary, tick: int) -> void:
	var is_new := id != vehicle_id
	_last_tank_tick = tick
	if is_new or not _older(tick, _last_vitals_sequence):
		_apply_vitals(stats)
		_last_vitals_sequence = tick
	if is_new or not _older(tick, _entity_sequences.get(id, -1)):
		var item: Dictionary = entities.get(id, {}).duplicate()
		item.merge({"unit": unit, "team": side, "pos": position, "rot": rotation, "health": stats.get("health", health)}, true)
		entities[id] = item
		_entity_sequences[id] = tick
	vehicle_id = id
	team = side
	if is_new:
		docked = false
		carrying = false
		docking_pad = 0
		cargo_item = 0
		deployed.emit()

func _apply_vitals(stats: Dictionary) -> void:
	if not stats.is_empty():
		health = stats.health
		fuel = stats.fuel
		weapon_table = stats.weapon_table
		weapon_mask = stats.weapon_mask
		pulse_charge = stats.get("pulse_charge", 0.0)
		repair_charge = stats.get("repair_charge", 0.0)

func _decode_behavior(reader: WulfWire) -> void:
	if reader.data.size() < 1 + 95 + 4 * 13 * 45:
		reader.valid = false
		return
	reader.bit = (1 + 45) * 8
	var minimum := reader.fixed()
	reader.bit = (1 + 95) * 8
	var tables: Array = []
	for table in 4:
		var slots: Array = []
		for slot in 13:
			var enabled := reader.take(8) != 0
			for flag in 4:
				reader.take(8)
			var aim := reader.fixed()
			var cooldown := reader.take(32)
			for field in 4:
				reader.take(32)
			var cost := reader.fixed()
			var damage := reader.fixed()
			var distance := reader.fixed()
			var interval := reader.fixed()
			slots.append({"enabled": enabled, "aim": aim, "cooldown": cooldown / 1000.0, "cost": cost, "damage": damage, "range": distance, "interval": interval})
		tables.append(slots)
	# Read the remaining definitions too. A truncated physics tail must not
	# leave apparently valid weapons paired with incomplete vehicle settings.
	for index in 39 * 3:
		reader.take(32)
	var vehicles: Array = []
	for index in 2:
		for field in 4:
			reader.take(32)
		var jet_start := reader.fixed()
		var jet_minimum := reader.fixed()
		reader.fixed()
		reader.take(32)
		reader.take(32)
		vehicles.append({"jet_start": clampf(jet_start, 0.0, 1.0), "jet_minimum": clampf(jet_minimum, 0.0, 1.0)})
	for shape in 4:
		var points := reader.take(32)
		if points > 32:
			reader.valid = false
			return
		for component in points * 7 + 1:
			reader.take(32)
	for component in 27:
		reader.take(32)
	if reader.bit != reader.data.size() * 8:
		reader.valid = false
	if reader.valid:
		weapons = tables
		pulse_minimum = minimum
		vehicle_settings = vehicles

func _decode_transients(reader: WulfWire) -> void:
	var events: Array = []
	for index in reader.take(8):
		var event := {"type": reader.take(16)}
		var positioned := reader.take(1) != 0
		if positioned:
			if event.type == 0x27:
				event["unit"] = reader.take(32)
			event["pos"] = Vector3(reader.scalar(14, 8192.0, 16384.0), reader.scalar(14, 8192.0, 16384.0), reader.scalar(14, 8192.0, 16384.0))
		else:
			event["entity"] = reader.take(32)
		if reader.take(1) != 0:
			event["secondary"] = reader.take(32)
		events.append(event)
	if reader.valid:
		for event in events:
			transient.emit(event)

func _validate_translation(reader: WulfWire) -> void:
	# This slice supports the revival's advertised quantizers, not arbitrary
	# legacy servers. Reject different tables rather than drawing corrupt poses.
	var actions: Array = []
	for index in 28:
		var header := reader.take(32)
		reader.take(32)
		var total := reader.take(32)
		var maximum := reader.read_text()
		var span := reader.read_text()
		var expected := [16, 0, 1000.0, 2000.0]
		if index in [10, 11] and float(maximum) in [1.0, 1000.0]:
			expected = [16, 0, float(maximum), float(maximum) * 2.0]
			actions.append(float(maximum))
		elif index == 1:
			expected = [5, 0, 0.0, 0.0]
		elif index in [2, 3, 4]:
			expected = [8, 0, 0.0, 0.0]
		elif index in [5, 8]:
			expected = [10, 0, 1.0, 1.0]
		elif index in [13, 14]:
			expected = [8, 0, 1.0, 1.0]
		elif index >= 16:
			expected = [[2, 16, 8192.0, 16384.0], [2, 16, 1000.0, 2000.0], [2, 16, 6.3, 12.6], [2, 16, 200.0, 400.0]][(index - 16) % 4]
		if not maximum.is_valid_float() or not span.is_valid_float() or header != expected[0] or total != expected[1] or not is_equal_approx(float(maximum), expected[2]) or not is_equal_approx(float(span), expected[3]):
			reader.valid = false
			return
	if actions.size() != 2 or actions[0] != actions[1]:
		reader.valid = false
	elif reader.valid:
		action_maximum = actions[0]

func _decode_updates(reader: WulfWire, view: bool, scoped_owner := -1) -> void:
	if view:
		reader.take(32)
	var sequence := reader.take(32)
	var stats := reader.vitals()
	var updates: Dictionary = {}
	for index in reader.take(8):
		var id := reader.take(32)
		reader.take(1)
		var mask := reader.take(10)
		var bank := reader.take(16)
		if bank > 2:
			reader.valid = false
			return
		var item: Dictionary = entities.get(id, {}).duplicate()
		if mask & 1:
			item.unit = reader.take(8)
			item.team = reader.take(8)
			reader.take(8)
			if item.unit == 37:
				reader.take(32)
				reader.take(32)
			elif item.unit == 19:
				reader.take(8)
			reader.take(1)
		for field in [[2, "pos", 8192.0, 16384.0], [4, "vel", 1000.0, 2000.0], [8, "rot", 6.3, 12.6], [16, "spin", 200.0, 400.0]]:
			if mask & int(field[0]):
				item[field[1]] = reader.vector(field[2], field[3])
		if mask & 32:
			item.health = reader.scalar(10, 1.0, 1.0)
		if mask & 64:
			var table := reader.take(5)
			if table > 3:
				reader.valid = false
				return
			item.weapon_table = table
			item.weapon_mask = reader.take([3, 2, 0, 1][table])
		if mask & 128:
			item.fuel = reader.scalar(10, 1.0, 1.0)
		if mask & 256:
			item.target = reader.take(32)
		updates[id] = item
	if not reader.valid:
		return
	# Owner and remote updates arrive independently. A newer owner packet must
	# not suppress still-useful positions of other entities from the remote stream.
	for id in updates:
		if _deleted.has(id):
			continue
		var previous: int = _entity_sequences.get(id, -1)
		if _older(sequence, previous):
			if not entities.get(id, {}).has("unit") and updates[id].has("unit"):
				entities[id]["unit"] = updates[id].unit
				entities[id]["team"] = updates[id].team
			continue
		if entities.size() >= 2048 and not entities.has(id):
			reader.valid = false
			return
		entities[id] = updates[id]
		_entity_sequences[id] = sequence
	if (scoped_owner < 0 or scoped_owner == vehicle_id) and not _older(sequence, _last_vitals_sequence):
		_apply_vitals(stats)
		_last_vitals_sequence = sequence
	snapshots += 1
	if state == "bootstrap":
		state = "ready"
		status_changed.emit("Connected. Choose a team and a repair pad.")

static func _older(sequence: int, previous: int) -> bool:
	return previous >= 0 and NativeWorld.newer(previous, sequence)

func choose_team(side: int) -> void:
	if state != "ready" or side not in [1, 2]:
		return
	if _team_requested == side:
		return
	_team_requested = side
	_team_retry_at = 0.0
	_team_deadline = now() + 5.0
	status_changed.emit("Joining " + ("Crimson Federation…" if side == 1 else "Azure Alliance…"))

func _confirm_team(side: int) -> void:
	if side != team:
		vehicle_id = 0
	team = side
	if side == _team_requested:
		_team_requested = 0
		status_changed.emit(("Crimson Federation" if side == 1 else "Azure Alliance") + ". Choose a friendly repair pad.")

func spawn_at(pad: int, vehicle := 0) -> void:
	if state != "ready" or vehicle_id != 0 or vehicle not in [0, 1]:
		return
	var item: Dictionary = entities.get(pad, {})
	if item.get("unit") != 27 or item.get("team") != team or item.get("health", 0.0) <= 0:
		return
	reliable_sequence = (reliable_sequence + 1) & 0xffff
	_send_udp(Wire.new().put(0x25, 8).put(reliable_sequence, 16).put(22, 16).put(0, 8).put(pad, 32).put(vehicle, 32).put(2000, 32).put(700, 32).data)

func controls(forward: float, turn: float, strafe: float, fire: bool, jump: bool, tilt := 0.0, jet := 1.0, pulse := false, repair := false, piercer := false) -> void:
	if state != "ready" or vehicle_id == 0:
		return
	if forward != 0.0 or turn != 0.0 or strafe != 0.0:
		movement_packets += 1
	if fire:
		firing_packets += 1
	_send_udp(control_packet(stamp(), forward, turn, strafe, fire, jump, tilt, jet, pulse, repair, piercer, action_maximum))

static func control_packet(tick: int, forward: float, turn: float, strafe: float, fire: bool, jump: bool, tilt := 0.0, jet := 1.0, pulse := false, repair := false, piercer := false, maximum := 1000.0) -> PackedByteArray:
	var packet := Wire.new().put(0x0a, 8).put(11, 8).put(tick, 32).put(0, 32)
	for pair in [[1, turn], [2, forward], [3, strafe], [5, jet], [6, tilt], [7, 0.0]]:
		packet.put(pair[0], 16).put(Wire.encoded_scalar(pair[1], maximum), 16)
	for pair in [[8, fire], [4, jump], [12, pulse], [9, repair], [13, piercer]]:
		packet.put(pair[0], 16).put(int(pair[1]), 1)
	return packet.data

func reliable(opcode: int, body: PackedByteArray) -> int:
	if state != "ready" or _pending.size() >= 16 or body.size() > 4096:
		return -1
	reliable_sequence = (reliable_sequence + 1) & 0xffff
	var packet := Wire.new().put(opcode, 8).put(reliable_sequence, 16).put(body.size() + 5, 16).data
	packet.append_array(body)
	# Retries retain the original map and vehicle, never a later respawn.
	packet = _scope_outgoing(packet)
	_pending[reliable_sequence] = {"opcode": opcode, "packet": packet, "retry": now() + 0.5, "deadline": now() + 5.0}
	_send_udp(packet)
	return reliable_sequence

func send_chat(message: String, scope := 0) -> int:
	if message.length() < 1 or message.length() > 240 or scope not in [0, 1, 4]:
		return -1
	for index in message.length():
		if message.unicode_at(index) < 32 or message.unicode_at(index) > 126:
			return -1
	return reliable(0x20, Wire.new().put(scope, 16).put(0, 16).text(message).data)
