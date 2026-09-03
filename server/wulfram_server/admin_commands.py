from __future__ import annotations

from dataclasses import dataclass
import queue
import random
import re
import time
from typing import Any

from wulfram_server import application as app
from wulfram_server.core.entity import TEAM_ID_BY_SIDE
from wulfram_server.core.land import LandMap
from wulfram_server.core.map_loader import MapLoader
from wulfram_server.network.packets import WorldStatsPacket


MAP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAP_CHANGE_ENTITY_INTERVAL_SECONDS = 0.25
REPAIR_PAD_UNIT_TYPE = 27
COMPETING_TEAM_IDS = (1, 2)
TEAM_NAMES = {1: "Red", 2: "Blue"}


@dataclass(frozen=True, slots=True)
class MapChangeRequest:
    context: Any | None
    map_name: str
    reason: str = "administrator"


@dataclass(slots=True)
class MapChangeTransition:
    request: MapChangeRequest
    replacement_land: LandMap
    state_text: str | None
    next_entity_at: float


@dataclass(slots=True)
class MatchState:
    armed: bool = False
    winner_team: int | None = None
    pending_map: str | None = None


@dataclass(frozen=True, slots=True)
class BotRequest:
    context: Any
    action: str
    name: str | None = None
    team: int | None = None


def initialize(server: Any) -> None:
    server.admin_command_queue = queue.Queue(maxsize=1)
    server.map_change_transition = None
    server.match_state = MatchState()


def _send(context: Any, message: str) -> None:
    try:
        app.send_system_message(context, message)
    except OSError as error:
        print(f"[admin] could not send command response: {error}")


def _command_parts(message: str) -> list[str]:
    parts = message.strip().split()
    if parts and parts[0].casefold() == "/s":
        parts = parts[1:]
    return parts


def process(context: Any, message: str) -> bool:
    parts = _command_parts(message)
    if not parts:
        return False
    command = parts[0].casefold()
    if command not in {"help", "status", "map", "bot", "team"}:
        return False
    if not bool(getattr(context.session, "is_admin", False)):
        _send(context, "Administrator access required.")
        return True

    if command == "help":
        _send(
            context,
            "Admin commands: /s status, /s map <map-name>, "
            "/s bot add [name] [1|2], /s bot remove <name|all>, "
            "/s team <red|blue|neutral>",
        )
        return True

    if command == "team":
        side = parts[1].casefold() if len(parts) == 2 else ""
        if side not in TEAM_ID_BY_SIDE:
            _send(context, "Usage: /s team <red|blue|neutral>")
            return True
        if app.switch_session_team(context, TEAM_ID_BY_SIDE[side]):
            _send(context, f"Switched to the {side} team.")
        else:
            _send(context, f"You are already on the {side} team.")
        return True

    if command == "bot":
        if len(parts) < 2:
            _send(context, "Usage: /s bot add [name] [1|2] | remove <name|all>")
            return True
        action = parts[1].casefold()
        if action == "add" and len(parts) <= 4:
            name = parts[2] if len(parts) >= 3 else None
            try:
                team = int(parts[3]) if len(parts) == 4 else None
            except ValueError:
                team = 0
            if team not in (None, 1, 2):
                _send(context, "Bot team must be 1 or 2.")
                return True
            request = BotRequest(context, action="add", name=name, team=team)
        elif action == "remove" and len(parts) == 3:
            request = BotRequest(context, action="remove", name=parts[2])
        else:
            _send(context, "Usage: /s bot add [name] [1|2] | remove <name|all>")
            return True
        try:
            context.server.admin_command_queue.put_nowait(request)
        except queue.Full:
            _send(context, "An administrative change is already queued.")
            return True
        _send(context, f"Bot {action} queued.")
        return True

    if command == "status":
        players = sum(
            bool(getattr(session, "is_logged_in", False))
            for session in context.server.sessions
        )
        entities = len(context.server.entities.get_all())
        _send(
            context,
            f"Server status: map={context.server.current_map_name} "
            f"players={players} entities={entities}",
        )
        return True

    if len(parts) != 2:
        _send(context, "Usage: /s map <map-name>")
        return True
    queue_map_change(context, parts[1])
    return True


