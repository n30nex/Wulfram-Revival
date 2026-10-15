# Wulfram Revival modern client

**Development preview, Windows x64.** This is the first native replacement-client
slice, not the stable release or finished remaster. The public preserved-client
download remains available while this client is developed.

The client connects directly to the existing Wulfram Revival TCP/UDP server.
The server's reconstructed C++ hover physics and combat remain authoritative.
Godot renders/interpolates the received state; this slice does not approximate
hover physics with a new controller. Client prediction is still future work.

## Play the preview

Keep `WulframRevival.exe`, `WulframRevival.pck`, `maps` and `original` together.
Open the executable, choose a unique callsign, and connect to
`wulfram.canadaverse.org` with the public join code `canadaverse`.
Choose Crimson or Azure, select a friendly repair pad, then Deploy.
The client retries a busy pad for up to 20 seconds; choose another if it stays busy.

- W/S: forward and reverse; A/D: strafe; Q/E: turn.
- Space: jump jets; left mouse: primary weapon.
- F2: first/third-person camera; F12: screenshot.
- Deployment button or Escape: open the team/deployment panel.
- Disconnect returns to the connection screen without restarting.

Screenshots go in Godot's application user-data `screenshots` folder. The native
renderer captures both UI and world and saves a small diagnostic JSON beside it.
It does not save passwords or raw network packets.

## Build and check

Engine: [Godot 4.7.2 stable](https://godotengine.org/download/archive/4.7.2-stable/),
standard Windows x64 edition, Compatibility renderer. The build script pins and
checks the official SHA-512 hashes before extracting the editor/export templates.
No .NET, Python or editor installation is needed by the exported client.

```powershell
./scripts/build-modern-client.ps1
python scripts/import-modern-maps.py --content-root /path/to/authorized/content --output build/modern-client/maps
python scripts/import-original-assets.py --client /path/to/preserved/client --output build/modern-client/original
```

Repeat `--content-root` when maps are stored in separate content roots. The
importer copies the supported terrain grids and texture tables, records their checksums and
does not commit original assets. The Actions artifact contains the executable,
game pack, source identity and checks; the separately imported map manifest must
also be included when assembling a playable distribution.

The original-asset importer copies the original archives verbatim and records
their hashes. The native loader reads the original visual meshes (not collision
substitutes), UVs, attachment points, palette pixels and stored mip levels.
No replacement or AI-generated models/textures are used. All 39 visual models
and their 175 referenced textures pass the local archive check.

For development, import maps to `client/modern/content/maps` and the original
archives to `client/modern/content/original`, then open
`project.godot`. Run the bounded checks with:

```text
python scripts/check-modern-client.py --godot /path/to/godot_console.exe
godot_console.exe --headless --path client/modern -- --online-smoke
```

`--online-smoke` makes one short player connection to the public server, selects
Crimson, deploys, moves and disconnects. It stops after at most 35 seconds. Do not
use it as a soak or as evidence of physical rendering/input. `--connect` starts
the normal UI already connected as ModernPilot; `--server=HOST` overrides its
server. `--fullscreen`, `--capture-start`, and `--capture-dir=PATH` support local
display qualification without desktop screenshot tools.

## Current scope and gaps

Implemented: direct native session/bootstrap, current server quantizer validation,
world snapshots, team acknowledgement, Tank/Scout deployment, server-driven
poses/vitals, primary-weapon input, two cameras, cockpit radar/map, bounded
deployment retries, reconnect UI and screenshots. Terrain comes from the same
grids used by the server. New UI uses Godot's layout/input transforms.

The maintainer requires the original models and textures to look exactly like
the original. The loader preserves those assets, while full appearance parity
is still under qualification. Terrain uses original tile bitmaps and the original
bank-1 dither masks; the old renderer's variant/priority selection and exact
lighting/effect/UI presentation still need side-by-side comparison. Sound,
mouse aiming, complete weapon/equipment interfaces,
prediction/reconciliation, full loss/reordering/map/death tests, accessibility,
GPU/DPI coverage and human playtests are not qualified. No claim of production
readiness, pixel-identical terrain composition or complete combat presentation is made. Do not replace the main
download with this preview until the replacement-client gates pass.

Godot is MIT licensed; see [Godot's license and third-party notices](https://godotengine.org/license/).
The revival code follows the repository LICENSE/NOTICE. Original terrain remains
attributed to its original creators; importing it does not change its ownership.
