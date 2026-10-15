extends Node3D
## Preserved Ogg clips and sound catalogue, with bounded spatial voice playback.
const MAX_VOICES := 48
var catalog: Dictionary = {}
var streams: Dictionary = {}
var voices: Array[Node] = []
var loops: Dictionary = {}
var listener: Camera3D
var loaded := false
var errors: Array[String] = []
var volume := .7
var mute_unfocused := true
var focused := true
var force_quiet := false
var bus_name := ""
var started := 0
var dropped := 0
var peak_voices := 0
var playback_enabled := true

func _ready() -> void:
	# The headless Dummy driver does not consume playback/stop queues. Offline
	# checks still exercise voice allocation; device-mixer checks opt back in.
	playback_enabled = DisplayServer.get_name() != "headless"
	bus_name = "WulframAudio" + str(get_instance_id())
	AudioServer.add_bus()
	var index := AudioServer.bus_count - 1
	AudioServer.set_bus_name(index, bus_name)
	var limiter := AudioEffectHardLimiter.new()
	limiter.ceiling_db = -1.0
	AudioServer.add_bus_effect(index, limiter)
	var settings := ConfigFile.new()
	if settings.load("user://audio.cfg") == OK:
		volume = clampf(float(settings.get_value("sound", "volume", .7)), 0, 1)
		mute_unfocused = bool(settings.get_value("sound", "mute_unfocused", true))
	_update_bus()

func open_directory(path: String) -> bool:
	clear()
	errors.clear()
	loaded = false
	catalog.clear()
	streams.clear()
	var index := path.path_join("index.wgn")
	if not FileAccess.file_exists(index):
		errors.append("Original sound files are missing. Extract the complete package.")
		return false
	var safe_file := RegEx.create_from_string("^[A-Za-z0-9_-]+$")
	for raw in FileAccess.get_file_as_string(index).split("\n", false):
		var line := raw.strip_edges()
		if line.is_empty() or line.begins_with("#"):
			continue
		var fields := line.replace("\t", " ").split(" ", false)
		if fields.size() < 9 or safe_file.search(fields[1]) == null:
			errors.append("Invalid original sound catalogue.")
			return false
		for column in [2, 3, 4, 5, 6, 7, 8]:
			if not fields[column].is_valid_float():
				errors.append("Invalid original sound parameters.")
				return false
		var name: String = fields[0]
		var stream := AudioStreamOggVorbis.load_from_file(path.path_join(fields[1] + ".ogg"))
		if stream == null or stream.get_length() <= 0:
			errors.append("Could not decode original sound: " + name)
			return false
		stream.loop = int(fields[8]) != 0
		catalog[name] = {"file": fields[1], "volume": clampf(float(fields[2]), 0, 1),
			"limit": int(fields[3]), "pitch": clampf(float(fields[4]), 0, .5),
			"near": maxf(.01, float(fields[5]) * .1), "far": maxf(.02, float(fields[6]) * .1),
			"priority": clampf(float(fields[7]), 0, 1), "loop": stream.loop}
		streams[name] = stream
	loaded = not catalog.is_empty()
	return loaded

func set_volume(value: float, persist := true) -> void:
	volume = clampf(value, 0, 1)
	_update_bus()
	if persist:
		save_settings()

func save_settings() -> void:
	var settings := ConfigFile.new()
	settings.set_value("sound", "volume", volume)
	settings.set_value("sound", "mute_unfocused", mute_unfocused)
	settings.save("user://audio.cfg")

func _update_bus() -> void:
	var index := AudioServer.get_bus_index(bus_name)
	if index >= 0:
		AudioServer.set_bus_volume_db(index, linear_to_db(maxf(volume, .00001)))
		AudioServer.set_bus_mute(index, force_quiet or volume == 0 or (mute_unfocused and not focused))

func _process(_delta: float) -> void:
	_update_bus()
	for voice in voices.duplicate():
		if not is_instance_valid(voice):
			voices.erase(voice)
		elif not voice.playing and not voice.has_meta("loop_key"):
			_remove(voice)
	for key in loops.keys():
		if not is_instance_valid(loops[key]):
			loops.erase(key)

func _remove(voice: Node) -> void:
	voices.erase(voice)
	if is_instance_valid(voice):
		if voice.has_meta("loop_key"):
			loops.erase(voice.get_meta("loop_key"))
		voice.stop()
		voice.queue_free()

func clear() -> void:
	for voice in voices.duplicate():
		_remove(voice)
	loops.clear()

func stop_loop(key: String) -> void:
	if loops.has(key):
		_remove(loops[key])
		loops.erase(key)

func _voice(name: String, position_value: Variant, looping: bool) -> Node:
	if not loaded or not catalog.has(name) or catalog[name].file == "empty":
		return null
	var definition: Dictionary = catalog[name]
	if definition.loop != looping:
		return null
	var distance := 0.0
	if position_value != null and listener != null:
		distance = listener.global_position.distance_to(position_value)
		if distance >= definition.far:
			dropped += 1
			return null
	var score: float = definition.priority + (1.0 if position_value == null else 0.0) - .5 * distance / definition.far
	var matching: Array[Node] = []
	for voice in voices:
		if is_instance_valid(voice) and voice.get_meta("cue", "") == name:
			matching.append(voice)
	var limit: int = definition.limit if definition.limit > 0 else MAX_VOICES
	if matching.size() >= limit or voices.size() >= MAX_VOICES:
		var candidates: Array = matching if matching.size() >= limit else voices
		var victim: Node = null
		for candidate in candidates:
			if not candidate.has_meta("loop_key") and (victim == null or candidate.get_meta("score") < victim.get_meta("score")):
				victim = candidate
		if victim == null or float(victim.get_meta("score")) > score:
			dropped += 1
			return null
		_remove(victim)
	var player = AudioStreamPlayer.new() if position_value == null else AudioStreamPlayer3D.new()
	player.stream = streams[name]
	player.bus = bus_name
	player.volume_db = linear_to_db(maxf(definition.volume, .00001))
	player.pitch_scale = randf_range(1.0 - definition.pitch, 1.0 + definition.pitch)
	player.max_polyphony = 1
	player.set_meta("cue", name)
	player.set_meta("score", score)
	if position_value != null:
		player.position = position_value
		player.unit_size = definition.near
		player.max_distance = definition.far
		player.max_db = 0.0
		player.attenuation_filter_db = 0.0
	add_child(player)
	voices.append(player)
	if playback_enabled:
		player.play()
	started += 1
	peak_voices = maxi(peak_voices, voices.size())
	return player

func play(name: String, position_value: Variant = null) -> Node:
	return _voice(name, position_value, false)

func update_loop(key: String, name: String, position_value: Variant = null) -> void:
	if loops.has(key) and loops[key].get_meta("cue") != name:
		stop_loop(key)
	if not loops.has(key):
		var voice := _voice(name, position_value, true)
		if voice == null:
			return
		voice.set_meta("loop_key", key)
		loops[key] = voice
	elif position_value != null:
		loops[key].position = position_value

func _exit_tree() -> void:
	clear()
	var index := AudioServer.get_bus_index(bus_name)
	if index >= 0:
		AudioServer.remove_bus(index)
