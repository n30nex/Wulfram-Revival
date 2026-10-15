extends VBoxContainer
## Bounded plain-text communications and the server's current player roster.
signal mode_changed(mode: String)
signal incoming_chat
const Network = preload("res://network.gd")
const HISTORY_LIMIT := 120
var network: Network
var mode := ""
var history: Array[String] = []
var feed := RichTextLabel.new()
var transcript := RichTextLabel.new()
var entry := LineEdit.new()
var channel := OptionButton.new()
var hint := Label.new()
var tree := Tree.new()
var heading := Label.new()
var chat_panel: PanelContainer
var players_panel: PanelContainer
var overlay := Control.new()
var pending: Dictionary = {}
var _rows: Dictionary = {}
var _order: Array = []
var _refresh_at := 0.0

func _ready() -> void:
	size_flags_vertical = Control.SIZE_EXPAND_FILL
	feed.custom_minimum_size.y = 40
	feed.size_flags_vertical = Control.SIZE_EXPAND_FILL
	feed.add_theme_font_size_override("normal_font_size", 14)
	feed.bbcode_enabled = false
	feed.scroll_following = true
	add_child(feed)
	var layer := CanvasLayer.new()
	layer.layer = 2
	add_child(layer)
	layer.add_child(overlay)
	overlay.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	overlay.mouse_filter = Control.MOUSE_FILTER_STOP
	overlay.hide()
	overlay.resized.connect(_layout)
	var chat := _panel()
	chat_panel = chat.get_parent()
	chat.add_child(_label("Communications", 24))
	transcript.bbcode_enabled = false
	transcript.selection_enabled = true
	transcript.scroll_following = true
	transcript.size_flags_vertical = Control.SIZE_EXPAND_FILL
	transcript.add_theme_font_size_override("normal_font_size", 17)
	chat.add_child(transcript)
	channel.add_item("All players", 0)
	channel.add_item("Your team", 4)
	channel.custom_minimum_size.y = 34
	channel.item_selected.connect(func(_index: int): entry.call_deferred("grab_focus"))
	chat.add_child(channel)
	entry.placeholder_text = "Message · Enter sends · Escape closes · /s help for commands"
	entry.max_length = 240
	entry.custom_minimum_size.y = 38
	entry.add_theme_font_size_override("font_size", 17)
	entry.text_submitted.connect(_submit)
	entry.gui_input.connect(func(event: InputEvent):
		if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
			entry.accept_event()
			close())
	chat.add_child(entry)
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.custom_minimum_size.y = 36
	chat.add_child(hint)
	var actions := HBoxContainer.new()
	chat.add_child(actions)
	_button(actions, "SEND", func(): _submit(entry.text))
	_button(actions, "CLOSE / ESC", close)
	var players := _panel()
	players_panel = players.get_parent()
	heading.add_theme_font_size_override("font_size", 22)
	players.add_child(heading)
	tree.columns = 5
	tree.hide_root = true
	tree.column_titles_visible = true
	tree.size_flags_vertical = Control.SIZE_EXPAND_FILL
	tree.add_theme_font_size_override("font_size", 17)
	for column in 5:
		tree.set_column_title(column, ["Callsign", "Tag", "Team", "Match kills", "Total K/D"][column])
		tree.set_column_custom_minimum_width(column, 200 if column == 0 else 95)
		tree.set_column_expand(column, column == 0)
		tree.set_column_clip_content(column, true)
	players.add_child(tree)
	var explanation := _label("Totals cover this connection. Sorted by team, then match kills.", 14)
	explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	players.add_child(explanation)
	_button(players, "CLOSE / F4", close)
	chat_panel.hide()
	players_panel.hide()
	network.message_received.connect(_receive)
	network.reliable_delivered.connect(_acknowledged)
	network.roster_changed.connect(func(): _refresh_at = 0.0)
	call_deferred("_layout")

func _panel() -> VBoxContainer:
	var panel := PanelContainer.new()
	var style := StyleBoxFlat.new()
	style.bg_color = Color("10171e")
	style.border_color = Color("708492")
	style.set_border_width_all(1)
	style.set_content_margin_all(18)
	panel.add_theme_stylebox_override("panel", style)
	overlay.add_child(panel)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	panel.add_child(box)
	return box

func _label(value: String, font_size: int) -> Label:
	var label := Label.new()
	label.text = value
	label.add_theme_font_size_override("font_size", font_size)
	return label

func _button(parent: Node, value: String, action: Callable) -> void:
	var button := Button.new()
	button.text = value
	button.custom_minimum_size.y = 38
	button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	button.pressed.connect(action)
	parent.add_child(button)

func _layout() -> void:
	if chat_panel == null or players_panel == null:
		return
	for panel in [chat_panel, players_panel]:
		panel.size = Vector2(minf(760, overlay.size.x - 32), minf(540, overlay.size.y - 32))
		panel.position = (overlay.size - panel.size) * .5

func _show_mode(value: String) -> void:
	mode = value
	overlay.visible = not mode.is_empty()
	chat_panel.visible = mode == "chat"
	players_panel.visible = mode == "players"
	mode_changed.emit(mode)
	if mode == "chat":
		entry.grab_focus()
	elif mode == "players":
		tree.grab_focus()
	else:
		var focused := get_viewport().gui_get_focus_owner()
		if focused != null:
			focused.release_focus()

