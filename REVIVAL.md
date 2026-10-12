# Canadaverse Wulfram II

This fork adds simple combat CPU tanks and a native Raspberry Pi 5 server
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

`bots_per_team = 2` starts four CPU players and reserves human slots. CPU tanks
pursue enemy vehicles and bases, use the normal weapons/fuel/cooldown rules,
and respawn from unoccupied living friendly pads. Navigation is direct pursuit
with jumping, so difficult terrain can still strand them. These are basic
combat opponents, without base-building strategy or route planning.

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
Deployment rollback is `systemctl disable --now wulfram.service`, retaining
the source, content and state directories for recovery. Disable the named
Wulfram router rule and remove its DNS record to withdraw public access.