def queue_map_change(context: Any, map_name: str) -> bool:
    """Validate and enqueue a guarded map transition."""
    if MAP_NAME_PATTERN.fullmatch(map_name) is None:
        _send(context, "Invalid map name.")
        return False
    if getattr(context.server, "map_change_transition", None) is not None:
        _send(context, "A map change is already in progress.")
        return False
    if map_name == context.server.current_map_name:
        _send(context, f"Map {map_name} is already active.")
        return False
    if not app.verify_map_land_exists(context.server, map_name):
        _send(context, f"Map {map_name} has no land file.")
        return False

    try:
        context.server.admin_command_queue.put_nowait(
            MapChangeRequest(context, map_name)
        )
    except queue.Full:
        _send(context, "A map change is already queued.")
        return False
    suffix = (
        ""
        if app.verify_map_state_exists(context.server, map_name)
        else " (terrain only; no state file)"
    )
    _send(context, f"Map change queued: {map_name}{suffix}")
    return True


def _broadcast_system_message(server: Any, message: str) -> None:
    for session in list(server.sessions):
        context = getattr(session, "udp_context", None)
        if bool(getattr(session, "is_logged_in", False)) and context is not None:
            _send(context, message)


def _respond_to_map_request(request: MapChangeRequest, message: str) -> None:
    if request.context is not None:
        _send(request.context, message)
    else:
        print(f"[admin] automatic map change: {message}")


def _team_resources(server: Any, team_id: int) -> bool:
    for session in server.sessions:
        if not bool(getattr(session, "is_logged_in", False)):
            continue
        if int(getattr(session, "team", 0) or 0) != team_id:
            continue
        entity = getattr(session, "entity", None)
        if (
            entity is not None
            and server.entities.get_entity(entity.net_id) is entity
            and entity.team_id == team_id
            and entity.health_points > 0.0
            and entity.is_manned
        ):
            return True
    return any(
        entity.unit_type == REPAIR_PAD_UNIT_TYPE
        and entity.team_id == team_id
        and entity.health_points > 0.0
        for entity in server.entities.get_all()
    )


def _choose_rotation_map(server: Any) -> str | None:
    rotation = tuple(getattr(server.cfg.game, "map_rotation", ()))
    available = [
        map_name
        for map_name in rotation
        if MAP_NAME_PATTERN.fullmatch(map_name) is not None
        and app.verify_map_land_exists(server, map_name)
    ]
    if not available:
        return None
    alternatives = [
        map_name for map_name in available if map_name != server.current_map_name
    ]
    return random.choice(alternatives or available)


def _queue_automatic_map_change(
    server: Any,
    map_name: str,
    reason: str,
) -> bool:
    if getattr(server, "map_change_transition", None) is not None:
        return False
    try:
        server.admin_command_queue.put_nowait(
            MapChangeRequest(None, map_name, reason=reason)
        )
    except queue.Full:
        return False
    print(f"[admin] automatic map change queued map={map_name} reason={reason!r}")
    return True


