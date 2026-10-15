extends RefCounted
const Wire = preload("res://wire.gd")
const OPCODE := 0x50
const HEADER_SIZE := 23
const MAX_BODY := 8192 - HEADER_SIZE - 2
const HELLO := "WulframRevival:actions-v1,combat-v1,lifecycle-v1"
const SERVER_UNSCOPED := [0x02, 0x1a, 0x1b, 0x1c, 0x1f]
const SERVER_WORLD := [0x0d, 0x0e, 0x0f, 0x15, 0x16, 0x18, 0x1d, 0x1e, 0x25, 0x29, 0x38]
const SERVER_RELIABLE := [0x02, 0x15, 0x16, 0x18, 0x1a, 0x1b, 0x1c, 0x1d, 0x1e, 0x1f, 0x25, 0x29, 0x38]
const CLIENT_WORLD := [0x09, 0x0a, 0x19, 0x20, 0x25, 0x2b, 0x39, 0x3a]
const CLIENT_OWNER := [0x09, 0x0a, 0x2b, 0x3a]
const ACTION_OPS := [0x09, 0x0a]

static func encode(payload: PackedByteArray, epoch: int, owner: int, sequence: int, connection: int) -> PackedByteArray:
	var packet := Wire.new().put(OPCODE, 8).put(connection >> 32, 32).put(connection & 0xffffffff, 32).put(epoch, 32).put(owner, 32).put(sequence, 32).put(payload.size(), 16).data
	packet.append_array(payload)
	return packet

static func decode(packet: PackedByteArray) -> Dictionary:
	if packet.size() < HEADER_SIZE + 1:
		return {}
	var reader := Wire.new(packet)
	if reader.take(8) != OPCODE:
		return {}
	var connection := (reader.take(32) << 32) | reader.take(32)
	var result := {"connection": connection, "epoch": reader.take(32), "owner": reader.take(32), "sequence": reader.take(32)}
	var size := reader.take(16)
	if connection <= 0 or size < 1 or size > MAX_BODY or packet.size() != HEADER_SIZE + size or packet[HEADER_SIZE] == OPCODE:
		return {}
	result.payload = packet.slice(HEADER_SIZE)
	return result

static func newer(sequence: int, previous: int) -> bool:
	var difference := (sequence - previous) & 0xffffffff
	return previous < 0 or (difference > 0 and difference < 0x80000000)
