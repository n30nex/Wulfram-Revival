# Preserved-client network qualification

Roadmap [#7](https://github.com/n30nex/Wulfram-Revival/issues/7) remains open.
This lab exercises the shipped Windows client through reproducible TCP/UDP
faults. Use a private test server with isolated state; record its exact source,
Actions-built native artifact, content identity and population before testing.
Keep screenshots, dumps and detailed run receipts outside Git.

## Relay

`scripts/network-lab.py` accepts one TCP client on loopback and rewrites only the
server's advertised UDP endpoint to that same loopback port. It checks that the
original advertised endpoint matches the explicitly supplied upstream. The
matching UDP peer is fixed after its first datagram. TCP preserves framing and
byte order, drains pending bytes before forwarding FIN, and rejects truncated
frames. Credentials and packet bodies remain in memory only.

Each UDP direction has an independent seeded random generator. A given ordered
input stream produces the same faults; live packet timing and traffic may vary.
Reports bind the relay source hash, PID and UTC timestamps to opcode counts,
actual deliveries and queue peaks. Queues are
bounded to 128 KiB per TCP destination and 128 KiB/512 UDP datagrams overall;
individual UDP datagrams are limited to 4096 bytes. Overload fails the test.

| Profile | One-way base delay / jitter | UDP loss | Duplicates | Targeted loss |
| --- | --- | --- | --- | --- |
| `clean` | 0 / 0 ms | 0 | 0 | None |
| `latency` | 80 / 30 ms | 0 | 0 | None |
| `reorder` | 60 / 60 ms | 0 | 10% | None |
| `loss` | 50 / 30 ms | 5% | 2% | None |
| `bootstrap-loss` | 0 / 0 ms | 0 | 0 | First server HELLO-verified and handshake |
| `spawn-loss` | 0 / 0 ms | 0 | 0 | First server TANK |

UDP jitter can also reorder adjacent messages in the `latency` profile. TCP
receives only the base delay; it remains an ordered stream. These are bounded
application-layer fault scenarios, not a simulation of every Internet failure.

```sh
python scripts/network-lab.py --upstream-ip PI_LAN_IPV4 --upstream-port 2630 \
  --listen-port 2631 --profile spawn-loss --seed 2627 --seconds 240 \
  --report /private-evidence/new-run.json
```

Wait for the report to say `ready`, then point a fresh client-lab extraction at
`127.0.0.1:2631`. Use a new report path for every attempt; existing reports cannot
be overwritten. Pair the relay report with the exact client run, sustained scene
checks, observed repair-pad clicks and screenshots. Do not infer a passing
journey from relay status: `complete` means both TCP directions closed cleanly.
An intentional harness termination can produce a reset and a failed transport
receipt after successful gameplay. Record that termination separately. Check
receipt freshness and process liveness after interruptions.

For a scripted server check, use `check-online.py --spawn-once --drive` through
the relay. The report must show exactly one `spawn_requests_sent`, a received
TANK and a successful journey; the relay must show the targeted TANK drop and a
later TANK delivery. Otherwise a repeated pad request could mask a missing
server retry. This protocol probe supplements the separate preserved-client
journey and cannot establish its rendering or gameplay behavior.

## October 13 results before the spawn retry fix

Server: `675bdda2f763b330b28d5daed2c3c1eed87b57a6`, eight bots, private Pi instance.
Windows package: `0.4.0-alpha2`, source
`906fba4896918328de55167abd2a66bcab7d05da`, Actions `38324818801`.
Package SHA-256:
`4327276ed0d24a99d593f008dbf3888aaf7bced088b24171819c1d7987f76913`.
Requested display: 1920x1080 on Windows 10; logical renderer: 960x540.

| Scenario | Observed result |
| --- | --- |
| Clean, second run | Map/model and pointer checks passed; pad click reached a sustained full-health Frontier world. Harness then stopped its own child. |
| Bootstrap loss | Both targeted startup messages were dropped; login, map and pad click recovered to a sustained full-health world. Harness then stopped its own child. |
| First TANK loss | One TANK was dropped. Client stayed on the map for over a minute, acknowledged snapshots, and sent no `0x19` request or owner control input. Failed deployment. |
| Delay/jitter | First attempt was closed by the user. A repeat disconnected during startup and did not reach the map. Cause remains unresolved; it is not a passing result. |
| Random loss / dedicated reorder | Not yet qualified with the real client. |

Native inspection explains the first-TANK failure: `0x19` is emitted after a
received TANK fails to create its entity. It cannot recover a TANK that never
arrives. Repeated TANKs for an existing entity retain its pose and apply current
timestamped vitals, but reload its keymap. Retry only briefly and stop promptly
when valid owner control arrives. Keep raw native UDP framing.

The server fix retries current TANK state every 0.5 seconds for at most eight
seconds, bound to the exact live entity. It stops on valid owner input or an
invalidated lifecycle and never renews health, fuel or spawn protection. Action
packets contain no entity ID, so delayed input from a previous life remains an
explicit protocol ambiguity to exercise under reordering. Automated regression
coverage does not replace the pending real-client retest of the exact candidate.

## Pi protocol-probe results after the fix

Private server source: `8bbebf2867a8745a0be43eaf3fc3a1c0b2f4cd34`, version
`0.4.0-alpha2.4-test`, eight bots, Crossroads. Actions run `38364764482` built
its ARM64 binding, SHA-256
`11b59a63903cf4755f03799c681b9c82ee1555f01a173a0c2a377ad7008e986c`.
The public server used alpha2.3 during these private tests. The fix is now live
in alpha2.4, source `2caef4bf497c677cf21ce40622393db9447b5ca0`; see
[deployment evidence](READINESS.md#live-deployment-october-13-2026-1333-utc).

The targeted first-TANK test passed twice with exactly one deployment request:
the server sent a second TANK after the relay dropped the first, and the probe
received it after 0.520 and 0.511 seconds. Movement followed at full health,
with no missing owner vitals. Retries stopped after owner controls arrived.

Scripted journeys also completed under clean, bootstrap-loss, latency/jitter,
reorder/duplication and random-loss profiles. Each used an eight-second world
sample, with actual queue/drop/order counters and a completed relay receipt.
These are short protocol checks with eight bots. The preserved client's fixed
spawn path, its delay/jitter startup failure and the full lifecycle/load matrix
still require separate qualification.

Retain the failed attempts: an earlier latency probe closed its receive side
before delayed TCP bytes drained, producing a reset after successful gameplay.
The probe now half-closes and waits up to two seconds for server EOF; the repeat
completed cleanly. An earlier random-loss run with pad retries deliberately
disabled received no TANK. A repeat using normal pad-retry behavior passed;
that earlier rejection was not diagnosed and must not be erased or counted as
success. Use `--spawn-once` to isolate targeted TANK loss, not as a general
substitute for the client's request recovery.

Final probe source SHA-256:
`36c5c0ede79206c25325ba687b3efce0266326f9511cbf36b6256e7177d6ef0a`.
Relay source SHA-256:
`b39572f6187c8186785caccd0ebe1c149f92271ecc14ed0b6b8ca698d5896667`.
All 91 Python tests and the Windows/x64/ARM64 build checks pass for the server
implementation. Native desktop testing paused when Computer Use was stopped;
none of these scripted results substitutes for that pending test.

## Remaining acceptance

The alpha2.5 update adds real loopback lifecycle checks and external team-change
journeys, with explicit Tank/Scout identities, death/deletion notices and Scout
fuel validation. All eight team-switch clients and all 16 connection-capacity
clients completed their respective background scenarios with the 64-bot roster.
The eight-client timing result missed its target; full adverse-network lifecycle
coverage remains open. See [current deployment evidence](READINESS.md#live-alpha25-and-network-lifecycle-checks-october-13-2026)
and [reproduction commands](CONTRIBUTING.md).

- Retest targeted loss, delay/jitter, random loss and reordering against the
  exact candidate, including failed/retried login, both teams and deployments.
- Cover death/respawn, creation/deletion, chat, full map changes and reconnects;
  check for missing vitals, ghost objects and permanent stalls.
- Repeat with 64 bots and 16 human connections; retain bounded work and memory.
- Diagnose the native client's Quit/reset cleanup fault at executable offset
  `0xdc7e7`, separately from its intermittent `D3DIM700.DLL` fault.
- Complete physical mouse/DPI/display coverage. In-engine screenshots and click
  checks establish only their explicitly recorded rendering/input paths.
