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
Python 3.13 and builds the native binding on Linux x64 and ARM64. It also builds
and checks the 32-bit Windows display helper. Run the asset-free server checks:

```text
python -m unittest discover -s tests -v
```

Gameplay/physics checks requiring original assets need a separate, authorized
content directory. Keep game assets, credentials, private configuration, client
copies and runtime logs outside Git. Share only sanitized evidence.

## Review and release

Explain the player-visible problem, the resulting behavior and the checks run
on the exact candidate. Link its roadmap issue and disclose untested coverage.
Changes to the packaged client need the client-harness and actual input/display
checks described in [READINESS.md](READINESS.md). Changes to public services need
a recovery path and verification of the real player journey.

The build workflow tests and uploads artifacts; merging does not deploy the live
server or replace the public download. Release promotion follows the roadmap's
acceptance and human-playtest gates.
