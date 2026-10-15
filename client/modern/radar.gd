extends Control
## Both cockpit maps share the same world-to-screen transform for drawing/input.
signal pad_selected(id: int)
var network: WulfNetwork
var world_size := Vector2(5600, 5600)
var local_view := false
var selected := 0
var _markers: Dictionary = {}

func _ready() -> void:
	custom_minimum_size = Vector2(200, 164)
	mouse_filter = Control.MOUSE_FILTER_STOP

func _process(_delta: float) -> void:
	queue_redraw()

func _draw() -> void:
	var region := Rect2(Vector2(12, 32), size - Vector2(24, 44))
	draw_style_box(_panel(), Rect2(Vector2.ZERO, size))
	draw_string(ThemeDB.fallback_font, Vector2(14, 22), "RADAR" if local_view else "TACTICAL MAP", HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color("9eafba"))
	for index in range(1, 4):
		var fraction := index / 4.0
		draw_line(region.position + Vector2(region.size.x * fraction, 0), region.position + Vector2(region.size.x * fraction, region.size.y), Color("25333f"))
		draw_line(region.position + Vector2(0, region.size.y * fraction), region.position + Vector2(region.size.x, region.size.y * fraction), Color("25333f"))
	_markers.clear()
	if network == null:
		return
	var center := world_size * 0.5
	var extent := world_size
	if local_view and network.entities.has(network.vehicle_id):
		var p: Vector3 = network.entities[network.vehicle_id].get("pos", Vector3.ZERO)
		center = Vector2(p.x, p.y)
		extent = Vector2(850, 850)
	for id in network.entities:
		var item: Dictionary = network.entities[id]
		if not item.has("pos") or not item.has("unit"):
			continue
		var p: Vector3 = item.pos
		var uv := (Vector2(p.x, p.y) - center) / extent + Vector2(0.5, 0.5)
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
