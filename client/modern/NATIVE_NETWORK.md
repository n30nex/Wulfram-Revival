# Native lifecycle protocol

The native client opts into `lifecycle-v1` with an authenticated ROOT greeting.
It sends the new greeting followed by the existing `actions-v1,combat-v1`
greeting in the same datagram. Older revival servers finish on the recognized
greeting and retain precise controls/combat feedback. New servers remember the
lifecycle request and freeze all active capabilities during bootstrap. A later
greeting cannot change the active format. Retail and earlier native clients
keep their existing wire format.

## Scope envelope

Opcode `0x50` encloses one unchanged original packet body. Fields are big-endian:

| Field | Size | Meaning |
| --- | --- | --- |
| Opcode | u8 | 0x50 |
| Connection generation | u64 | Nonzero random 63-bit value, bound by TCP bootstrap |
| World epoch | u32 | Advances on each map replacement, including reloads |
| Owner entity | u32 | Recipient vehicle for local state; sending vehicle for owner requests |
| Request sequence | u32 | Client packet order; server messages use zero |
| Body length | u16 | Exact following byte count |
| Body | bytes | One original opcode and its fields |

The header is 23 bytes. The maximum body is 8167 bytes, fitting the existing
8192-byte inbound TCP frame limit. Nested envelopes are rejected. Native UDP
updates remain at most 1200 bytes, including the envelope. Connection generations
are correlation identifiers, not authentication credentials or encryption.

## Reliable transitions and ownership

Native world announcements, TANK ownership, deletion, birth/death notices,
deployment replies, carrying and docking state travel over TCP. Roster, score,
chat and acknowledgement packets also use TCP with epoch zero because they
belong to the connection. Regular entity/view updates and cosmetic transients
remain UDP, tagged with their connection, map and local-stat owner.

The client accepts map announcements only over TCP. It drops previous-connection,
old-map, unscoped native-world and UDP control packets. Before a world is loaded,
raw game packets cannot create vehicles. Bootstrap identity/configuration must
arrive over TCP. Local vitals from another vehicle cannot overwrite a respawn's
vitals. Duplicate TANK deliveries do not emit another deployment; deleted/older
vehicles cannot become the current owner. Sequence comparisons handle wraparound.

Client movement stays UDP; discrete native gameplay requests use TCP. Requests
carry the current map and, where applicable, vehicle ID. Retries retain the
original envelope rather than rebinding to a later vehicle. Movement sequences
reject reordered/replayed input. Native mutations execute on the simulation
thread, so validation and ownership changes share the same ordering.

Each client has at most 64 queued requests, with eight processed per simulation
iteration. A separate existing control worker drains at most 64 messages at a
time from a 512-message queue; it never holds the queue lock during a TCP write.
Overflow disconnects that peer rather than blocking the simulation. Socket
writes retain their two-second deadline. New-world control waits for its reliable
announcement, and old-world control is retired. Snapshot chunks retain the epoch
captured before sending. The readiness acknowledgement uses the announcement's
world lock, including when it arrives before the send call finishes.

## Bounded checks

- Independent Python/GDScript fixtures cover scope bytes, truncated messages,
  connection/map/owner binding, stale acknowledgements, retry identity, duplicate
  deployment, stale vitals and serial wraparound.
- Server tests cover authenticated opt-in, unchanged retail delivery, datagram
  limits, stale requests, thread-local dispatch authorization, bounded queues,
  slow TCP isolation and the fast-readiness race.
- `check-modern-lifecycle.py` reproduced the previous client's stuck death by
  dropping one UDP deletion. With the native protocol it checks death/respawn,
  old input replay, map replacement, old world replay, same-callsign reconnect,
  previous-connection replay and session/entity/native-body cleanup. Use
  `--map-content-root` and `--next-map` to include the full map/reconnect journey.
- `check-modern-session.py --journey capacity` admits fifteen native peers and
  one legacy probe alongside 64 bots, respecting the production limit of four
  concurrent unauthenticated connections per source IP. It requires 80 roster
  places and sixteen simultaneously active human vehicles, movement and cleanup.
- `--online-smoke --require-lifecycle` refuses to pass on the older fallback
  protocol. It is a short check, not a soak or physical input qualification.

Older servers retain their original UDP lifecycle limits. These checks do not
certify every network fault combination, Pi capacity, sustained uptime or human
gameplay approval. Original physics and media are unchanged.
