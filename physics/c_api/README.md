# C API

`WulframPhysicsC` exposes the portable solver through an opaque-handle shared
library suitable for foreign-function interfaces and native engine adapters.
The API supports world and terrain creation, dynamic and static bodies,
sequenced vehicle input, fixed stepping, snapshots, traces, impulses, and
authoritative restore/replay operations.

Callers retain ownership of input buffers for the duration of each call. State
returned through snapshots is copied across the boundary. The library has no
dependency on Python or on the Wulfram server.
