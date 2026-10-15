extends RefCounted
## Original keymap coefficients, sampled independently of rendering resolution.
var sensitivity := 1.0
var invert_y := false
var tilt := 0.0
var jet := 0.8
var mouse_x := 0.0

func mouse_motion(screen_delta: Vector2) -> void:
	mouse_x += screen_delta.x
	tilt = clampf(tilt + screen_delta.y * (-0.001 if not invert_y else 0.001) * sensitivity, -1.0, 1.0)

func sample(seconds: float, keyboard_turn: float) -> Dictionary:
	# The preserved mapping uses mousex * .06 (absolute) and mousey * -.001
	# (relative). Normalize its horizontal 60 Hz reference to the network sample
	# interval so changing FPS or packet rate does not change turn sensitivity.
	var turn := clampf(keyboard_turn + mouse_x * 0.06 * sensitivity / maxf(seconds * 60.0, 0.001), -1.0, 1.0)
	mouse_x = 0.0
	return {"turn": turn, "tilt": tilt, "jet": jet}

func clear_motion() -> void:
	mouse_x = 0.0

func reset() -> void:
	mouse_x = 0.0
	tilt = 0.0
	jet = 0.8

static func world_basis(rotation: Vector3) -> Basis:
	# Retail Rz(yaw) * Ry(pitch) * Rx(roll), converted from Z-up to Godot Y-up.
	return Basis(Vector3.UP, rotation.z) * Basis(Vector3.FORWARD, rotation.y) * Basis(Vector3.RIGHT, rotation.x)
