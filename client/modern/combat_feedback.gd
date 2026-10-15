extends Node3D
## Presentation follows accepted server events; no local damage/hit prediction.
const Audio = preload("res://original_audio.gd")
const Assets = preload("res://original_assets.gd")
const SHOT_CUES := {0x100: "GUN_FIRE", 0x101: "SCOUT_GUN_FIRE", 0x102: "PULSE_SHELL_SHOT",
	0x103: "PIERCER_SHOT", 0x104: "FLAK_SHOT", 0x105: "GUN_FIRE"}
const LEGACY_CUES := {0x0b: "UPLINK_ACTIVATE", 0x0c: "UPLINK_DEACTIVATE", 0x0d: "TANK_TOUCHDOWN",
	0x10: "TANK_JUMP", 0x11: "TANK_BANG_1", 0x12: "TANK_BANG_2", 0x25: "TANK_RAM", 0x26: "NEW_UNIT"}
var network: WulfNetwork
var audio: Audio
var assets: Assets
var camera: Camera3D
var visuals: Dictionary = {}
var first_person := false
var configured := false
var animations: Dictionary = {}
var effects: Array = []
var seen: Dictionary = {}
var projectile_cues: Dictionary = {}
var events_played := 0
var shot_events := 0
var _ambient_at := 0.0
var _owner := 0
var _health := 1.0

static func world(p: Vector3) -> Vector3:
	return Vector3(p.x, p.z, -p.y) * .1

func configure() -> bool:
	for group in [["gun", "gunblast_front", 3, 1, .08 / 3.0, .8],
		["explosion", "x", 18, 3, .08, 1.6], ["unit", "Guex", 21, 3, .05, 2.2],
		["impact", "Ht", 11, 3, .045, .4], ["flak", "flak", 15, 3, .05, 1.6]]:
		var frames: Array[Texture2D] = []
		for index in range(1, group[2] + 1):
			var name: String = group[1] + str(index).pad_zeros(group[3])
			var texture := assets.texture(name)
			if texture == null:
				return false
			frames.append(texture)
		animations[group[0]] = {"frames": frames, "interval": group[4], "size": group[5]}
	network.transient.connect(_transient)
	network.object_removed.connect(_removed)
	network.world_changed.connect(func(_name: String): reset())
	network.deployed.connect(func(): audio.play("ENTER_GAME"))
	configured = true
	return true

func reset() -> void:
	audio.clear()
	for effect in effects:
		effect.sprite.queue_free()
	effects.clear()
	seen.clear()
	projectile_cues.clear()
	_owner = 0
	_health = 1.0

func _effect(group: String, position_value: Vector3) -> void:
	if not animations.has(group) or effects.size() >= 96 or camera.position.distance_to(position_value) > 180.0:
		return
	var definition: Dictionary = animations[group]
	var sprite := Sprite3D.new()
	sprite.texture = definition.frames[0]
	sprite.pixel_size = definition.size / sprite.texture.get_width()
	sprite.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	sprite.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	sprite.position = position_value
	add_child(sprite)
	effects.append({"sprite": sprite, "definition": definition, "age": 0.0})

func _transient(event: Dictionary) -> void:
	if not configured or network.vehicle_id == 0:
		return
	var position_value: Variant = event.get("pos")
	if position_value == null:
		position_value = network.entities.get(event.get("entity", 0), {}).get("pos")
	if position_value == null:
		return
	var position: Vector3 = world(position_value)
	var kind: int = event.type
	if kind >= 0x100:
		if not event.has("secondary") or event.secondary == 0:
			return
		var key := "%d:%d" % [kind, event.secondary]
		if seen.has(key):
			return
		seen[key] = WulfNetwork.now()
		if seen.size() > 8192:
			seen.erase(seen.keys()[0])
	if SHOT_CUES.has(kind):
		shot_events += 1
		audio.play(SHOT_CUES[kind], position)
		if kind in [0x100, 0x101, 0x105]:
			_effect("gun", position)
		elif kind in [0x102, 0x103, 0x104]:
			projectile_cues[event.secondary] = {"cue": {0x102: "PULSE_FLIGHT", 0x103: "PIERCER_FLIGHT", 0x104: "FLAK_FLIGHT"}[kind], "until": WulfNetwork.now() + 20}
			if projectile_cues.size() > 2048:
				projectile_cues.erase(projectile_cues.keys()[0])
	elif kind in [0x110, 0x111]:
		audio.play("BULLET_HIT" if kind == 0x110 else "BULLET_MISS", position)
		_effect("impact", position)
	elif kind in [0x120, 0x121, 0x122]:
		audio.play({0x120: "PULSE_EXPLOSION", 0x121: "PIERCER_EXPLOSION", 0x122: "FLAK_EXPLOSION"}[kind], position)
		_effect("flak" if kind == 0x122 else "explosion", position)
		projectile_cues.erase(event.secondary)
		audio.stop_loop("entity:%d" % event.secondary)
	elif kind == 0x27:
		audio.play("FLAK_EXPLOSION" if event.get("unit") == 5 else "PULSE_EXPLOSION", position)
		_effect("explosion", position)
	elif kind in [0x0e, 0x0f]:
		var scout: bool = network.entities.get(event.get("entity", 0), {}).get("unit") == 1
		audio.play(("SCOUT_" if scout else "TANK_") + ("TAKEOFF" if kind == 0x0e else "POWERDOWN"), position)
	elif LEGACY_CUES.has(kind):
		audio.play(LEGACY_CUES[kind], position)
	events_played += 1

