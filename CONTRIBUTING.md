# Contributing

By contributing, you agree that your contribution is licensed under the
GNU Affero General Public License, version 3 or any later version.

## Choose a change

Start with the [roadmap](ROADMAP.md) and the issue's dependencies and completion
checks. Use `main` as the maintained baseline. Keep independent pull requests
targeted at `main`; if work must be stacked, record the dependency and reconcile
the older pull requests when their commits are integrated.

## Build and check

Follow the [README](README.md) for the C++17/CPython build and the
[revival guide](REVIVAL.md) for external content and client setup. CI uses
Python 3.13 and builds the native binding on Windows x64, Linux x64 and ARM64.
It also builds and checks the 32-bit Windows display helper. Run the asset-free server checks:

```text
python -m unittest discover -s tests -v
```

Gameplay/physics checks requiring original assets need a separate, authorized
content directory. Keep game assets, credentials, private configuration, client
copies and runtime logs outside Git. Share only sanitized evidence.

For background tests on Windows, download the exact candidate's
`wulfram-physics-windows-x64-python313` Actions artifact, verify its run/revision,
and add its extracted directory to `PYTHONPATH` for that shell. Use 64-bit
Python 3.13. `scripts/benchmark-bots.py` runs real native physics and bot combat
without opening a window or listening on a port. Keep checks short and targeted;
no soak tests are part of the active roadmap. This tests simulation, not the
preserved client's rendering or physical input.

For repeatable deployment behavior, run the actual game loop with a simulation
clock and the same native binding and authorized assets:

```text
python scripts/check-bot-deployment.py --content-root /path/to/content --map mayhem --phase 1000 --seconds 75 --output /private-evidence/mayhem.json
```

The scenario contains 64 bots and 16 bot-driven snapshot recipients, opens no
window or listening port, and stops after the requested simulated duration.
`--phase` selects the starting patrol-clock phase; 1000 and 1009 exercise the two
Mayhem patrol phases. Reports bind the harness/native hashes and record when all
bots first deploy. `timing_qualified` always remains false: an accelerated clock
cannot establish real-time performance, actual network players or uptime.
Existing report/log paths are refused. Use a separate short `benchmark-bots.py`
check when measuring wall-clock timing.

For real TCP/UDP lifecycle checks on the same host, keep the native artifact on
`PYTHONPATH` and run:

```text
python scripts/check-network-lifecycle.py --content-root /path/to/content --clients 8 --seconds 5 --switch-team --output /private-evidence/team-switch.json
python scripts/check-network-lifecycle.py --content-root /path/to/content --clients 16 --seconds 8 --output /private-evidence/full-connections.json
python scripts/check-network-lifecycle.py --content-root /path/to/content --clients 16 --seconds 5 --rotate-map mayhem --reconnect --output /private-evidence/map-reconnect.json
```

Each command creates and stops its own loopback-only native server with 64 bots.
The first checks Tank deployment, team changes, old-vehicle deletion and Scout
redeployment with full health/fuel. It requires free team places, so it supports
at most eight clients. The second exercises all 16 human connections. The third
queues a normal map transition after all clients deploy, discards any UDP world
announcements, and requires each client to receive the replacement over TCP,
request its snapshot and deploy again. `--reconnect` repeats login/deployment
with the same callsign, requiring a new player identity and the current map.
The two supported replacement maps are Mayhem and Frontier. Team-switch and
map-change scenarios are separate choices.

Reports require clean disconnects and no remaining UDP peers, human sessions
or registered vehicles belonging to the test clients; they
record the source, native/probe/content hashes, tick counters and coverage limits.
These are bounded protocol checks, with no window, live-server changes or soak.
`timing_qualified` remains false; inspect reported drops separately, and never
infer Pi performance or physical client compatibility from loopback results.

`check-online.py --switch-team` runs the same extra journey against an explicitly
selected endpoint. The initial deployment has a 20-second request deadline;
`--seconds` measures the world sample after deployment. Keep retries and movement
timers running even when no packets arrive. A team switch adds up to 20 seconds
to deploy plus another world sample. `--wait-map NAME` instead allows 30 seconds
for a replacement map, then requests the new snapshot and deployment. It does
not initiate a live map change. These protocol checks do not qualify the
preserved client's rendering or physical input.

## Review and release

The active replacement-client work lives in `client/modern`; its
[build and test guide](client/modern/README.md) describes the pinned Godot toolchain,
synthetic cross-language wire fixtures, headless layout checks, optional bounded
online check and native screenshots. The Windows Actions artifact is separate
from the preserved-client package. Never count headless checks as physical
mouse/DPI proof or promote the development preview as the stable download.

Explain the player-visible problem, the resulting behavior and the checks run
on the exact candidate. Link its roadmap issue and disclose untested coverage.
Changes to the packaged client need the client-harness and actual input/display
checks described in [READINESS.md](READINESS.md). Changes to public services need
a recovery path and verification of the real player journey.

The build workflow tests and uploads artifacts; merging does not deploy the live
server or replace the public download. Release promotion follows the roadmap's
acceptance and human-playtest gates.