def check_win_condition(server: Any) -> None:
    """Announce an elimination win and queue a random configured map."""
    if getattr(server, "map_change_transition", None) is not None:
        return
    state = getattr(server, "match_state", None)
    if state is None:
        state = MatchState()
        server.match_state = state

    if state.winner_team is not None:
        if state.pending_map is not None and _queue_automatic_map_change(
            server,
            state.pending_map,
            f"{TEAM_NAMES[state.winner_team]} team victory",
        ):
            state.pending_map = None
        return

    resources = {
        team_id: _team_resources(server, team_id)
        for team_id in COMPETING_TEAM_IDS
    }
    if not state.armed:
        if all(resources.values()):
            state.armed = True
            print("[match] win condition armed from Red and Blue survival resources")
        return

    eliminated = [team_id for team_id in COMPETING_TEAM_IDS if not resources[team_id]]
    if len(eliminated) != 1:
        return
    losing_team = eliminated[0]
    winning_team = 2 if losing_team == 1 else 1
    if not resources[winning_team]:
        return

    next_map = _choose_rotation_map(server)
    state.winner_team = winning_team
    state.pending_map = next_map
    winner_name = TEAM_NAMES[winning_team]
    loser_name = TEAM_NAMES[losing_team]
    if next_map is None:
        _broadcast_system_message(
            server,
            f"{winner_name} team wins! No valid rotation map is available.",
        )
        print(
            f"[match] winner={winner_name} loser={loser_name} "
            "map_change=unavailable"
        )
        return

    _broadcast_system_message(
        server,
        f"{winner_name} team wins! Next map: {next_map}.",
    )
    print(f"[match] winner={winner_name} loser={loser_name} next_map={next_map}")
    if _queue_automatic_map_change(
        server,
        next_map,
        f"{winner_name} team victory",
    ):
        state.pending_map = None


def _start_map_change(
    server: Any,
    request: MapChangeRequest,
    now: float,
) -> bool:
    map_name = request.map_name
    land_path = app.map_land_path(server, map_name)
    state_path = app.map_state_path(server, map_name)
    previous_land_revision = int(getattr(server.land, "revision", 0))
    try:
        state_text = (
            state_path.read_text(encoding="utf-8") if state_path.is_file() else None
        )
        replacement_land = LandMap()
        replacement_land.load(land_path)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"[admin] map change rejected map={map_name}: {error}")
        _respond_to_map_request(request, f"Could not load map {map_name}.")
        return False
    if not replacement_land.loaded:
        _respond_to_map_request(request, f"Could not load map {map_name}.")
        return False
    # PhysicsWorldHost uses the monotonically increasing land revision to
    # decide when to rebuild its native terrain, even when the LandMap object
    # itself is replaced.
    replacement_land.revision = max(
        replacement_land.revision,
        previous_land_revision + 1,
    )
    server.map_change_transition = MapChangeTransition(
        request=request,
        replacement_land=replacement_land,
        state_text=state_text,
        next_entity_at=now,
    )
    _broadcast_system_message(
        server,
        f"Map change to {map_name} started; clearing the current world.",
    )
    print(
        f"[admin] map change started map={map_name} "
        f"entities={len(server.entities.get_all())}"
    )
    return True


def _owner_sessions_by_entity(server: Any) -> dict[int, Any]:
    owners: dict[int, Any] = {}
    for session in server.sessions:
        entity = getattr(session, "entity", None)
        if entity is not None and server.entities.get_entity(entity.net_id) is entity:
            owners[entity.net_id] = session
    return owners


def _remove_transition_entity(server: Any, entity: Any, category: str) -> bool:
    packet = server.entities.remove_entity(entity.net_id)
    if packet is None:
        return False
    app.broadcast(server, packet)
    print(
        f"[admin] map teardown removed category={category} "
        f"entity={entity.net_id} unit={entity.unit_type}"
    )
    return True


