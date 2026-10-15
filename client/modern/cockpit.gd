extends Control
## Original stripmap frame with a stretchable empty centre, fixed-shape sides.
const ART_SCALE := 1.8
const HEIGHT := 138.0 * ART_SCALE
var artwork: Texture2D:
	set(value):
		artwork = value
		queue_redraw()
var radar: Control
var instruments: Control
var tactical_map: Control

func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	resized.connect(_layout)
	call_deferred("_layout")

func _layout() -> void:
	if radar == null or instruments == null or tactical_map == null:
		return
	radar.position = Vector2(3, 4) * ART_SCALE
	radar.size = Vector2(105, 113) * ART_SCALE
	instruments.position = Vector2(130, 14) * ART_SCALE
	instruments.size = Vector2(maxf(1, size.x - 260 * ART_SCALE), 103 * ART_SCALE)
	tactical_map.position = Vector2(size.x - 109 * ART_SCALE, 22 * ART_SCALE)
	tactical_map.size = Vector2(105, 112) * ART_SCALE
	queue_redraw()

func _draw() -> void:
	if artwork == null:
		return
	var edge := 140 * ART_SCALE
	draw_texture_rect_region(artwork, Rect2(0, 0, edge, HEIGHT), Rect2(0, 342, 140, 138))
	draw_texture_rect_region(artwork, Rect2(edge, 0, maxf(1, size.x - edge * 2), HEIGHT), Rect2(140, 342, 360, 138))
	draw_texture_rect_region(artwork, Rect2(size.x - edge, 0, edge, HEIGHT), Rect2(500, 342, 140, 138))
