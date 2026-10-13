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

## Remaining acceptance

- Retest targeted loss, delay/jitter, random loss and reordering against the
  exact candidate, including failed/retried login, both teams and deployments.
- Cover death/respawn, creation/deletion, chat, full map changes and reconnects;
  check for missing vitals, ghost objects and permanent stalls.
- Repeat with 64 bots and 16 human connections; retain bounded work and memory.
- Diagnose the native client's Quit/reset cleanup fault at executable offset
  `0xdc7e7`, separately from its intermittent `D3DIM700.DLL` fault.
- Complete physical mouse/DPI/display coverage. In-engine screenshots and click
  checks establish only their explicitly recorded rendering/input paths.
