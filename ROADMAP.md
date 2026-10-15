# Wulfram Revival roadmap

Agreed direction: October 12, 2026.

**October 15 priority change:** the maintainer requested building a modern client
from scratch instead of continuing to spend the main effort patching the
preserved executable. M4 now progresses alongside server/bot qualification, before
the first stable release. Keep the current public alpha available as a reference
and fallback. This changes sequencing, not the acceptance standard.

Wulfram Revival is a modern remaster that preserves the original game's hover
handling and combat. Keep the recognizable cockpit, radar and map arrangement;
adapt it for clarity and modern displays. **Original models and textures must
look exactly like the original**, as clarified October 15. Import the actual
geometry, UVs, palette pixels and mip levels; do not replace them with redesigned,
generated or upscaled art. Rendering and lighting parity require comparison with
the preserved client before the appearance gate can close.

**[Play the Windows alpha](https://canadaverse.org/wulfram/)** ·
**[Roadmap tracker](https://github.com/n30nex/Wulfram-Revival/issues/23)** ·
**[All milestones](https://github.com/n30nex/Wulfram-Revival/milestones)**

## Commitments

- Run public matches on the Pi 5 with **64 bots plus 16 human places**. Humans
  joining must not displace bots or be blocked by bot capacity.
- Make the default match welcoming: moderate bots, a guided first deployment
  and brief, visible spawn protection that ends when the player attacks.
- Develop the native Windows replacement now, using the existing public server,
  protocol and authoritative hover physics. Maintain the preserved client as a
  reference and fallback. A native Linux client is deferred.
- Prioritize coordinated attacks, flanking, retreat and getting unstuck in the
  first major bot upgrade.
- Qualify the existing feature set for the first stable release. Deeper original
  systems and expansion features follow later.
- Deploy completed, validated increments to the public alpha as they are ready,
  with a verified recovery path and post-deployment Internet checks.
- Advance through acceptance checks, with **no fixed release dates**. The
  maintainer and a small group of returning and new players must approve the
  experience alongside automated checks.

## Current position

The public release is a playable alpha. It already provides the Windows package,
public server, 64-bot matches and development work on display compatibility,
tactical roles and reliability. Stable qualification remains open, including
display/input coverage, bounded operating checks and mixed-experience playtests.

The reviewed alpha implementation is integrated into the default branch through
[PR #5](https://github.com/n30nex/Wulfram-Revival/pull/5). M0 establishes this
public development baseline and its reproducible build instructions. See
[release readiness](READINESS.md) for candidate-specific evidence, deployed
source/package identities and remaining limitations.

Issue checklists and milestones hold live progress. This document records scope,
sequence and release rules; an item stays open until its completion checks have
evidence.

## Delivery sequence

| Stage | Player or contributor outcome | Advance when |
| --- | --- | --- |
| [M0: Public development baseline](https://github.com/n30nex/Wulfram-Revival/milestone/1) | Public source, build instructions and the playable revival agree. | Reviewed existing work is integrated and its source/artifacts are traceable. |
| [M1: Dependable public play](https://github.com/n30nex/Wulfram-Revival/milestone/2) | Players can download, connect and play reliably with correctly aligned displays and controls. | Network, Pi operation, Windows input/display and clean-install checks pass. |
| [M2: Tactical bots and a welcoming first match](https://github.com/n30nex/Wulfram-Revival/milestone/3) | Bots work as teams; new players can deploy and learn without losing their place to bots. | Navigation, tactics, onboarding and spawn-protection checks pass. |
| [M3: First stable release](https://github.com/n30nex/Wulfram-Revival/milestone/4) | A release we can confidently invite people to play. | M0-M2 are complete and the exact candidate passes qualification and human approval. |
| [M4: Playable replacement client](https://github.com/n30nex/Wulfram-Revival/milestone/5) | A modern Windows client preserves Wulfram's feel and familiar HUD. | A networked gameplay slice, modern presentation and compatibility/playtest checks pass. |
| [M5: Classic systems and logistics bots](https://github.com/n30nex/Wulfram-Revival/milestone/6) | Original base and logistics loops return, with bots that build, supply and repair. | Restored systems and support bots work through complete matches. |

M1, M2 and M4 now progress together after M0. The supported client, server and bot
acceptance checks must pass before M3. M5 follows the playable replacement client.
Individual issues record more specific dependencies.

## Work packages

### M0: Public development baseline

- [#6: Integrate the verified revival baseline into the public default branch](https://github.com/n30nex/Wulfram-Revival/issues/6).

### M1: Dependable public play

- [#7: Qualify sessions and world updates under loss, delay and reconnects](https://github.com/n30nex/Wulfram-Revival/issues/7).
- [#8: Verify bounded operating checks and service recovery](https://github.com/n30nex/Wulfram-Revival/issues/8).
- [#9: Qualify Windows resolutions, HUD placement and actual input alignment](https://github.com/n30nex/Wulfram-Revival/issues/9).
- [#10: Make the Windows download reproducible and qualify a clean first run](https://github.com/n30nex/Wulfram-Revival/issues/10).

The display work covers login, team/map selection and gameplay. It must measure
actual rendering and mouse alignment across supported resolutions, DPI settings
and window transitions. Use short, targeted background checks on the development
host for 64 bots, map changes and human connection churn, plus scoped service
recovery checks. No soak tests are planned or required, following the maintainer's
October 13 direction. Use isolated background tests that do not depend on an
unlocked desktop. Deploy completed validated changes to the live alpha as they
are ready; a scoped game-service restart can briefly disconnect players. Record
each check's duration and limits without inferring long-term uptime. Package
checks start from the public download on a clean, ordinary Windows account.

### M2: Tactical bots and a welcoming first match

- [#11: Qualify terrain routing, crowd avoidance and stuck recovery](https://github.com/n30nex/Wulfram-Revival/issues/11).
- [#12: Give bot teams coordinated attacks, flanking and sensible retreat](https://github.com/n30nex/Wulfram-Revival/issues/12).
- [#13: Guide the first deployment and add bounded spawn protection](https://github.com/n30nex/Wulfram-Revival/issues/13).

Reproduce the reported hill pileups and single-file movement in navigation and
tactics checks. Bots need useful objectives, varied routes, separation and
recovery while obeying normal vehicle limits. Keep default difficulty moderate
and document fair sensing and aiming limits. Onboarding must distinguish a
rejected password from an unreachable server and provide a clear retry path.

### M3: First stable release

- [#14: Run the stable-release qualification and mixed-experience playtests](https://github.com/n30nex/Wulfram-Revival/issues/14).
- [#15: Approve and publish the first stable public release](https://github.com/n30nex/Wulfram-Revival/issues/15).

Testers must cover the full journey: download, first launch, login, team/pad
selection, movement and combat, death/respawn, map rotation and reconnecting.
Returning players assess hover handling and combat feel; new players assess
whether the instructions and controls let them play without someone operating
the client for them. Record the maintainer's and both groups' approval against
the exact candidate.

### M4: Playable replacement client

- [#16: Choose the replacement-client architecture through a bounded spike](https://github.com/n30nex/Wulfram-Revival/issues/16).
- [#17: Build a networked replacement-client gameplay slice](https://github.com/n30nex/Wulfram-Revival/issues/17).
- [#18: Redraw the familiar cockpit and improve the classic sci-fi presentation](https://github.com/n30nex/Wulfram-Revival/issues/18).
- [#19: Qualify the replacement-client alpha and its transition path](https://github.com/n30nex/Wulfram-Revival/issues/19).

The initial implementation uses Godot 4.7.2, native TCP/UDP and the existing
server's authoritative physics. See [the native client](client/modern/README.md)
for the bounded prototype, build recipe and limitations. The first live checks
connect, select a team, deploy and move without the preserved executable.
The native asset loader reads the original visual meshes and texture archives;
terrain composition, original effect/UI coverage and visual comparison remain
required. Approximate development geometry is not acceptable final content.
Compare handling and combat with the preserved client and retain the recognizable
cockpit/radar/map relationship. Qualify the transition before making the
replacement the default download. A passing connection test does not close M4.

### M5: Classic systems and logistics bots

- [#20: Inventory and prioritize missing original gameplay systems](https://github.com/n30nex/Wulfram-Revival/issues/20).
- [#21: Restore coherent base, power, cargo and construction loops](https://github.com/n30nex/Wulfram-Revival/issues/21).
- [#22: Add bots that build, supply and repair their team](https://github.com/n30nex/Wulfram-Revival/issues/22).

Restore coherent gameplay loops in an explicit order, then teach bots to support
them. Building, supplying and repairing bases take priority over unrelated new
modes or account systems after the replacement client becomes playable.

## Release and evidence rules

- Record the exact source revision, package identity, test setup and sanitized
  results for each completed item. Reopen a gate if later changes invalidate it.
- Verify public downloads and a real internet session against the release
  candidate. Server status and build success are useful checks, but neither
  proves the complete player journey.
- Keep supported hardware and display coverage explicit. A logical-resolution
  screenshot does not establish physical 4K or mouse/DPI compatibility.
- Resolve release-blocking defects before promotion. Document limitations,
  installation/trust requirements, asset provenance and the recovery path.
- Obtain the agreed human approvals before calling a release stable or making
  the replacement client the default. Production readiness applies to the
  complete supported experience.

## Later candidates

Accounts, persistent progression, squads, further modes/maps/vehicles/weapons
and a native Linux client remain unscheduled. Some related alpha features already
exist; future work should assess and extend them instead of assuming a blank
slate. These candidates must not displace the agreed stable-release gates or
the priority for restored original systems and logistics bots.
