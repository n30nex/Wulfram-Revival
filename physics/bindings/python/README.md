# CPython binding

`WulframPhysicsPython` is the coarse 64-bit CPython binding for
`WulframPhysicsCore`. It uses the CPython C API, releases the GIL around native
world steps, and returns copied snapshots and trace events. No Python callback
runs inside controller, contact, or vector loops.

Build it from the repository root with `scripts/build-physics.cmd` on Windows
or `scripts/build-physics.sh` on Linux. The extension must be rebuilt for the
Python implementation, minor version, architecture, and platform that will run
the server.
