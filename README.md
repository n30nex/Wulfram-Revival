# Wulfram 2 Physics Core

An independently written portable C++17 reconstruction of Wulfram II vehicle
physics, together with a CPython binding and an authoritative Python server
that uses the same solver.

This repository contains source code only. It intentionally does **not** ship
the original game, maps, model/collision files, traces, textures, audio, or any
other Wulfram asset. You must supply assets you are legally entitled to use.

## Included

- `physics/`: portable C++ physics core
- `physics/c_api/`: shared-library C interface
- `physics/bindings/python/`: 64-bit CPython extension
- `server/`: authoritative Python Wulfram II server
- `config/server.example.toml`: safe starting configuration

## Requirements

- CMake 3.20 or newer
- A C++17 compiler (Visual Studio 2022, GCC, or Clang)
- 64-bit Python 3.11 or newer, including development headers
- User-supplied Wulfram map and collision data

The Python server otherwise uses only the Python standard library.

## Supply content

Place collision files directly in:

```text
server/wulfram_server/content/collision/
```

The current server can request these identities as gameplay requires:

```text
tank_1_s             tank_2_s
scout_1_s            scout_2_s
pulse_shell_s        cargo_s
energy_1_s           energy_2_s
refuel_1_s           refuel_2_s
repair_1_s           repair_2_s
flak_turret_1_s      flak_turret_2_s
gun_turret_1_s       gun_turret_2_s
```

Place each map in its own directory under:

```text
server/wulfram_server/content/shared/data/maps/<map-name>/
```

Each configured map requires a `land` file. A `state` file is optional, but a
map without authored repair pads may not support ordinary player spawning.
Change `map_name` and `map_rotation` in your server configuration to match the
directories you supplied.

## Build the Python binding

Windows, from a Visual Studio developer shell:

```console
scripts\build-physics.cmd
```

Linux:

```console
./scripts/build-physics.sh
```

The server locates the version-tagged `_wulfram_physics` extension in the
corresponding repository `build` directory. Set `WULFRAM_PYTHON` before running
the script to select a particular interpreter.

## Configure and run the server

Copy `config/server.example.toml` to a local configuration file. Set distinct
passwords in the environment variables named by that file. For the included
example:

```console
set WULFRAM_STAGING_PASSWORD=choose-a-player-password
set WULFRAM_STAGING_ADMIN_PASSWORD=choose-a-different-admin-password
python server\main.py --config config\server.example.toml --check-config
python server\main.py --config config\server.example.toml
```

On a POSIX shell, use `export` instead of `set` and forward slashes in paths.
Use `--content-root` to keep your licensed assets outside the source checkout.
That directory must contain `gameplay.toml`, `packets.toml`, `collision/`, and
`shared/data/maps/` with the same layout described above.

## Building other native interfaces

Configure the root project normally to build the C++ core and C API:

```console
cmake -S . -B build/core -DWULFRAM_PHYSICS_BUILD_PYTHON=OFF
cmake --build build/core --config RelWithDebInfo
```

Asset-dependent tests are off by default. To enable them, supply the required
collision files and configure with:

```console
cmake -S . -B build/test -DWULFRAM_PHYSICS_BUILD_TESTS=ON -DWULFRAM_PHYSICS_COLLISION_ROOT=/path/to/collision
cmake --build build/test --config RelWithDebInfo
ctest --test-dir build/test -C RelWithDebInfo --output-on-failure
```

## Status and fidelity

The implementation covers sequenced input, Tank and Scout control, hover
sensing, integration, terrain and model collision, response, snapshots, and
trace operations. It remains a reconstruction in progress and does not claim
complete behavioral identity with every original-client path.

## License

Copyright (C) 2026 baffler.

The source code is licensed under the GNU Affero General Public License,
version 3 or (at your option) any later version. See `LICENSE`.

The AGPL permits use, modification, and redistribution while requiring covered
modified versions, including versions operated for users over a network, to
offer their corresponding source under the same license. No license to
third-party Wulfram assets or trademarks is granted.
