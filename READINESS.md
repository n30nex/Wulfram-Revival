# Release readiness

This is a public community alpha, not a certification of full original-game
parity or every Windows/GPU/display combination. A native Linux client remains
out of scope for the first release; the Pi server runs on Linux.

## Deployed candidate, October 12, 2026

The public server runs `0.4.0-alpha2.1`, source
`0f6310b08c55342a0e1e3b337157c19d0af2b136`. The Windows package remains
`0.4.0-alpha2`, source `906fba4896918328de55167abd2a66bcab7d05da`, from Actions
run `38324818801`. Its ZIP SHA-256 is
`4327276ed0d24a99d593f008dbf3888aaf7bced088b24171819c1d7987f76913`.
The server's native binding is the Actions artifact from run `38326498545`;
source, native code and content are covered by its startup integrity manifest.

There are 59 passing Python tests and successful Windows/x64/ARM64 checks.
Real network testing exposed two disconnect races: a cleared connection
reference during broadcasting, and mutation of the entity dictionary during
iteration. Both have regressions. Entity membership is now copied under a
lock; newly created or changed entities keep their unsent dirty state.
Four subsequent waves of 16 real clients (64 login/spawn/disconnect journeys)
passed on the private server without a restart or missing owner vitals.
Three further Internet login/spawn/disconnect checks passed on the deployed
hotfix. The final Windows package joined and spawned on the public server;
desktop/mobile browser checks and a full external ZIP checksum passed too.

The final server's six-minute 64-bot/16-simulated-client rotation check passed
all three maps, lost 39 of 9003 scheduled ticks (0.43%), delivered at most
1199-byte updates, and ended with no stalled bots. All 64 bots spawned;
59 simultaneous goals were observed. A prior ten-minute run is described below.

The initial alpha2 deployment caught a container-inaccessible absolute website
symlink and rolled back the game. The site link was repaired, deployment and
rollback now use relative symlinks, and the corrected public routes passed.
The shared web container stayed on the same image with zero restarts.
Server-only rollback is retained at
`/opt/canadaverse/wulfram/backups/20261012-entity-0f6310b/rollback.py`;
the earlier game/page rollback is at
`/opt/canadaverse/wulfram/backups/20261012-readiness-906fba4/rollback.py`.
Run their `--check` option before use. A server rollback leaves the Windows
package and player page unchanged.

## Verified boundaries

- Windows launcher: original executable hash verified before starting; patches
  affect only its new process. Graphics presets are preserved. Calculated modes
  are advertised, with DWORD-aligned framebuffer rows. The former unaligned
  5:4 canvas crashed after spawning/capture; the aligned canvas is tested with
  the same Crossroads journey. The harness no longer rewrites package profiles.
- Network: bounded pre-authentication work and TCP deadlines, source-bound UDP
  keys, authenticated/readiness gates, rate-limited costly requests, unique
  validated callsigns, stale-session removal and serialized TCP frames. Team
  chat stays within its team. Administration accepts only LAN/loopback peers.
  The retail protocol is unencrypted: use the published join code for players,
  never a personal password. Admin secrets remain outside source and logs.
- Supervision: service readiness is explicit; only completed simulation and
  broadcast work refreshes the watchdog. A frozen private service recovered in
  51 seconds. Both rollback to alpha1 and restoration of the candidate were
  exercised using isolated state, credentials and private port 2628.
- Capacity: 600 seconds of native Pi physics/combat with 64 bots and 16 simulated
  snapshot recipients ran all three maps, delivered at most 1200-byte updates,
  lost 25 of 15021 scheduled ticks (0.17%), and ended with zero stalled bots.
  All 64 bots spawned; 61 distinct simultaneous goals were observed. This is a
  bounded load test, not a multi-day availability claim.
- Website: desktop/mobile layout, failed-download states and stale-status
  handling are checked. Published status excludes identities and credentials.
  Page headers are scoped to Wulfram, leaving other Canadaverse routes intact.

## Coverage still required for a stable release

- Physical 4K, Windows 11, non-NVIDIA GPUs and mixed-DPI/multiple monitors have
  not been tested. Layout requests are not evidence of physical hardware QA.
- The launcher and original client are unsigned. First-run experience on a
  clean Windows installation remains unverified.
- Legacy squads, persistent account ranks and the entire original equipment
  catalogue are not implemented. The player page and package guide identify
  that scope; a clickable legacy page is not proof its service exists.
- Long-running, multi-day real-player matches and adverse-network conditions
  remain release qualification work. Original reliable-stream semantics and
  legacy client stability need testing under packet loss and reordering.

## Stable-play qualification work, October 13, 2026

The stable-play candidate is `e86e67d2e5663f1bb74b0f33152cd8683be0a74e`,
server version `0.4.0-alpha2.2`. Its ARM64 binding comes from Actions run
`38349852699`, SHA-256
`11b59a63903cf4755f03799c681b9c82ee1555f01a173a0c2a377ad7008e986c`.
It adds bounded password retries, UDP bootstrap retries and
native TANK retransmission. Gameplay retains the retail transport: an
experimental TCP gameplay path failed a real-client spawn and was removed.
Five seconds of spawn protection end on any offensive input; repeated pad
requests neither heal nor re-shield a live vehicle. The client harness requires
a sustained scene and uses the normal team/map controls. Entering gameplay may
capture/recenter the pointer, while menu click checks still require alignment.