func open_chat(team_only := false) -> void:
	if network.state != "ready":
		return
	channel.set_item_disabled(1, network.team not in [1, 2])
	channel.select(1 if team_only and network.team in [1, 2] else 0)
	hint.text = "Team messages reach your current team. /s commands go to the server."
	_show_mode("chat")

func toggle_players() -> void:
	if mode == "players":
		close()
	elif network.state == "ready":
		_refresh_players()
		_show_mode("players")

func close() -> void:
	if not mode.is_empty():
		_show_mode("")

func clear() -> void:
	close()
	history.clear()
	pending.clear()
	entry.clear()
	feed.clear()
	transcript.clear()
	tree.clear()
	_rows.clear()
	_order.clear()

static func plain(value: String, limit := 1024) -> String:
	return value.replace("\r", " ").replace("\n", " ").replace("\t", " ").left(limit)

func _append(value: String) -> void:
	var scroll := transcript.get_v_scroll_bar()
	transcript.scroll_following = scroll.value + scroll.page >= scroll.max_value - 1.0
	history.append(value)
	transcript.add_text(("\n" if history.size() > 1 else "") + value)
	if history.size() > HISTORY_LIMIT:
		history.pop_front()
		transcript.remove_paragraph(0)
	# Never parse player/server strings as markup or links.
	feed.text = "\n".join(history.slice(maxi(0, history.size() - 3)))

func _receive(message: String, source: int, scope: int, kind: int) -> void:
	var label := "Server"
	if kind == 5 and source != 0:
		var pilot: Dictionary = network.roster.get(source, {})
		label = ("Team" if scope == 4 else "All") + " · " + plain(pilot.get("name", "Player %d" % source), 64)
		if source != network.player_id:
			incoming_chat.emit()
		else:
			for sequence in pending.keys():
				if pending[sequence].text == message and pending[sequence].scope == scope:
					pending.erase(sequence)
					break
	_append("%s: %s" % [label, plain(message)])

func _submit(value: String) -> void:
	var message := value.strip_edges()
	if message.is_empty():
		return
	var scope := 1 if message == "/s" or message.begins_with("/s ") else channel.get_selected_id()
	if scope == 4 and network.team not in [1, 2]:
		hint.text = "Choose a team before sending a team message."
		return
	var sequence := network.send_chat(message, scope)
	if sequence < 0:
		hint.text = "Could not send. Use up to 240 basic keyboard characters and check the connection."
		return
	pending[sequence] = {"text": message, "scope": scope, "until": Network.now() + 6.0}
	entry.clear()
	close()

func _acknowledged(sequence: int, success: bool) -> void:
	if not pending.has(sequence):
		return
	if success and pending[sequence].scope == 1:
		pending.erase(sequence)
	elif not success:
		pending.erase(sequence)
		_append("Local: Delivery could not be confirmed. Check the history before retrying.")

func _process(_delta: float) -> void:
	if network == null:
		return
	if network.state == "offline":
		close()
		pending.clear()
	for sequence in pending.keys():
		if Network.now() >= pending[sequence].until:
			pending.erase(sequence)
			_append("Local: Your message was not echoed back. Delivery could not be confirmed.")
	if mode == "players" and Network.now() >= _refresh_at:
		_refresh_at = Network.now() + .5
		_refresh_players()

func _refresh_players() -> void:
	var ids: Array = network.roster.keys()
	ids.sort_custom(func(a: int, b: int):
		var first: Dictionary = network.roster[a]
		var second: Dictionary = network.roster[b]
		if first.team != second.team:
			return first.team < second.team
		if first.get("round_kills", -1) != second.get("round_kills", -1):
			return first.get("round_kills", -1) > second.get("round_kills", -1)
		return first.name.naturalnocasecmp_to(second.name) < 0)
	var root := tree.get_root()
	if root == null:
		root = tree.create_item()
	for id in _rows.keys():
		if not network.roster.has(id):
			_rows[id].free()
			_rows.erase(id)
	var previous: TreeItem
	var counts := [0, 0, 0]
	for id in ids:
		var pilot: Dictionary = network.roster[id]
		var row: TreeItem = _rows.get(id)
		if row == null:
			row = tree.create_item(root)
			_rows[id] = row
		if ids != _order:
			if previous != null:
				row.move_after(previous)
			elif row != root.get_first_child():
				row.move_before(root.get_first_child())
		previous = row
		row.set_metadata(0, id)
		var side: int = pilot.team
		if side in [0, 1, 2]:
			counts[side] += 1
		row.set_text(0, plain(pilot.name, 64) + (" (you)" if id == network.player_id else ""))
		row.set_text(1, plain(pilot.get("tag", ""), 64))
		row.set_text(2, {1: "Crimson", 2: "Azure"}.get(side, "Unassigned"))
		row.set_text(3, str(pilot.round_kills) if pilot.has("round_kills") else "—")
		row.set_text(4, "%d / %d" % [pilot.kills, pilot.deaths])
		row.set_custom_color(2, Color("ff947f") if side == 1 else Color("80bfff") if side == 2 else Color.WHITE)
	_order = ids
	heading.text = "Players · %d Crimson / %d Azure / %d unassigned" % [counts[1], counts[2], counts[0]]
