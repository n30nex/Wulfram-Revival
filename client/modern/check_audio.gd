extends SceneTree
const Sound = preload("res://original_audio.gd")
const Feedback = preload("res://combat_feedback.gd")
const Network = preload("res://network.gd")

func _init() -> void:
	call_deferred("_run")

func _samples(capture: AudioEffectCapture) -> Dictionary:
	var samples := capture.get_buffer(capture.get_frames_available())
	return _measure(samples)

func _measure(samples: PackedVector2Array) -> Dictionary:
	var peak := 0.0
	var energy := Vector2.ZERO
	for sample in samples:
		peak = maxf(peak, maxf(absf(sample.x), absf(sample.y)))
		energy += sample * sample
	return {"frames": samples.size(), "peak": peak, "energy": energy}

func _decode(stream: AudioStream) -> Dictionary:
	var playback := stream.instantiate_playback()
	playback.start()
	var result := _measure(playback.mix_audio(1.0, 4096))
	playback.stop()
	return result

func _run() -> void:
	create_timer(5.0).timeout.connect(func(): quit(1))
	var device := "--mix-device" in OS.get_cmdline_user_args()
	AudioServer.set_bus_mute(0, true)
	var sound := Sound.new()
	root.add_child(sound)
	sound.playback_enabled = device
	sound.set_volume(1.0, false)
	sound.mute_unfocused = false
	# Capture only this game's bus, before this process's muted master. This
	# neither plays through speakers nor records other applications/microphones.
	var bus := AudioServer.get_bus_index(sound.bus_name)
	var capture := AudioEffectCapture.new()
	capture.buffer_length = .5
	AudioServer.add_bus_effect(bus, capture)
	var pcm := PackedByteArray()
	pcm.resize(5512 * 2)
	for index in 5512:
		pcm.encode_s16(index * 2, int(sin(index * TAU * 440 / 22050) * 28000))
	var wave := AudioStreamWAV.new()
	wave.format = AudioStreamWAV.FORMAT_16_BITS
	wave.mix_rate = 22050
	wave.data = pcm
	sound.catalog["TEST"] = {"file": "fixture", "volume": 1.0, "limit": 2, "pitch": 0.0, "near": 1.0, "far": 5.0, "priority": .5, "loop": false}
	sound.streams["TEST"] = wave
	sound.loaded = true
	sound.play("TEST")
	sound.play("TEST")
	sound.play("TEST")
	assert(sound.voices.size() == 2, "Per-cue voice budget was exceeded")
	await create_timer(.18).timeout
	var mixed := _samples(capture) if device else _decode(wave)
	assert(mixed.frames > 100 and mixed.peak > .01 and (not device or mixed.peak <= .9), "Game audio did not mix or limiter failed")
	sound.clear()
	var camera := Camera3D.new()
	root.add_child(camera)
	camera.current = true
	sound.listener = camera
	assert(sound.play("TEST", Vector3(100, 0, 0)) == null, "Inaudible distant voice was allocated")
	var spatial := {"frames": 0}
	if device:
		await create_timer(.08).timeout
		capture.clear_buffer()
		sound.play("TEST", Vector3(2, 0, -2))
		await create_timer(.15).timeout
		spatial = _samples(capture)
		assert(spatial.frames > 100 and spatial.energy.y > spatial.energy.x * 1.05, "Right-side spatial sound did not pan right")
	sound.clear()
	var looping: AudioStreamWAV = wave.duplicate()
	looping.loop_mode = AudioStreamWAV.LOOP_FORWARD
	looping.loop_end = 5512
	sound.streams["LOOP"] = looping
	sound.catalog["LOOP"] = sound.catalog.TEST.duplicate()
	sound.catalog.LOOP.loop = true
	sound.catalog.LOOP.limit = 100
	for index in 52:
		sound.update_loop(str(index), "LOOP")
	assert(sound.voices.size() == Sound.MAX_VOICES and sound.loops.size() == Sound.MAX_VOICES)
	sound.clear()
	assert(sound.voices.is_empty() and sound.loops.is_empty())
	sound.mute_unfocused = true
	sound.focused = false
	sound._update_bus()
	assert(AudioServer.is_bus_mute(bus))
	sound.focused = true
	sound.set_volume(0, false)
	assert(AudioServer.is_bus_mute(bus))
	sound.set_volume(1, false)
	var network := Network.new()
	root.add_child(network)
	network.set_process(false)
	network.state = "ready"
	network.vehicle_id = 1
	var feedback := Feedback.new()
	feedback.network = network
	feedback.audio = sound
	feedback.camera = camera
	feedback.configured = true
	root.add_child(feedback)
	sound.catalog.GUN_FIRE = sound.catalog.TEST
	sound.streams.GUN_FIRE = wave
	var before := sound.started
	var event := {"type": 0x100, "pos": Vector3.ZERO, "secondary": 12}
	feedback._transient(event)
	feedback._transient(event)
	assert(sound.started == before + 1, "Duplicate combat event replayed a gunshot")
	feedback.reset()
	assert(sound.voices.is_empty() and feedback.seen.is_empty())
	feedback.queue_free()
	network.queue_free()
	var originals := 0
	if "--original-audio" in OS.get_cmdline_user_args():
		assert(sound.open_directory("res://content/original/audio"), str(sound.errors))
		originals = sound.catalog.size()
		assert(originals == 104)
		for name in sound.streams:
			assert(_decode(sound.streams[name]).frames > 0, "Original cue could not decode: " + name)
		capture.clear_buffer()
		sound.play("GUN_FIRE")
		await create_timer(.2).timeout
		var original_mix := _samples(capture) if device else _decode(sound.streams.GUN_FIRE)
		assert(original_mix.frames > 100 and original_mix.peak > .0001, "Original Ogg gunshot did not decode/mix")
	print("MODERN_AUDIO=PASS " + JSON.stringify({"frames": mixed.frames, "peak": mixed.peak, "device_mixer": device, "spatial_frames": spatial.frames, "max_voices": sound.peak_voices, "original_cues": originals, "physical_audio_qualified": false}))
	sound.clear()
	await create_timer(.08).timeout
	sound.queue_free()
	camera.queue_free()
	await process_frame
	quit()
