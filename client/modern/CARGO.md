# Original cargo controls

Touch a cargo crate to pick it up. The original comma key drops the crate;
period deploys its contents. The cockpit also provides clickable buttons while
F1 releases the mouse. Typing punctuation in chat or using a menu cannot trigger
these gameplay shortcuts. Only one cargo request can be pending at a time.

Cargo names and carrying state come from server packet `0x29`. Enemy cargo stays
redacted as locked; both the client and server reject its deployment, while
dropping preserves the enemy team. The server remains responsible for pickup,
entity creation and team ownership. The client never clears cargo optimistically:
a transport acknowledgement is not a confirmed state change. Unconfirmed actions
time out after five seconds with an uncertainty message. Death, map replacement
and reconnect clear cargo, docking state and pending cargo retries.

Requests use the original reliable `0x2b` body: mode 0 for drop, 1 for deployment.
Native sessions retain the existing connection/map/vehicle scope. Original and
older revival servers retain the legacy transport fallback and its known limits.

The carried crate uses the original `cargo` mesh and each Tank/Scout model's
original `cargo_pos` attachment, including remote players. Meshes, texture bytes,
UVs and original attachment coordinates are unchanged. Confirmed changes play
the original `CARGO_PICKUP` / `CARGO_DROP` clips; duplicate updates do not replay
them. The existing original missile-launcher and skypump models are now also
mapped to their deployed unit types.

Reference evidence: the preserved `data/keymap` and `data/help/basic` document
the controls and contact pickup. The original executable's unit-info construction
at `0x004e441d` onward supplies names for unit types 25..36 (cargo IDs 0..11).
Its locked-enemy cargo message is at `0x0055d304`. Reference executable SHA-256:
`94990864ab1db2ddbe2652cfdbca726356b19dd3fb7597945e297a43973d99d4`.

`check_cargo.gd` exercises real GUI routing at five window sizes, chat/menu
isolation, pending/timeout/acknowledgement behavior, owner/map cleanup, redaction
and original attachment placement when authorized assets are available. Its GPU
mode can require focused-window keyboard routing with `--require-keyboard`;
engine-generated events do not qualify physical mouse, DPI or hardware coverage.

`scripts/check-modern-session.py --journey cargo` creates crates in contact with
a real native-physics vehicle on a private server with 64 bots. Pickup happens
through normal collision events. It verifies drop, friendly deployment, repeated
requests and a forged enemy-deployment request, then removes test fixtures and
stops the server. It never creates cargo on the public server.

This increment does not complete the original construction system. Unlocking
stolen cargo at repair pads, power networks, placement constraints, construction
timing and units without recovered presentation/behavior remain open under the
classic-systems roadmap. Full visual and human gameplay approval remain open.