func _removed(id: int, explosion: bool, previous: Dictionary) -> void:
	audio.stop_loop("entity:%d" % id)
	audio.stop_loop("repair:%d" % id)
	projectile_cues.erase(id)
	if network.vehicle_id != 0 and explosion and previous.has("pos"):
		var position := world(previous.pos)
		audio.play("TANK_EXPLOSION" if previous.get("unit") in [0, 1] else "UNIT_EXPLOSION", position)
		_effect("unit", position)

func _process(delta: float) -> void:
	if not configured:
		return
	if network.state == "offline":
		if not audio.voices.is_empty() or not effects.is_empty():
			reset()
		return
	for effect in effects.duplicate():
		effect.age += delta
		var index := int(effect.age / effect.definition.interval)
		if index >= effect.definition.frames.size():
			effect.sprite.queue_free()
			effects.erase(effect)
		else:
			effect.sprite.texture = effect.definition.frames[index]
	# Move positional loops with the interpolated render pose between the
	# slower voice-selection passes, especially for fast projectiles.
	for key in audio.loops:
		var voice = audio.loops[key]
		var id: int = voice.get_meta("follow_entity", 0)
		if voice is AudioStreamPlayer3D and visuals.has(id) and is_instance_valid(visuals[id]):
			voice.position = visuals[id].global_position
	if WulfNetwork.now() >= _ambient_at:
		_ambience()
		_ambient_at = WulfNetwork.now() + .1

func _ambience() -> void:
	var wanted: Dictionary = {}
	var candidates: Array = []
	var now := WulfNetwork.now()
	for id in projectile_cues.keys():
		if projectile_cues[id].until < now:
			projectile_cues.erase(id)
	if _owner != network.vehicle_id:
		_owner = network.vehicle_id
		_health = network.health
	if network.vehicle_id != 0:
		if _health >= .25 and network.health > 0 and network.health < .25:
			audio.play("HEALTH_WARNING")
		_health = network.health
		for id in network.entities:
			var item: Dictionary = network.entities[id]
			var owner_vehicle: bool = id == network.vehicle_id
			var health: float = network.health if owner_vehicle else item.get("health", 1.0)
			if not item.has("pos") or not item.has("unit") or health <= 0:
				continue
			var position := world(item.pos)
			var distance := camera.position.distance_squared_to(position)
			var cue := ""
			var fuel: float = network.fuel if owner_vehicle else item.get("fuel", 1.0)
			if item.unit in [0, 1] and fuel > 0:
				cue = "SCOUT" if item.unit == 1 else "TANK"
				if id == network.vehicle_id and first_person:
					cue += "_INTERNAL"
				if owner_vehicle and network.docked and item.get("vel", Vector3.ZERO).length_squared() < 1.0:
					cue = ""
			elif item.unit == 25:
				cue = "ENERGY_UNIT"
			elif item.unit == 35:
				cue = "DARKLIGHT"
			elif item.unit in [5, 6] and projectile_cues.has(id):
				cue = projectile_cues[id].cue
			if not cue.is_empty():
				candidates.append({"key": "entity:%d" % id, "cue": cue,
					"entity": id,
					"pos": null if cue.ends_with("_INTERNAL") else position,
					"distance": -1.0 if id == network.vehicle_id else distance})
			var table: int = network.weapon_table if owner_vehicle else item.get("weapon_table", 0)
			var mask: int = network.weapon_mask if owner_vehicle else item.get("weapon_mask", 0)
			if table == 1 and (mask & 2) != 0:
				candidates.append({"key": "repair:%d" % id, "cue": "SCOUT_REPAIRBEAM", "pos": position, "distance": distance, "entity": id})
		if network.docked and network.entities.has(network.docking_pad):
			var pad: Dictionary = network.entities[network.docking_pad]
			var vehicle: Dictionary = network.entities.get(network.vehicle_id, {})
			var nearby: bool = vehicle.has("pos") and pad.has("pos") and vehicle.pos.distance_to(pad.pos) < 20.0 and vehicle.get("vel", Vector3.ZERO).length_squared() < 625.0
			if nearby and pad.get("team") == network.team and pad.get("health", 0) > 0 and ((pad.get("unit") == 27 and network.health < .999) or (pad.get("unit") == 26 and network.fuel < .999)):
				candidates.append({"key": "service", "cue": "REPAIRING" if pad.unit == 27 else "REFUELING", "pos": world(pad.pos), "distance": -2.0})
	candidates.sort_custom(func(a: Dictionary, b: Dictionary): return a.distance < b.distance)
	for candidate in candidates.slice(0, 16):
		wanted[candidate.key] = true
		audio.update_loop(candidate.key, candidate.cue, candidate.pos)
		if audio.loops.has(candidate.key):
			audio.loops[candidate.key].set_meta("follow_entity", candidate.get("entity", 0))
	for key in audio.loops.keys():
		if not wanted.has(key):
			audio.stop_loop(key)