The preserved Windows package reached a sustained 1920x1080 world on the private
`bff003e` server, with aligned cockpit/chat and visible shield start/end messages.
The user confirmed closing that run normally. Its two-minute Crossroads test
with 64 bots and 16 simulated recipients dropped 17 ticks out of 3008 scheduled
(0.57%), ended with no persistent stalls and observed 57 distinct goals.
This evidence does not qualify other displays or a 24-hour run.

Bots now wait 350-650ms after acquiring/reacquiring a visible target before
firing. Three visible opponents can prompt an isolated bot to fall back toward
allies/a friendly pad and reassess after four seconds. The decision uses at most
three combat line-of-sight checks within 450 units. Known map structures and
base-defense radar still guide strategic jobs; combat obeys normal turning,
scatter, fuel and cooldowns. Tactical scenario and real-map acceptance remain
open, including team coordination and crowd behavior through complete matches.

Waiting first deployments now take priority over repeat bot respawns. Route
goals leave a cell of clearance at map edges. World-update construction starts
with small groups instead of repeatedly serializing and discarding oversized
world packets. Native collision checks reject provably separated bodies before
transforming complete meshes, retaining the original narrow collision path.
All three native suites passed on ARM64 with the original collision assets;
the exact Actions binding passed its Python binding suite too.

The final server completed a real 16-player login/deployment/movement/disconnect
wave with all 64 bot accounts present. Its 90-second sample recorded 33 dropped
ticks; this burst alone does not meet the under-1% gate. Long-run qualification
and complete tactical scenarios remain required. Load clients run on a separate
computer and stagger authentication while keeping 16 players connected, honoring
the existing per-address limit on unauthenticated connections.

On Windows 10, the preserved package passed the lab bridge's seven navigation
tabs, a fully rendered map/model preview, repair-pad click and sustained world
capture at the 1920x1080 aspect ratio. This verifies logical rendering and
in-engine clicks. Native desktop capture timed out, so physical mouse and DPI
qualification are still open. One earlier map-screen access violation in
`D3DIM700.DLL` at offset `0x6129` was recorded; subsequent monitored runs did not
reproduce it. Keep this intermittent crash open in #9. Login uses a text caret;
the lab's software-pointer pixel check is intended for deployment menus.

`qualification.json` is a private, fixed-size server snapshot updated every five
seconds. It records cumulative simulation counters across map changes, current
memory, bot population, bounded route-cache size and order counts. It contains
no callsigns, IP addresses or credentials and is not part of the public status
export. `scripts/qualify-soak.py` consumes it for one exact **staging** revision,
tests 16 simultaneous real login/spawn/disconnect journeys every five minutes,
and writes a bounded JSONL trace plus an atomic summary. Runner/probe hashes bind
the evidence to its test tools. Tick rate uses the server publication interval
rather than including the observer's wait for its next sample. A restart, stale
heartbeat or failed journey fails the run. A short smoke run can complete but
can never pass the 24-hour gate. Check both `status == "completed"` and
`passed == true`; recovery injection is a separate controlled exercise.

Example from a separate load-driver computer (use its actual SSH identity,
the Pi address, a fresh output file and the candidate SHA):

```sh
python3 scripts/qualify-soak.py \
  --state-directory /var/lib/wulfram/staging/stable-play-test \
  --expected-revision FULL_CANDIDATE_SHA \
  --ssh-target USER@PI_LAN_ADDRESS --ssh-identity /path/to/ssh-identity \
  --host PI_LAN_ADDRESS --expected-ip PI_LAN_ADDRESS --port 2628 \
  --output /path/to/private-evidence/soak.json
```

The server and observer need separate processes; the SSH account needs read
access through `sudo -n` to the private state directory. Do not run this load against the
public service. M1/M2 issues remain open until their complete acceptance evidence
is recorded; these changes do not promote the project to stable.

## Repeatable checks

Run `python -m unittest discover -s tests -v`, the native binding tests with
user-supplied collision assets, and `scripts/benchmark-bots.py` for capacity.
`scripts/check-online.py` verifies a real TCP/UDP handshake, roster, map-specific
repair-pad discovery, full-health spawn and owner vitals; its test player leaves
after a bounded run. It never logs passwords or packet bodies.

Use `scripts/client-lab.py` against a fresh extraction of the published ZIP and
an exact Actions-built helper. Check login, team changes, every navigation tab,
map pixels, cursor position, spawning, repeated F12 captures and map rotation.
Keep crash dumps and runtime screenshots outside Git.

Before deployment, preserve the old release, unit, configuration, site symlink
and Caddy file. Recheck exact identities and shared-file hashes immediately
before switching. Verify the external download checksum and a real Internet
spawn afterward. Rollback must refuse to overwrite subsequent unrelated site
changes. The game's DNS-only host and TCP/UDP router rules are independent of
the existing web tunnel.
