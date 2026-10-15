class_name WulfWire
extends RefCounted
## MSB-first retail wire codec. A failed read never advances past the packet.

var data := PackedByteArray()
var bit := 0
var valid := true

func _init(bytes := PackedByteArray()) -> void:
	data = bytes

func take(count: int) -> int:
	if not valid or count < 0 or count > 32 or bit + count > data.size() * 8:
		valid = false
		return 0
	var value := 0
	for index in count:
		value = (value << 1) | ((data[bit >> 3] >> (7 - (bit & 7))) & 1)
		bit += 1
	return value

func put(value: int, count: int) -> WulfWire:
	for index in range(count - 1, -1, -1):
		if (bit & 7) == 0:
			data.append(0)
		data[bit >> 3] |= ((value >> index) & 1) << (7 - (bit & 7))
		bit += 1
	return self

func text(value: String) -> WulfWire:
	var bytes := value.to_ascii_buffer()
	put(bytes.size() + 1, 16)
	for byte in bytes:
		put(byte, 8)
	return put(0, 8)

func read_text() -> String:
	var count := take(16)
	if not valid or count < 1 or count > 4096 or bit + count * 8 > data.size() * 8:
		valid = false
		return ""
	var bytes := PackedByteArray()
	for index in count - 1:
		bytes.append(take(8))
	if take(8) != 0:
		valid = false
	return bytes.get_string_from_ascii()

func fixed() -> float:
	var raw := take(32)
	if raw >= 0x80000000:
		raw -= 0x100000000
	return float(raw) / 65536.0

func fixed_vector() -> Vector3:
	return Vector3(fixed(), fixed(), fixed())

func scalar(count: int, maximum: float, span: float) -> float:
	var raw := take(count)
	return 0.0 if raw == 0 else maximum - float(raw - 1) * span / float((1 << count) - 2)

func vector(maximum: float, span: float) -> Vector3:
	var count := 13 + take(2)
	return Vector3(scalar(count, maximum, span), scalar(count, maximum, span), scalar(count, maximum, span))

func vitals() -> Dictionary:
	if take(1) == 0:
		return {}
	var table := take(5)
	if table > 3:
		valid = false
		return {}
	var result := {"health": scalar(10, 1.0, 1.0), "fuel": scalar(10, 1.0, 1.0)}
	result["weapon_table"] = table
	result["weapon_mask"] = take([3, 2, 0, 1][table])
	if table < 2:
		result["pulse_charge" if table == 0 else "repair_charge"] = scalar(8, 1.0, 1.0)
	return result

static func encoded_scalar(value: float, maximum := 1000.0) -> int:
	return 0 if value == 0.0 else int((maximum - clampf(value, -maximum, maximum)) * 65534.0 / (2.0 * maximum)) + 1