def _advance_map_change(server: Any, now: float) -> None:
    transition = getattr(server, "map_change_transition", None)
    if transition is None:
        return
    entities = sorted(server.entities.get_all(), key=lambda entity: entity.net_id)
    if not entities:
        _complete_map_change(server, transition)
        return
    if now < transition.next_entity_at:
        return

    owners = _owner_sessions_by_entity(server)
    repair_pads = [
        entity for entity in entities if entity.unit_type == REPAIR_PAD_UNIT_TYPE
    ]
    living_players = [
        entity
        for entity in entities
        if entity.net_id in owners
        and float(getattr(owners[entity.net_id], "death_cleanup_at", 0.0) or 0.0)
        <= 0.0
    ]
    dying_players = [
        entity
        for entity in entities
        if entity.net_id in owners
        and float(getattr(owners[entity.net_id], "death_cleanup_at", 0.0) or 0.0)
        > 0.0
    ]
    other_entities = [
        entity
        for entity in entities
        if entity.unit_type != REPAIR_PAD_UNIT_TYPE
        and entity.net_id not in owners
    ]

    acted = False
    if repair_pads:
        acted = _remove_transition_entity(server, repair_pads[0], "repair_pad")
    elif living_players:
        entity = living_players[0]
        entity.set_health_points(0.0)
        acted = app._destroy_authoritative_entity(
            server,
            entity,
            explosion=True,
        )
        if acted:
            print(
                f"[admin] map teardown killed player_entity={entity.net_id} "
                f"unit={entity.unit_type}"
            )
    elif dying_players:
        entity = dying_players[0]
        owner = owners[entity.net_id]
        deadline = float(getattr(owner, "death_cleanup_at", 0.0) or 0.0)
        if now < deadline:
            return
        acted = app._finalize_player_death(server, owner)
        if acted:
            print(
                f"[admin] map teardown removed player_wreck={entity.net_id} "
                f"unit={entity.unit_type}"
            )
    elif other_entities:
        acted = _remove_transition_entity(server, other_entities[0], "world")
    if acted:
        transition.next_entity_at = now + MAP_CHANGE_ENTITY_INTERVAL_SECONDS


def _complete_map_change(server: Any, transition: MapChangeTransition) -> None:
    request = transition.request
    map_name = request.map_name

    for session in list(server.sessions):
        if getattr(session, "entity", None) is not None:
            server.hooks.entity_removed(session, "admin_map_change")
        session.entity = None
        session.construction_ready_at = 0.0
        session.death_cleanup_at = 0.0
        session.death_delete_explosion = False
        session.ground_dock_armed = True
        session.ground_dock_settle_started_at = None
        session.ground_dock_reference_pos = None
        session.ground_dock_reference_rot = None
        session.ground_dock_last_physics_tick = 0

    server.land = transition.replacement_land
    server.current_map_name = map_name
    if transition.state_text is not None:
        MapLoader(server.entities).load_from_string(transition.state_text)
    server.first_map_load = True
    server.map_change_transition = None
    server.match_state = MatchState()
    app.broadcast(server, WorldStatsPacket(map_name=map_name))
    for session in server.sessions:
        if not session.is_logged_in or session.udp_context is None:
            continue
        send = getattr(session.udp_context, "send", None)
        if not callable(send):
            continue
        send(server.entities.get_snapshot_packet(
            sequence_num=app.get_ticks(),
            health=1.0,
            energy=1.0,
            viewer_team=session.team,
        ))
    requester = (
        getattr(request.context.session, "name", "unknown")
        if request.context is not None
        else request.reason
    )
    print(f"[admin] map changed map={map_name} requested_by={requester!r}")
    suffix = (
        ""
        if transition.state_text is not None
        else " (terrain only; no state file)"
    )
    _broadcast_system_message(
        server,
        f"Administrator changed map to {map_name}{suffix}.",
    )


def apply_pending(server: Any, *, now: float | None = None) -> None:
    current_time = time.monotonic() if now is None else now
    if getattr(server, "map_change_transition", None) is not None:
        _advance_map_change(server, current_time)
        if getattr(server, "map_change_transition", None) is not None:
            return

    while True:
        try:
            request = server.admin_command_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(request, MapChangeRequest):
            if _start_map_change(server, request, current_time):
                _advance_map_change(server, current_time)
                if getattr(server, "map_change_transition", None) is not None:
                    return
            continue
        try:
            if request.action == "add":
                bot = server.bots.add(request.name, request.team)
                _send(
                    request.context,
                    f"Added bot {bot.name} to team {bot.team}.",
                )
            else:
                removed = server.bots.remove(str(request.name))
                names = ", ".join(bot.name for bot in removed)
                _send(request.context, f"Removed bot(s): {names}.")
        except ValueError as error:
            _send(request.context, f"Bot command failed: {error}.")
