extends Control
## Both cockpit maps share the same world-to-screen transform for drawing/input.
signal pad_selected(id: int)
var network: WulfNetwork
var world_size := Vector2(5600, 5600)
var local_view := false
var classic := false
var overview: Texture2D
var selected := 0
var _markers: Dictionary = {}

func _ready() -> void:
	custom_minimum_size = Vector2.ZERO if classic else Vector2(200, 164)
	mouse_filter = Control.MOUSE_FILTER_STOP

func _process(_delta: float) -> void:
	queue_redraw()

func _draw() -> void:
	var region := Rect2(Vector2.ZERO, size) if classic else Rect2(Vector2(12, 32), size - Vector2(24, 44))
	if not classic:
		draw_style_box(_panel(), Rect2(Vector2.ZERO, size))
		draw_string(ThemeDB.fallback_font, Vector2(14, 22), "RADAR" if local_view else "TACTICAL MAP", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("9eafba"))
	_markers.clear()
	if network == null:
		return
	var center := world_size * 0.5
	var extent := world_size
	var yaw := 0.0
	if local_view and network.entities.has(network.vehicle_id):
		var p: Vector3 = network.entities[network.vehicle_id].get("pos", Vector3.ZERO)
		center = Vector2(p.x, p.y)
		extent = Vector2(850, 850)
		yaw = network.entities[network.vehicle_id].get("rot", Vector3.ZERO).z
	var right := Vector2(sin(yaw), -cos(yaw))
	var forward := Vector2(cos(yaw), sin(yaw))
	if local_view:
		var points := PackedVector2Array()
		var uvs := PackedVector2Array()
		for index in 64:
			var delta := Vector2(cos(index * TAU / 64.0), sin(index * TAU / 64.0)) * .5
			points.append(region.get_center() + delta * region.size)
			uvs.append((center + (right * delta.x - forward * delta.y) * extent) / world_size)
		draw_colored_polygon(points, Color.BLACK)
		if overview != null:
			draw_polygon(points, PackedColorArray([Color.WHITE]), uvs, overview)
	else:
		draw_rect(region, Color.BLACK)
		if overview != null:
			draw_texture_rect(overview, region, false)
	for id in network.entities:
		var item: Dictionary = network.entities[id]
		if not item.has("pos") or not item.has("unit"):
			continue
		var p: Vector3 = item.pos
		var delta := (Vector2(p.x, p.y) - center) / extent
		if local_view:
			delta = Vector2(delta.dot(right), -delta.dot(forward))
			if delta.length() > .47:
				continue
		var uv := delta + Vector2(0.5, 0.5)
		var point := region.position + uv * region.size
		if not region.has_point(point):
			continue
		var color := Color("ef785f") if item.get("team", 0) == 1 else Color("67c4ff")
		if id == network.vehicle_id:
			color = Color("f8df7a")
		if item.unit == 27:
			draw_rect(Rect2(point - Vector2(4, 4), Vector2(8, 8)), color)
			if item.get("team", 0) == network.team:
				_markers[id] = point
			if id == selected:
				draw_arc(point, 8, 0, TAU, 20, Color.WHITE, 1.5, true)
		elif item.unit in [0, 1]:
			if id == network.vehicle_id and local_view:
				draw_colored_polygon(PackedVector2Array([point + Vector2(0, -6), point + Vector2(5, 5), point, point + Vector2(-5, 5)]), color)
			else:
				draw_circle(point, 2.5 if id != network.vehicle_id else 4.0, color)

func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		var closest := 0
		var distance := 12.0
		for id in _markers:
			var candidate: float = event.position.distance_to(_markers[id])
			if candidate < distance:
				closest = id
				distance = candidate
		if closest != 0:
			selected = closest
			pad_selected.emit(closest)
			accept_event()

func _panel() -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = Color(0.035, 0.055, 0.075, 0.94)
	box.border_color = Color("4a5e6c")
	box.set_border_width_all(1)
	box.set_corner_radius_all(8)
	return box
