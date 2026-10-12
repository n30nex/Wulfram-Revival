# Canadaverse Wulfram II

This fork adds combat CPU players and a native Raspberry Pi 5 server
configuration to baffler's portable Physics Core. The first client target is
Windows. Original game assets remain separate from this AGPL source tree.

## Content and client

Use an original Wulfram II installation with the required maps and collision
models. The tested preserved client is cyberbalsa/wulfram2-server at
`c721d1599809730921ec8d0d5c605c8e2824bc3d`, client directory. The executable's
SHA-256 is `94990864ab1db2ddbe2652cfdbca726356b19dd3fb7597945e297a43973d99d4`.
The original executable needs DDrawCompat 0.7.1, DxWrapper 1.8.8600.25 and
the registry compatibility shim documented in that project's
[CLIENT_COMPAT.md](https://github.com/cyberbalsa/wulfram2-server/blob/c721d1599809730921ec8d0d5c605c8e2824bc3d/CLIENT_COMPAT.md).
The preserved shim is a Debug build requiring unavailable debug CRTs. Supply
the verified release DLL separately; no game binaries or third-party shim
source are included in this repository.

With the game closed, prepare that client directory:

```powershell
.\scripts\prepare-windows-client.ps1 -ClientDir F:\Wulfram\client-windows -CompatibilityDll F:\Wulfram\client-compat-build\w2reg.dll
```

Preparation checks the executable and supplied DLL hashes, validates the newer
shape archive and its gun/scout models, and copies `data/shapes2.zip` unchanged
to the active `data/shapes.zip`. The older archive lacks these models and the
client crashes while rendering its fallback geometry. The newer archive
contains every old member plus 13 additional models; no repacking is needed.
The script selects D3D Alpha and the tested DDrawCompat borderless profile,
retains unrelated preferences, and backs up each changed file alongside it
as `.pre-canadaverse-*`. Repeating preparation makes no further changes.

The pinned additional hashes are:

| File | SHA-256 |
| --- | --- |
| `shapes2.zip`, also the prepared `shapes.zip` | `8ebe6d994d8f824f9d3d8102f321a9ae9dae5b815494bc647711e6132229c394` |
| Release `w2reg.dll` | `477b8938034987db335998cd3c2bfa2f2bd32a005d5e2114256e12528a0a34aa` |

The DLL was built from unchanged
[compat_registry.cpp](https://github.com/cyberbalsa/wulfram2-server/blob/c721d1599809730921ec8d0d5c605c8e2824bc3d/src/client/compat_registry.cpp)
using Zig 0.17.0, targeting x86 Windows. The recovery workstation keeps its
compiler provenance and source/output hashes outside this checkout in
`F:\Wulfram\client-compat-build\build-provenance.json`. The build recipe is:

```powershell
zig c++ -target x86-windows-gnu -std=c++17 -O2 -DNDEBUG -shared -s path\to\compat_registry.cpp -o w2reg.dll
```

The tested DLL imports only Windows system libraries. The setup intentionally
rejects a different DLL hash; a replacement build needs review and an updated
pin before use. Do not distribute original assets or third-party binaries
through this source repository.

Import collision models and Crossroads into a new directory outside the checkout:

```text
python scripts/import-client-content.py /path/to/client /path/to/content
```

The importer applies shapes2.zip over shapes.zip, validates required models and
map files, and refuses to overwrite an existing content directory. Core tests
recognize both the original 15-node reference tank tree and the verified retail
16-node tree; their physics behavior assertions are unchanged.

## Pi server

Build with the existing scripts/build-physics.sh. Despite its historic `x64`
directory name, the script builds natively on ARM64. The only runtime Python
dependencies are the standard library and the compiled physics module.

`config/pi5.toml` is the deployment configuration, and `config/wulfram.service`
is the bounded systemd service. Adjust the bind and advertised public addresses
to your host. Store distinct player/admin credentials in the root-readable
`/etc/wulfram/server.env`; do not commit credentials. Keep assets under
`/opt/canadaverse/wulfram/content`, with a source checkout at `current`.

`bots_per_team = 32` starts 64 CPU players; `player_limit = 80` leaves 16 human
slots. The client receives a 40-player limit per team from the same server
capacity; its old independent 20-player default incorrectly blocked team
selection when 32 bots were present. Human and bot respawns share a pad
reservation lock. An occupied human-selected pad falls back to the nearest
living, unoccupied friendly pad, or returns a busy message if none is free.
The Pi profile uses this configuration. CPU vehicles
pursue enemy vehicles and bases, use the normal weapons/fuel/cooldown rules,
and respawn from unoccupied living friendly pads. Teams share cached terrain
distance fields toward enemy bases. Routes reject steep cells and diagonal
corner cuts, with short look-ahead only across a clear terrain path. Nearby
vehicles influence spacing; a bot that stops making progress backs off,
strafes and tries a jump. Routine random jumping is removed to preserve fuel.
Each 32-bot team assigns 12 assault vehicles, eight flankers, eight guards and
four interceptors. Assault groups split between enemy structures and approach
lanes; flankers pass through opposite staging areas before attacking. Guards
patrol away from spawn pads and respond to enemy incursions, then resume their
patrol. Interceptors reinforce threatened bases or join the attack. Bots keep
their jobs across respawns and distribute spawns across available pads.
They engage visible nearby opponents, try another target if the first is
occluded, and space themselves around vehicles ahead. They do not yet build
bases or coordinate cargo construction.

### Released gameplay additions

The current branch adds real kill/death counters, team points and timed rounds.
Destroying an enemy vehicle earns one point, a base structure earns three,
and a Scout earns one point for each 100 health repaired. Eliminating the
opposing team's survival resources still wins; a timed round otherwise uses
team points, with ties recorded as draws. The Pi profile uses 20-minute rounds
and ordered Crossroads/Mayhem/Frontier rotation. `/s score` and `/s status`
are available to players. The native Your Stats page receives real round and
connection statistics. Session kill/death totals survive map changes; round
scores reset, and connection totals reset on reconnect.

Each 32-bot team uses 20 Tanks, eight Support Scouts and four Siege loadouts.
Scouts use a machine gun and a fuel/charge-limited friendly repair beam.
Siege uses the existing Tank chassis with 180 health and cannot carry cargo.
The Tank's Piercer is a faster direct-hit projectile without pulse splash.
Choose `/s vehicle tank|scout|siege|auto` for the next deployment. `auto`
restores the original map-screen Tank/Scout choice. Low-resource bots return
to friendly service pads, and Scouts seek nearby damaged allies.

Weapon fuel debit and pad refueling now use native authority. These changes
require Python binding API **13**; rebuild the native module with the source
before deploying this branch. Reusing the live API-12 module is rejected.

Generate the original Frontier map into a new, external map directory:

```text
python scripts/build-frontier-map.py /path/to/content/shared/data/maps/frontier
```

Its three approaches, eight pads per team and midfield construction cargo use
the preserved client's existing textures and models. Copy the generated
`shared/data/maps/frontier` directory to both server and client before adding
`frontier` to rotation. The generator refuses to overwrite an existing map.
The packaged client has been checked with Frontier's terrain preview, 3D world
and Scout deployment. Solid materials use the retail tagmap2 plain-name format.

With the client closed, `scripts/prepare-controls.ps1 -ClientDir <path>` applies
WASD movement, Q/E turning and Space jump while preserving the mouse and arrow
controls. `-Preset classic` restores the saved original vehicle keymaps.

The server writes `public.json` in its private state directory every five
seconds. `scripts/publish-status.py` exports only the match counters needed by
the player page, omitting player names, addresses and credentials. The supplied
systemd timer refreshes that public file, and the page treats timestamps older
than 30 seconds as unavailable. The public guide and verified download are at
https://canadaverse.org/wulfram/ . `release.json` identifies the exact ZIP and SHA-256.
The native movement check also records distance travelled, active engagements,
and live bots that want to move but travel less than 10 units in 10 seconds.
Patrolling, intentional holding and fighting are distinguished from stalls.
It also saves role counts, concurrent goals and vehicle positions so route
diversity can be checked against actual movement, not just assigned labels.

Large-match updates are split into datagrams of at most 1200 bytes. Every
datagram includes the recipient's health, fuel and weapon state. The retail
decoder zero-initializes an omitted vital-stat block and then applies it
unconditionally, so omitting these fields falsely reports a dead vehicle and
can leave the screen red. World-entity records are cached per team within a
broadcast, while vital statistics and owner exclusion remain recipient-specific.
Enemy cargo contents remain concealed. The advertised per-team player limit
comes from the configured match capacity, leaving eight human spaces per
side in the 64-bot profile.
Hover-support geometry is transformed once per physics tick and uses conservative
bounds before the original triangle tests. No physics tick rate is reduced.

The reproducible load check runs native physics and combat without opening a
listening port. Optional simulated clients exercise snapshot serialization with
bot-driven vehicles and an in-memory transport; this does not replace a real
client or public-network test:

```text
python scripts/benchmark-bots.py --content-root /path/to/content --bots 64 --clients 16 --seconds 120 --output /tmp/wulfram-load.json
```

The Windows display launcher under `client/windows/` is an experimental retail
client patch. It verifies the executable hash and patches only a newly created,
suspended process, leaving the original executable unchanged. Native widescreen
gameplay and menu clicking have been exercised. Menus now retain a centered
640x480 canvas while gameplay uses the full widescreen viewport. Custom map
and polygon-button hit tests use the same menu origin; the map's texture
readback uses the full framebuffer. UI proportions stay consistent from HD
through 4K layout requests. Native 1920x1080 render targets and full-screen
presentation were confirmed in the graphics-wrapper trace; 1440p and 4K
layout requests were checked, but physical 4K hardware was not available.
Mouse coordinates are clamped to the full screen, and both cursor drawing
paths compensate for the menu origin. The Units Info preview panes use that
origin too. F12 capture is repaired by converting the renderer's RGB24
readback to RGB565 before the original BMP writer; `--self-test` checks the
conversion and checks that hook emission preserves caller buffers. The
Actions-built helper is included in the public 0.4.0-alpha1 Windows package.

`scripts/client-lab.py` prepares an isolated client from the verified baseline
archive and records each exact child process, creation time, executable hash,
display helper hash, layout and screenshots. Its optional in-engine test
bridge exercises the real Windows mouse-coordinate clamp, dispatches menu
events and checks resulting team/map/spawn state;
it refuses authentication-dialog clicks and unrelated processes. It also
checks map and cursor pixels, catching blank terrain or a pointer drawn away
from its input position even when widget geometry looks valid.
Use `--root <new-lab> prepare --archive <verified-zip>`, then `--root <lab> start
--launcher <Actions-helper> --resolution 1920x1080 --scene login`. For the
non-authentication menu journey use `--scene teams` with the test server's
player credential supplied in `WULFRAM_LAB_PASSWORD`. Save and reuse the
reported run directory for `inspect`, `capture`, `click` and `stop`. A scene
timeout leaves that recorded child intact for diagnosis; do not relaunch it
blindly. Do not commit lab copies, screenshots, credentials or runtime logs.

`scripts/package-client.py` verifies the baseline archive and exact Actions
helper, prepares a clean portable folder, adds Frontier and reversible
Settings.cmd presets, and verifies every file in the resulting ZIP. Pass the
published ZIP checksum to the lab's `prepare --sha256` option to test a fresh
extraction. No developer runtime is needed to play the packaged game.

Release verification included 43 Python tests, Windows/x64/ARM64 CI, the
asset-dependent native binding tests, a five-minute 64-bot/16-simulated-client
run, and a six-minute three-map rotation. The load runs recorded 65 dropped
ticks out of 7,435 and 47 out of 8,955 respectively, with no bots stalled at
their ends. Public TCP/UDP login, team capacity, full-health spawning and
owner vitals were checked from an external host. The public ZIP was downloaded
there in full and its SHA-256 matched. The real packaged Windows client joined
the public 64-bot match and survived a round change before deploying on Mayhem.

## Public connection

The game uses TCP **and** UDP 2627. A Cloudflare DNS-only A record points
`wulfram.canadaverse.org` at the WAN IPv4 address. Forward both protocols on the
router to the Pi, and advertise that same WAN address in `network.server_ip`.
A normal Cloudflare Tunnel published hostname cannot carry this native UDP
game traffic. Keep the web site's existing tunnel route unchanged. Update the
DNS record and advertised address if the WAN IPv4 changes.

Launch the Windows client with `scripts/launch-windows.ps1 -ClientDir <path>`.
The launcher defaults to the public hostname; `-Server <address>` overrides it.
The launcher checks preparation before opening the game. Do not add
`-windowed` or `-allow_windowed`: the former forces the old software renderer
instead of the configured D3D backend. DDrawCompat supplies the borderless
window. Choose a callsign and use the server's player password. Keep the
separate admin password private.

## Checks and rollback

```text
python -m unittest discover -s tests -v
cmake -S physics -B build/physics-linux-x64 -DWULFRAM_PHYSICS_BUILD_TESTS=ON -DWULFRAM_PHYSICS_COLLISION_ROOT=/path/to/content/collision
cmake --build build/physics-linux-x64 --parallel 1
ctest --test-dir build/physics-linux-x64 --output-on-failure
```

Client setup has a regression check using an existing client and supplied
release DLL. It prepares a temporary copy, checks idempotence, preserved
preferences and invalid-DLL rejection, then removes only that temporary copy:

```powershell
.\scripts\prepare-windows-client.ps1 -ClientDir F:\Wulfram\preserved-client\client -CompatibilityDll F:\Wulfram\client-compat-build\w2reg.dll -SelfTest
```

To undo client preparation, close the game and restore the affected files from
their adjacent `.pre-canadaverse-*` backups. No global registry or runtime
installation is changed by preparation.

The CI builds the native core/bindings and checks CPU-player logic without
redistributing game assets. Asset-dependent physics tests run on the Pi.
The 0.4.0-alpha1 deployment retains the previous source, native binding,
configuration and website route. Its guarded recovery script is
`/opt/canadaverse/wulfram/backups/20261012-public-105646f/rollback.sh` on the Pi.
It restores the previous game release and Caddy configuration and disables
only the Wulfram status timer. Check the recorded deployment identities before
using it; do not overwrite unrelated later website changes. The public game
hostname and its TCP/UDP router forwarding were preserved by the deployment.
