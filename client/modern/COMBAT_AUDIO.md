# Original sound and accepted combat feedback

The importer retains the 93 original Ogg files and `base_sound/index.wgn` verbatim.
The catalogue defines 104 named cues with volume, voice count, pitch variation,
distance and looping metadata. Positional audio uses the same world coordinate
conversion as rendering. Playback is limited to 48 voices, with at most 16
selected ambient/flight/repair loops, distance culling and a -1 dB output limiter.
Volume and background muting are saved separately in `user://audio.cfg`.

Vehicle engines, accepted gun/shell/flak shots, impacts/explosions, jump/power-down,
repair/refuel service, UI clicks and low-health warnings use those original clips.
Gun flashes, impacts and explosions use preserved frame sequences. No generated
replacement artwork or audio is included. Exact emitter/spatial-mix comparison,
remaining effects and human listening approval remain open.

## Capability and wire format

After authenticated key verification, the native client sends ROOT greeting
`WulframRevival:actions-v1,combat-v1`. The server freezes precise actions and combat
events at bootstrap. Earlier native greetings retain their existing action mode;
retail and earlier native clients do not receive combat extensions. Late greetings
cannot change an active session's capability flags.

Combat events use the existing TRANSIENT_ARRAY format: u8 count, then u16 type,
the existing positional/entity discriminator and compressed position/reference,
and its existing optional u32 secondary reference. Coordinates retain the original
14-bit positional quantizer. Modern batches contain at most 96 events, keeping
them below 1200 bytes. The ordinary legacy stream is independently serialized.

| Type | Meaning | Secondary reference |
| --- | --- | --- |
| 0x100 | Tank gun accepted | Server presentation sequence |
| 0x101 | Scout gun accepted | Server presentation sequence |
| 0x102 | Pulse launch accepted | Projectile entity ID |
| 0x103 | Piercer launch accepted | Projectile entity ID |
| 0x104 | Flak launch accepted | Projectile entity ID |
| 0x105 | Gun turret accepted | Server presentation sequence |
| 0x110 | Ray hit a body | Same sequence as its gun event |
| 0x111 | Ray hit terrain | Same sequence as its gun event |
| 0x112 | Ray ended without collision | Same sequence as its gun event |
| 0x120 / 0x121 / 0x122 | Pulse / piercer / flak explosion | Projectile entity ID |

Shots are emitted after cooldown/fuel admission, and ray endpoints come from the
authoritative trace. A body collision does not assert damage: friendly-fire and
protection rules remain server-owned. The presentation counter is separate from
the scatter RNG. Receivers deduplicate typed references and limit retained state.
These are cosmetic UDP events, not a reliable damage/score channel. Complete loss,
reordering and map-transition qualification remains a separate release gate.

Legacy projectile explosions keep their original 0x27 transient and non-flashing
deletion path. Modern clients receive the typed explosion event instead, avoiding
duplicate sounds and retaining the piercer distinction.

## Validation

- Server tests reject audio for empty fuel/cooldown, check impact endpoints,
  frozen/unauthenticated capabilities, unchanged legacy traffic and batch sizes.
- Independent packet fixtures cover optional references and truncation.
- `check_audio.gd` checks offline PCM decoding, voice limits, mute controls,
  event deduplication and cleanup without an output device.
- On the reference Windows host, `--headless --audio-driver WASAPI --script
  res://check_audio.gd -- --original-audio --mix-device` captures only the game's
  bus before a muted master. It verifies all original cues decode, nonzero mixer
  output, limiter ceiling and right-side panning without speaker playback or
  capturing any microphone/other application. This is not a listening approval.
- Some preserved Sony Vorbis files contain non-key/value comment metadata. Godot
  warns about those comments; the clips decode and mix. They are not rewritten.
- `check_feedback.gd` drives the real decoder with fixed original-effect packets,
  checks duplicate suppression and expiry, and captures a renderer reference.
- The private native match checks actual Tank/Scout unit and weapon-table IDs,
  accepted event families and own projectile references alongside a legacy client.
  An earlier harness's forced Tank preference made its labelled Scout journey
  invalid; that older result must not be used as Scout qualification.

`--online-smoke --combat-smoke` adds a brief firing exercise to the bounded native
connection check. It requires accepted shot events, remains quiet, disconnects
and exits. It is not a soak or physical input/audio qualification.
