# Release readiness

This is a public community alpha, not a certification of full original-game
parity or every Windows/GPU/display combination. A native Linux client remains
out of scope for the first release; the Pi server runs on Linux.

## Original model exterior correction, October 15, 2026

The published 0.1.3 preview corrects model triangle winding when importing the original
right-handed meshes into Godot. Exterior surfaces were being culled, exposing
interior/bottom faces and hiding top panels. Reversing triangle indices restores
the exterior and outward normals while retaining every original position, UV
association, texture and attachment. Terrain and authoritative physics are unchanged.

A synthetic original +Z face failed the outward-normal regression before the
fix and passes afterward, with unchanged UV bindings. Fixed-camera GPU model
gallery captures verify exterior rendering on preserved repair/refuel pads,
Tank and Scout. This correction does not close remaining sky/effect/decorative
coverage, complete client systems, physical input or human approval gates.

[PR #39](https://github.com/n30nex/Wulfram-Revival/pull/39) is merged as `93bab3b`.
The exact client source is `ac2831bde0ac0e291f584167704e784c0abeadac`, from
[Actions 38743435633](https://github.com/n30nex/Wulfram-Revival/actions/runs/38743435633).
All required checks passed, including the new regression, wire, original-format,
layout and input checks. The exported build rendered a live Frontier match,
moved 90.03 world units and received 239 snapshots without malformed packets.

- [Optional Windows preview ZIP](https://canadaverse.org/downloads/wulfram/Wulfram-Revival-Modern-0.1.3-dev-ac2831b.zip):
  50,092,954 bytes; SHA-256 `bb503fd9cae3d8d6a562ede5de744a7460bf8f5b6bc20262d0aa51625041ecb2`.
  The complete public HTTP 200 download, checksum and manifest matched at
  13:44 UTC.
- EXE SHA-256 `d34d36f3be1a6c49c56525ae86469b92e4f417ddf0b43cf00dd80c385c4b0562`;
  PCK SHA-256 `8a698b6f40a8ad369f162aa91d6b55af23371fdade6044be7d18c6a50139e201`.
- Server alpha2.7, original asset files and the preserved-client default remain
  unchanged. Preview rollback removes only the new ZIP, checksum and
  `modern-preview-ac2831b.json`. Earlier versions remain available.

The manifest retains `production_approved: false`; complete appearance, client
systems and physical/human qualification remain unfinished.

## Original terrain and cockpit increment, October 15, 2026

The published 0.1.2 development preview corrects two terrain format errors: texture IDs
belong to a (W-1)*(H-1) square grid even though the file interleaves them with W*H
vertex heights, and binary texture masks must be applied before filtering each
stored mip. The native physics height grid is unchanged. Fixed-camera before/
after captures now show continuous roads and metal structures in their original
positions. Family-specific mask banks replace the single-bank approximation.

The cockpit uses the preserved `shockforce_cockpit` artwork, decoded directly
from `stripmaps2.zip`. Radar and tactical map now show terrain imagery; the local
radar rotates with vehicle heading. The frame retains its side proportions while
its centre expands for widescreen, and long status text stays inside it.

Validation: independent byte fixtures cover all eight composition mips, source
pixel immutability, palette/strip transparency, inferred bounds and malformed
strips. A non-square synthetic LAND checks texture and height strides separately.
All 39 core models, 175 model textures, ten stripmaps and three terrain loaders
pass. The decoded cockpit matches an independent RGBA SHA-256. GPU GUI-event
checks pass login/team/map clicks and status containment at five requested sizes
through 3840x2160. These are not physical mouse/DPI or full hardware approval.

Crossroads builds in about 3.3 seconds locally and uses 369,355,260 uncompressed
RGBA texture bytes, in pages of 256 layers. The fragment shader samples one
completed texture. [Format evidence](client/modern/ORIGINAL_FORMATS.md) records
the original executable identity, reader/compositor behavior and limits. Runtime
variant randomness, skies, decorative assets, effects and complete UI parity
remain open; original files are unchanged.

[PR #37](https://github.com/n30nex/Wulfram-Revival/pull/37) is merged as `c084c09`.
Exact source `00d4f44392efc77688ea6fb790efe7a52b131da0` was exported by
[Actions 38737891770](https://github.com/n30nex/Wulfram-Revival/actions/runs/38737891770),
with a clean build manifest and all required checks passing.

- [Optional Windows preview ZIP](https://canadaverse.org/downloads/wulfram/Wulfram-Revival-Modern-0.1.2-dev-00d4f44.zip):
  50,092,577 bytes; SHA-256 `91900680b89b4db333955600391ff4006a5694d9afc7c9de8cba516b6701ccb7`.
  A complete public HTTP 200 download matched that digest at 13:03 UTC;
  the public manifest and checksum file also matched.
- EXE SHA-256 `d34d36f3be1a6c49c56525ae86469b92e4f417ddf0b43cf00dd80c385c4b0562`;
  PCK SHA-256 `f2bc9876dd6a3d4b6d50cf8908838b45e58b84ecf830e3fc04e548c47819b605`.
- The exact exported build rendered a live Crossroads match, deployed, moved
  90.46 world units and received 252 snapshots with zero malformed packets.
  Its renderer capture includes the restored frame, road/structure textures,
  terrain radar/map and live owner vitals.
- Server code/configuration did not change. The public Pi remained alpha2.7,
  PID 2503993 with 64 bots, 16 human places and zero automatic restarts at
  12:49 UTC. The preserved-client page/download remain unchanged.
- Publication added only the new ZIP, checksum and `modern-preview-00d4f44.json`.
  Removing those three versioned files rolls back this preview publication;
  earlier downloads and the game server are independent.

The preview still reports `production_approved: false`. Full original appearance,
physical input/display and human gameplay approval remain open; this does not
replace the default preserved-client download.

## Native aiming and combat increment, October 15, 2026

The published 0.1.1 development preview adds mouse steering/tilt using the preserved
keymap coefficients, full vehicle/camera rotation, pulse/piercer/repair controls,
weapon-charge display and focus/menu input release. Original models and texture
archives are unchanged. The new per-session action table preserves fine input;
the default table stays byte-for-byte unchanged for retail and 0.1.0 clients.

Bounded local evidence:

- 114 Python tests pass, including both real handshake paths and rejection of
  unauthenticated capability requests. Late greetings cannot change the active
  per-session encoding.
- Cross-language fixtures match both action formats and reject 4,718 truncated
  packets. Camera forward vectors agree with the server's combat ray.
- A 15-second private native-physics match passed with 64 bots, the new client
  and a simultaneous legacy protocol client. Tank/Scout moved 104.7/124.2 world
  units; the server observed 48 fine-aim samples and both pulse/piercer projectiles.
  Repair input reached the server. Zero dropped catch-up ticks were observed;
  this is a bounded desktop check, not Pi capacity or complete combat approval.
  Both human connections and UDP peers were removed, and the test server stopped.
- Actual GTX 1060 rendering plus GUI-event routing passed login, team and map
  selection at five requested sizes, 800x600 through 3840x2160. Native Windows
  activation failed during the attempted physical mouse check. These results
  therefore do not qualify physical mouse capture, desktop DPI or 4K hardware.

[PR #35](https://github.com/n30nex/Wulfram-Revival/pull/35) is merged as `f8c042d`.
The exact client/server source is `d5cefcce0ef9b463f43ca7b1ce3550ba8285c2c0`.
All Windows, x64 Linux and ARM64 checks passed. The Windows client comes from
[Actions 38729091171](https://github.com/n30nex/Wulfram-Revival/actions/runs/38729091171),
with a clean-source build manifest.

- [Optional native preview ZIP](https://canadaverse.org/downloads/wulfram/Wulfram-Revival-Modern-0.1.1-dev-d5cefcc.zip):
  50,079,687 bytes; SHA-256 `bf92cfd4c82cb0da803d95b4d24e55f722aaab9b9b97d2b011f0de71944a534a`.
  Full public download returned HTTP 200 and matched at 11:50 UTC.
- EXE SHA-256 `d34d36f3be1a6c49c56525ae86469b92e4f417ddf0b43cf00dd80c385c4b0562`;
  PCK SHA-256 `4f9a6a8545a27b67537eefa391f28a34c21fb9307fe7f8bce31ac40954bbfcc5`.
- The exact exported build rendered Crossroads, deployed, moved 87.46 world
  units and received 249 snapshots with zero malformed packets. Its capture
  confirmed the live server negotiated the precise action table.
- Pi server `0.4.0-alpha2.7` runs that source with the exact ARM64 artifact from
  [Actions 38729091089](https://github.com/n30nex/Wulfram-Revival/actions/runs/38729091089).
  Native API 14, native binary and content identity are unchanged from alpha2.6.
  At 11:48 UTC it was ready with 64 bots, 16 human places and no automatic restarts.
- An external-host legacy journey passed public DNS/TCP/UDP, full-health spawn,
  movement, team switch, Scout deployment and clean disconnect in 19.4 seconds.
- Server rollback is `/opt/canadaverse/wulfram/backups/20261015-alpha27-d5cefcc/rollback.py`;
  its checked target is the sealed alpha2.6 release. Configuration, existing
  player page and default download stayed unchanged. Preview rollback removes
  only the new versioned ZIP, its checksum and `modern-preview-d5cefcc.json`.

This increment does not close original-art parity, audio, prediction, equipment
UI or human approval gates. The preview manifest has `production_approved: false`;
the preserved client remains the default download.

## Native Windows development preview, October 15, 2026

The maintainer moved replacement-client development ahead of the first stable
release and requires the original models/textures to retain their appearance.
[PR #33](https://github.com/n30nex/Wulfram-Revival/pull/33) is merged as `cb5d773`.
The exact tested build source is `5fe9b117068a2873953da15ce3138ec490d4a70b`, from
[Actions 38718928409](https://github.com/n30nex/Wulfram-Revival/actions/runs/38718928409).
The exported build manifest reports a clean source tree and Godot 4.7.2 stable.

- `WulframRevival.exe`: SHA-256 `d34d36f3be1a6c49c56525ae86469b92e4f417ddf0b43cf00dd80c385c4b0562`.
- `WulframRevival.pck`: SHA-256 `2d49e1c16c7d84158e3e4749db1e4006240a62ff8a72f6c41615209ebbc5e432`.
- The [complete optional preview ZIP](https://canadaverse.org/downloads/wulfram/Wulfram-Revival-Modern-0.1.0-dev-5fe9b11.zip)
  is 50,354,923 bytes, SHA-256
  `b2ea6e59772eed582f46961ce3f7c52b58349bedfa22ffd3ad07c7d604298ae9`.
  A complete public HTTP download returned 200 and matched that digest at
  10:42 UTC. `PACKAGE.json` seals the code, original archives and map files.

The client talks directly to the unchanged public TCP/UDP server. It renders
the server's authoritative physics state; no replacement hover controller was
introduced. It includes native UI, team/deployment selection, Tank/Scout choices,
two cameras, radar/map, owner vitals and renderer-owned screenshots. Input for
movement, primary fire and jump is encoded through the existing protocol.

Validation:

- Cross-language wire fixtures match the authoritative serializer; 1,128
  truncated packets are rejected. Tests cover independent update streams,
  late updates after deletion and quantizer compatibility.
- Headless layout checks pass at four requested logical sizes from 800x600 to
  2560x1440. They do not qualify physical DPI, 4K or hardware coverage.
- Local archive checks load 39 core original visual models, 4,244 triangles and
  175 referenced textures without missing assets. Original mesh positions, UVs,
  attachment points, palette pixels and stored mip levels are retained.
- Terrain loaders pass Crossroads, Mayhem and Frontier. They retain original
  texture references and bitmap sizes, including Mayhem's non-square UI tile.
- A native 1920x1080 click check selected a team and deployed in the prototype.
  The general window-capture tool timed out; client-rendered screenshots provide
  the visual record. The tested host is Windows 10 with a GTX 1060 6GB.
- The exact exported build passed a bounded headless public connection/spawn/
  movement check on Frontier (220 snapshots, no malformed packets), then a
  windowed GPU run on Crossroads (94 snapshots, no malformed packets, terrain
  loaded). Both ended their test connection. This is not a soak or full combat
  qualification. Existing 111 Python tests and all build jobs pass.

The preview and public manifest explicitly have `production_approved: false`.
Original terrain variant/template priority, skies, decorative assets, effects,
lighting and cockpit artwork still need reference comparison. Aiming, audio,
complete weapon/equipment interfaces, prediction/reconciliation, broad physical
display/input tests and agreed human approvals remain open. Do not label this
preview production-ready or replace the default download with it.

Publication added only the uniquely named ZIP, checksum and preview manifest.
The previous player page/download and `wulfram.service` were unchanged; the
public process remained PID 1168652 with no automatic restarts. Rollback is
removal of those three new preview files, with no service or configuration change.

## Live alpha2.6 and reliable map handovers, October 13, 2026

The public Pi server runs **`0.4.0-alpha2.6`**, source
`e6f8bf2b4e5d5d84b704a8f26221672c0b6ba305`, from
[PR #32](https://github.com/n30nex/Wulfram-Revival/pull/32). Deployment completed
at 11:06 EDT. A lost UDP world announcement previously left a player on the old
map with updates disabled. Map announcements now use the existing per-client
TCP control worker, with one coalescing event per connection. Slow TCP sends
stay outside the simulation loop. An old snapshot finishes before the next
world announcement; teardown and pending announcements block premature readiness.
Unfinished logins announce the current world themselves. Disconnects cannot
skip the next recipient of a lifecycle broadcast.

All **111 Python tests** and Windows/Linux x64/ARM64 checks pass. Five regressions
reproduce failures in the previous implementation; additional checks cover
non-blocking scheduling and coalescing to the current map. The exact ARM64
artifact from [Actions 38418117758](https://github.com/n30nex/Wulfram-Revival/actions/runs/38418117758)
passed the asset-backed binding suite on the Pi. Its SHA-256 remains
`584420a49559e1e7365bf27759d5a504aca38c338cb3b0b19100b98b540e0cd0`.
Physics API 14, native behavior and content are unchanged; the sealed release
verifies 142 files.

The native loopback harness discards every UDP world announcement and requires
the replacement map over TCP, a new snapshot, deployment, and a same-callsign
reconnect with a new player identity. All cases retain the 64-bot roster:

| Source and destination | Clients | Duration | Physics ticks / dropped | Result |
| --- | ---: | ---: | ---: | --- |
| Previous `6bf610b`, Crossroads to Mayhem | 2 | 41.773 s | 1039 / 0 | Both stalled after two dropped UDP announcements. |
| Candidate `e6f8bf2`, Crossroads to Mayhem | 16 | 50.369 s | 1254 / 0 | All 16 handovers and reconnects passed; peak 80 sessions. |
| Candidate `e6f8bf2`, Crossroads to Frontier | 2 | 32.472 s | 799 / 8 | Both handovers and reconnects passed. |

Each candidate ended with exactly 64 bot sessions, zero UDP peers and zero
registered vehicles belonging to test clients; its private server stopped.
The baseline failure remains recorded. These are bounded Windows protocol
checks using the unchanged native binding from Actions `38407295330` and the
canonical content digest recorded below. They do not qualify Pi capacity,
long-term uptime or the preserved client's map rendering/input.

After deployment, four external Internet journeys passed: team changes and
same-callsign reconnects starting on both teams. Tank/Scout deployment had full
health and fuel, owner vitals were present, and all four disconnected cleanly.
Runtime telemetry confirmed all 64 bots had deployed and the exact release
remained ready without automatic restarts. The player page and fresh public
status passed; the Windows alpha2 download identity is unchanged. No public map
rotation was forced for these post-deployment checks.

The guarded rollback to alpha2.5 is
`/opt/canadaverse/wulfram/backups/20261013-alpha26-e6f8bf2/rollback.py`.
Its sealed target passed `--check` before and after the update. No human players
were connected at the restart, and private Pi test services remain stopped.
No soak or desktop interaction was used. Complete loss/reordering/combat
lifecycle scenarios, physical client coverage, tactical acceptance and human
approval remain open.

## Live alpha2.5 and network lifecycle checks, October 13, 2026

Before alpha2.6, the public Pi server ran **`0.4.0-alpha2.5`**, source
`05a32d92b6d697717de753bf96b394abba7ad72c`, from
[PR #31](https://github.com/n30nex/Wulfram-Revival/pull/31). Deployment completed
at 10:18 EDT. Spawn/team requests now validate their exact retail mode and body
length before acknowledgement, replay tracking or ownership changes. Previously
a malformed spawn could consume its sequence, suppressing a corrected retry;
invalid modes and trailing team-request data could also change ownership.
The regression reproduces all four cases against the previous implementation.

All **104 Python tests** and Windows/Linux x64/ARM64 build checks pass. The exact
ARM64 artifact from [Actions 38411386247](https://github.com/n30nex/Wulfram-Revival/actions/runs/38411386247)
passed the asset-backed binding suite on the Pi. Its SHA-256 remains
`584420a49559e1e7365bf27759d5a504aca38c338cb3b0b19100b98b540e0cd0`; physics API
14 and game content are unchanged. The sealed release verifies 142 files.

The new loopback-only harness exercises real TCP/UDP clients against the native
server on the development host. An eight-client development run completed Tank
deployment, team changes, death/deletion notices and full-health/full-fuel Scout
redeployment for every client. A clean-source `05a32d9` run completed all 16
client journeys, reached **80 simultaneous sessions**, and returned to exactly
64 bot sessions with zero retained UDP peers. Both private servers stopped at
completion. These checks used Windows binding
`e150eaca0e7eed2c4fc65d023c4c9f1a497973c5a0b32e1bd984388092f8d8cf`
from Actions `38407295330`; this change does not modify native physics.

The eight-client run lasted 28.144 seconds, with 662 physics ticks and 29 dropped
ticks; it passes lifecycle checks but misses the timing target. The 16-client
run lasted 22.812 seconds, with 563 ticks and zero drops. Neither establishes Pi
capacity or long-term uptime. Earlier failed harness attempts are retained:
one used the wrong metrics field, and pad retries waited for incoming traffic.
The corrected probe keeps retry timers running during silence and gives initial
deployment 20 seconds before starting the requested world sample.

After deployment, separate external Internet probes starting on each team
completed login, a Tank spawn, team switching, old-vehicle deletion, a fresh
Scout spawn at 100% health/fuel, movement inputs and clean disconnect. Each
switch respected the five-second construction delay, completing deployment in
5.342/5.391 seconds. Runtime telemetry confirmed all 64 bots had deployed and
the new process remained ready without automatic restarts. The player page and
fresh public status passed; Windows client version/hash/size remain alpha2 and
the values recorded below.

The guarded rollback to alpha2.4 is
`/opt/canadaverse/wulfram/backups/20261013-alpha25-05a32d9/rollback.py`;
its sealed target passed `--check` before and after deployment. No human players
were connected at the restart. No soak or desktop interaction was used. Full
map/death/reconnect fault scenarios, physical client/input coverage, tactical
acceptance and human approval remain open. See [contributor commands](CONTRIBUTING.md)
to reproduce the bounded checks.

## Live deployment, October 13, 2026, 13:33 UTC

Before the alpha2.5 update, the public Pi server ran **`0.4.0-alpha2.4`**, source
`2caef4bf497c677cf21ce40622393db9447b5ca0`. This deploys
[PR #27](https://github.com/n30nex/Wulfram-Revival/pull/27),
[PR #28](https://github.com/n30nex/Wulfram-Revival/pull/28) and
[PR #29](https://github.com/n30nex/Wulfram-Revival/pull/29): lost initial-deployment
recovery, repair-pad clearance and stuck recovery, and correct Scout fuel
accounting. The maintainer now requests deployment of completed, validated
increments as they are ready.

The ARM64 Python 3.13 binding is the exact artifact from
[Actions run 38404395999](https://github.com/n30nex/Wulfram-Revival/actions/runs/38404395999),
SHA-256 `584420a49559e1e7365bf27759d5a504aca38c338cb3b0b19100b98b540e0cd0`.
All 101 Python tests and platform build checks pass. The asset-backed native
binding suite also passed on the Pi. The sealed package verifies 141 files;
content identity remains
`edd715d34b3d536828e5b0351fe88a3802ea3f485baaafe92964e7a46a50ac6f`.
The Python server and binding API 14 were upgraded together.

Both teams passed separate Internet protocol journeys from an external host:
login, team join, full-health spawn, movement input, owner vitals and clean
disconnect. Each requested deployment once, receiving it after 0.025/0.041
seconds, and sent 34/38 movement inputs during an eight-second world sample.
The roster contained 32 bots per team with team capacity 40. Runtime telemetry
confirmed that all 64 bots had deployed, the exact native library was loaded,
and the service stayed ready without automatic restarts. These are bounded
post-deployment checks; they do not close the remaining client or tactical gates.

The player page returned HTTP 200 from the Windows development host; its status
was fresh and reported 64 bots plus 16 human places. Downloading the entire
122,223,197-byte public Windows ZIP reproduced its published SHA-256
`4327276ed0d24a99d593f008dbf3888aaf7bced088b24171819c1d7987f76913`.
The client remains `0.4.0-alpha2`. The automated website request from the external
Linux probe host received HTTP 403 from Cloudflare, so that web check is recorded
as failed; the external game protocol checks passed.

Only the game service was restarted, after confirming no human players or
established game TCP connections. Unit/configuration hashes and game content
were preserved. The guarded server-only rollback to alpha2.3 is
`/opt/canadaverse/wulfram/backups/20261013-alpha24-2caef4b/rollback.py`;
its `--check` verified the sealed recovery release before and after deployment.
Private test services remain stopped. No soak test or desktop interaction was
used for this deployment.

## Scout fuel accounting, October 13, 2026

[PR #29](https://github.com/n30nex/Wulfram-Revival/pull/29) corrects a shared
fuel-conversion error. The native Scout holds 13,000 units, while the Tank holds
33,000. Normalizing both against the Tank's capacity made a full Scout report
39.39% fuel and remain in resupply mode after filling up. The server now reads
capacities from the native world and uses the matching value for creation,
snapshots, weapon costs, refueling and docked regeneration. No handling or
capacity constants were changed.

All 101 Python tests and Windows display/native-physics, Linux x64 and ARM64
build checks pass for implementation `9964e59d7ceb5ad3433595847205edbe630ccf35`.
The exact Windows artifact from Actions `38401373284`, SHA-256
`1dd81667b27e17edd0d11243fd669a0edefb7967859c33203cb9852f9ceff430`, passes the
asset-backed binding suite. A native before/after check changes the full Scout
from 39.39% and still resupplying to 100% and resupply complete. Native docking
checks preserve 16,500/6,500 units at half fuel and 33,000/13,000 at full fuel for
Tank/Scout, with the full-fuel TANK wire value verified independently.

The bounded simulation-clock deployment checks still pass with 64 bots and
16 simulated recipients: all bots deploy at 54 simulated seconds on Crossroads
and Mayhem, and 5.12 seconds on Frontier. These are behavior checks, not timing
or uptime claims. Python binding API 14 rejects old binaries; the source and
native artifact require a coordinated upgrade, completed in the live deployment
above. Actual client and full tactical qualification remain open.

## Background bot qualification, October 13, 2026

[PR #28](https://github.com/n30nex/Wulfram-Revival/pull/28) addresses three
deployment/recovery problems found with local native physics: a clamped guard
patrol could stop beside a repair pad, elevated spherical clearance admitted
low-hovering neighbours too close, and full jets could keep a stuck hull
bouncing against the pad. Patrol goals now retain pad clearance after terrain
snapping. Spawn checks preserve horizontal clearance, and recovery briefly
settles the jets while alternating escape directions before restoring normal
hover input. These changes use ordinary controls and collision rules.

All 95 Python tests pass. The new patrol/clearance/recovery regressions fail
against their previous implementations. Windows display/native-physics, Linux
x64 and ARM64 build jobs pass for implementation source
`36e4abc4bbbe1ad7481243e4c69ee441e692c7c0`. Its Windows x64 Python 3.13 native
artifact comes from Actions `38374695555`, SHA-256
`143ae69af04a62834651e507a68cd174b57b16fb9a96611b83cc13082bfe38b9`;
the asset-backed binding suite passes on the development host.

`check-bot-deployment.py` runs the actual game loop with a bounded simulation
clock, 64 bots and 16 bot-driven snapshot recipients. All 64 deploy on
Crossroads at 54 simulated seconds, Mayhem at 54/60.1 seconds for the two tested
starting patrol phases, and Frontier at 5.12 seconds. Every scenario ends after
75 simulated seconds. The prior repeatable Mayhem case left 25 bots waiting.
These results establish deployment behavior, not real-time capacity, network
player coverage or uptime. Content files were verified against the public
server's manifest; an older local Frontier asset copy was excluded.

A separate 75.66-second real-time Mayhem check on Windows 10, CPython 3.13.6
x64 and an Intel i5-4690K passed with all 64 bots deployed and 16 simulated
snapshot recipients. It completed 1892 physics ticks with zero dropped ticks,
had no final stalled bots or occupied deployment pads, and emitted updates no
larger than 804 bytes. Physics-step p95 was 8.124 ms; CPU use averaged 25.22% of
one core. This is a scoped desktop result, not a Pi performance measurement.

Earlier real-time checks are retained: a 45-second Crossroads run had only 59
bots deployed and missed its timing gate; a subsequent 75-second run deployed
all 64 with 3 dropped ticks out of 1878 scheduled (0.16%). The earlier Mayhem
runs exposed the guard/scout pad jams described above. Do not hide these failed
attempts or infer a platform-wide pass from one bounded check. These server
changes are now live; the player client remains unchanged.

## Network qualification findings, October 13, 2026

The private eight-bot network lab reproduced a deployment stall in the deployed
`675bdda` server: dropping the first TANK message leaves the preserved client on
the map. Native opcode `0x19` requests another TANK after entity creation fails;
it does not detect loss of the entire first message. A bounded server retry in
candidate `8bbebf2` recovered the dropped message twice on the Pi in 0.52 seconds
or less, with exactly one deployment request. All 91 Python tests pass; scripted
journeys completed the six fault profiles with eight bots. The preserved-client
retest and full lifecycle/load matrix remain open. See [network qualification](NETWORK-QUALIFICATION.md)
for the repeatable profiles, actual-client evidence and remaining checks.

The 06:04 UTC soak observer was interrupted by an orderly Windows restart at
06:31 UTC. Its last observation covered 24 minutes and 64 successful journeys.
The unchanged Pi process continued, but later shared-host pressure pushed its
cumulative dropped-tick rate above the target. The interrupted private instance
was stopped after preserving its counters; the old receipt's `running` value is
stale. Following the maintainer's October 13 direction, no further soak tests are
planned or required. Qualification now uses short background checks on the
development host and scoped service checks. Completed validated updates are
deployed to the public alpha; a planned game-service restart can briefly
disconnect players. Those checks do not establish multi-day uptime.

Two client access violations at `wulfram2.exe+0xdc7e7` were localized to entity
list cleanup, once after normal Quit and once after connection reset. They are
separate from the earlier `D3DIM700.DLL` fault. Their underlying list invariant
failure remains open; no speculative client binary patch has been applied.

## Earlier alpha2.3 deployment, October 13, 2026

The preceding public server ran `0.4.0-alpha2.3`, source
`675bdda2f763b330b28d5daed2c3c1eed87b57a6`, with the stable-play work in
[PR #25](https://github.com/n30nex/Wulfram-Revival/pull/25) and deployment fix in
[PR #26](https://github.com/n30nex/Wulfram-Revival/pull/26).
An external Internet client verified login, full-health deployment, movement
input, owner vitals and clean disconnect. The existing Windows download still
returns the same published checksum and byte count. Server-only rollback is
`/opt/canadaverse/wulfram/backups/20261013-clearance-675bdda/rollback.py`.

That build (Actions `38353241181`) fixes Mayhem pad starvation:
the per-frame bot loop previously took openings before human retries arrived.
Valid blocked human requests now give humans priority for 2.5 seconds, releasing
on expiry, disconnect, team change or successful deployment. Invalid pads cannot
reserve anything; all 64 bots remain in the match.

Its two-minute private Mayhem check completed 16 real player journeys, observed
80 simultaneous sessions and every bot deploying. It dropped 14 of 2940
scheduled ticks (0.48%); peak process RSS was 83.7 MiB. The native artifact has
the same verified SHA-256 as alpha2.2. The observer now continues sampling during
connection waves and explicitly requires all 80 places to have been exercised.
It fails if the observer pauses long enough to leave a gap in continuous coverage.

Two earlier long-run attempts failed closed: an observer SSH timeout, then the
Mayhem pad race. Neither is a completed 24-hour qualification. These fixes and
79 Python regressions advance the roadmap. The fresh 24-hour qualification that
began on October 13 at 06:04 UTC was interrupted as described above and does not
pass. Display, adverse-network, complete
tactical and human-approval gates remain open.

## Earlier deployment evidence, October 12, 2026

The previous public server ran `0.4.0-alpha2.1`, source
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
- Bounded multiplayer lifecycle and adverse-network scenarios remain release
  qualification work. Original reliable-stream semantics and legacy client
  stability need testing under packet loss and reordering. Soak tests are
  excluded by the maintainer's current direction.

## Stable-play qualification work, October 13, 2026

The stable-play candidate is `e86e67d2e5663f1bb74b0f33152cd8683be0a74e`,
server version `0.4.0-alpha2.2`. Its ARM64 binding comes from Actions run
`38349852699`, SHA-256
`11b59a63903cf4755f03799c681b9c82ee1555f01a173a0c2a377ad7008e986c`.
It adds bounded password retries, UDP bootstrap retries and
native TANK responses to creation-failure requests. Gameplay retains the retail transport: an
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
ticks; this burst alone does not meet the under-1% gate. Further scoped operating
checks and complete tactical scenarios remain required. Load clients run on a separate
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
can never establish 24-hour operation. This is historical tooling, retained for
reproducibility; soak runs are no longer part of the active roadmap. Recovery
injection remains a separate controlled exercise.

Historical invocation from a separate load-driver computer (do not launch as
part of the current roadmap; use its actual SSH identity,
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
