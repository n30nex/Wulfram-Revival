# Portable physics library

`WulframPhysicsCore` owns portable gameplay-physics policy: explicit integer
time, sequenced inputs, Tank and Scout control, hover sensing, integration,
terrain selection, model-versus-terrain contact, response, snapshots, and trace
events. It contains no operating-system APIs, executable addresses, Python
objects, networking, or original packed layouts.

The public C++ API is under `include/wulfram/physics`. The optional shared C API
is under `c_api`, and the 64-bit CPython binding is under `bindings/python`.

Both MSVC and non-MSVC builds compile as C++17 with floating-point contraction
disabled where the compiler exposes that setting. Fast-math is not used.

Collision shapes use the original game's serialized shape format, but this
repository does not distribute shape files. Tests that require them are off by
default. Supply your own collision directory with
`WULFRAM_PHYSICS_COLLISION_ROOT` when enabling tests.

The solver is still a reconstruction in progress. Stable brute-force
mesh/terrain candidates currently stand in for parts of the original collision
hierarchy and full event/manifold system.
