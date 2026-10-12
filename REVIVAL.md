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
the registry compatibility shim documented in that project's CLIENT_COMPAT.md.
Build the shim as a release binary; the preserved debug DLL requires debug CRTs.

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
`-Windowed` selects the original small diagnostic window. Choose a callsign
and use the server's player password. Keep the separate admin password private.

## Checks and rollback

```text
python -m unittest discover -s tests -v
cmake -S physics -B build/physics-linux-x64 -DWULFRAM_PHYSICS_BUILD_TESTS=ON -DWULFRAM_PHYSICS_COLLISION_ROOT=/path/to/content/collision
cmake --build build/physics-linux-x64 --parallel 1
ctest --test-dir build/physics-linux-x64 --output-on-failure
```

The CI builds the native core/bindings and checks CPU-player logic without
redistributing game assets. Asset-dependent physics tests run on the Pi.
Deployment rollback is `systemctl disable --now wulfram.service`, retaining
the source, content and state directories for recovery. Disable the named
Wulfram router rule and remove its DNS record to withdraw public access.
