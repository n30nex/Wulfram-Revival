from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import time
from typing import Any

from wulfram_server.core.entity import GameEntity
from wulfram_server.core.combat import AUTOCANNON_ACTION, PULSE_ACTION, _forward
from wulfram_server.network.packets import (
    AddToRosterPacket,
    BirthNoticePacket,
    DeathNoticePacket,
    RemoveFromRosterPacket,
)


REPAIR_PAD_UNIT_TYPE = 27
BOT_VEHICLE_UNIT_TYPE = 0
BOT_NAME_LIMIT = 24
BOT_SPAWN_HEIGHT_OFFSET = 15.0
BOT_TARGET_UNIT_TYPES = frozenset((0, 1, 25, 26, 27, 29, 30))


@dataclass
class BotSession:
    """A server-owned player which deliberately has no network transport."""

    server: Any
    player_id: int
    name: str
    team: int
    entity: GameEntity | None = None
    is_logged_in: bool = True
    is_ready_for_updates: bool = True
    is_admin: bool = False
    is_bot: bool = True
    address: tuple[str, int] = ("bot", 0)
    udp_addr: None = None
    tcp_sock: None = None
    udp_context: None = None
    construction_ready_at: float = 0.0
    death_cleanup_at: float = 0.0
    death_delete_explosion: bool = False
    carried_cargo_item_id: int | None = None
    carried_cargo_team_id: int = 0
    physics_input_sequence: int = 0
    ground_dock_armed: bool = True
    ground_dock_settle_started_at: float | None = None
    ground_dock_reference_pos: tuple[float, float, float] | None = None
    ground_dock_reference_rot: tuple[float, float, float] | None = None
    ground_dock_last_physics_tick: int = 0
    next_decision_at: float = 0.0
    next_jump_at: float = 0.0
    jump_release_at: float | None = None
    progress_position: tuple[float,float,float] | None = None
    progress_check_at: float = 0.0
    recovery_until: float = 0.0
    spawn_position: tuple[float,float,float] | None = None
    furthest_travel: float = 0.0
    engaging: bool = False
    rng: random.Random = field(default_factory=random.Random, repr=False)


class BotManager:
    """Owns CPU tanks which steer and fight through ordinary player controls."""

    def __init__(self, server: Any):
        self.server = server
        self._bots: list[BotSession] = []
        self._next_default_name = 1
        self.navigation = None
        self._navigation_revision = None

    def prepare_navigation(self):
        land = getattr(self.server,'land',None)
        if land is None or not land.loaded: return
        revision = (land.identity,land.revision)
        if revision != self._navigation_revision:
            from wulfram_server.navigation import TerrainRoutes
            self.navigation = TerrainRoutes(land)
            self._navigation_revision = revision
        for team in (1,2):
            self.navigation.field(self._route_goals(team))

    def _route_goals(self, team):
        bases = [entity for entity in self.server.entities.get_all()
                 if entity.unit_type in (25,26,27,29,30) and entity.team_id == 3-team
                 and entity.health_points > 0]
        pads = [entity for entity in bases if entity.unit_type == REPAIR_PAD_UNIT_TYPE]
        return [entity.pos for entity in (pads or bases)]

    @property
    def bots(self) -> tuple[BotSession, ...]:
        return tuple(self._bots)

    def _default_name(self) -> str:
        existing = {
            str(getattr(session, "name", "")).casefold()
            for session in self.server.sessions
            if bool(getattr(session, "is_logged_in", False))
        }
        while True:
            name = f"Bot{self._next_default_name}"
            self._next_default_name += 1
            if name.casefold() not in existing:
                return name

    def _choose_team(self) -> int:
        counts = {1: 0, 2: 0}
        for session in self.server.sessions:
            team = int(getattr(session, "team", 0) or 0)
            if bool(getattr(session, "is_logged_in", False)) and team in counts:
                counts[team] += 1
        return 1 if counts[1] <= counts[2] else 2

    def _spawn_pad(self, team: int, *, require_free: bool = False) -> GameEntity | None:
        entities = self.server.entities.get_all()
        pads = sorted(
            (
                entity
                for entity in entities
                if entity.unit_type == REPAIR_PAD_UNIT_TYPE
                and entity.team_id == team
                and entity.health_points > 0.0
            ),
            key=lambda entity: entity.net_id,
        )
        for pad in pads:
            spawn_pos = (pad.pos[0], pad.pos[1], pad.pos[2] + BOT_SPAWN_HEIGHT_OFFSET)
            if not require_free or not any(
                other.unit_type in (0, 1) and other.health_points > 0.0
                and math.dist(other.pos, spawn_pos) < 20.0
                for other in entities
            ):
                return pad
        return None

    def can_spawn(self, team: int) -> bool:
        return self._spawn_pad(team) is not None

    def add(self, name: str | None = None, team: int | None = None) -> BotSession:
        if team is None:
            team = self._choose_team()
        if team not in (1, 2):
            raise ValueError("bot team must be 1 or 2")
        if not name:
            name = self._default_name()
        if len(name) > BOT_NAME_LIMIT:
            raise ValueError(f"bot names may be at most {BOT_NAME_LIMIT} characters")
        if any(
            str(getattr(session, "name", "")).casefold() == name.casefold()
            for session in self.server.sessions
            if bool(getattr(session, "is_logged_in", False))
        ):
            raise ValueError(f"the name {name!r} is already in use")
        game_config = getattr(getattr(self.server, "cfg", None), "game", None)
        limit = int(getattr(game_config, "player_limit", 20))
        # A connected client which is still authenticating already occupies a
        # server slot, matching the TCP accept path's limit accounting.
        if len(self.server.sessions) >= limit:
            raise ValueError("the server player limit has been reached")
        if not self.can_spawn(team):
            raise ValueError("the active map has no living repair pad for this bot's team")

        player_id = self.server.get_next_player_id()
        bot = BotSession(
            server=self.server,
            player_id=player_id,
            name=name,
            team=team,
            rng=random.Random(player_id),
        )
        self._bots.append(bot)
        self.server.sessions.append(bot)
        self.server.hooks.initialize_session(bot)

        from wulfram_server import application as app

        app.broadcast(self.server, AddToRosterPacket(
            account_id=bot.player_id,
            team=bot.team,
            name=bot.name,
            nametag=self.server.cfg.player.nametag,
        ))
        self._spawn(bot, time.monotonic())
        print(f"[bot] added player={bot.player_id} name={bot.name!r} team={bot.team}")
        return bot

    def _spawn(self, bot: BotSession, now: float) -> bool:
        if getattr(self.server, "map_change_transition", None) is not None:
            return False
        # Try every friendly pad before queuing an overlapping respawn.
        pad = self._spawn_pad(bot.team, require_free=True)
        if pad is None:
            return False

        spawn_pos = (
            pad.pos[0],
            pad.pos[1],
            pad.pos[2] + BOT_SPAWN_HEIGHT_OFFSET,
        )
        entity = self.server.entities.create_entity(
            unit_type=BOT_VEHICLE_UNIT_TYPE,
            team_id=bot.team,
            pos=spawn_pos,
        )
        entity.rot = pad.rot
        entity.is_manned = True
        entity.weapon_table_id = BOT_VEHICLE_UNIT_TYPE
        bot.entity = entity
        bot.construction_ready_at = 0.0
        bot.next_decision_at = now
        bot.next_jump_at = math.inf
        bot.jump_release_at = None
        bot.spawn_position = spawn_pos
        bot.progress_position = spawn_pos
        bot.progress_check_at = now+3
        bot.recovery_until = 0
        bot.engaging = False

        from wulfram_server import application as app

        app._note_entity_spawn(bot, entity, "bot_respawn")
        app.broadcast(self.server, BirthNoticePacket(
            player_id=bot.player_id,
            entity_id=entity.net_id,
        ))
        return True

    def remove(self, name: str) -> list[BotSession]:
        if name.casefold() == "all":
            targets = list(self._bots)
        else:
            targets = [bot for bot in self._bots if bot.name.casefold() == name.casefold()]
        if not targets:
            raise ValueError(f"no bot named {name!r}")

        from wulfram_server import application as app

        for bot in targets:
            if bot.entity is not None:
                app.broadcast(self.server, DeathNoticePacket(bot.player_id))
                self.server.hooks.entity_removed(bot, "bot_removed")
                packet = self.server.entities.remove_entity(bot.entity.net_id)
                if packet is not None:
                    app.broadcast(self.server, packet)
                bot.entity = None
            app.broadcast(self.server, RemoveFromRosterPacket(bot.player_id))
            bot.is_logged_in = False
            self.server.hooks.cleanup_session(bot)
            self.server.sessions.remove(bot)
            self._bots.remove(bot)
            print(f"[bot] removed player={bot.player_id} name={bot.name!r}")
        return targets

    def _decide(self, bot: BotSession, now: float) -> None:
        entity = bot.entity
        if entity is None:
            return
        targets = [
            target for target in self.server.entities.get_all()
            if target.team_id in (1, 2) and target.team_id != bot.team
            and target.unit_type in BOT_TARGET_UNIT_TYPES
            and target.health_points > 0.0
        ]
        target = min(
            targets,
            key=lambda other: (math.dist(entity.pos, other.pos), other.net_id),
            default=None,
        )
        entity.actions[AUTOCANNON_ACTION] = 0.0
        previous_pulse = entity.actions.get(PULSE_ACTION, 0.0)
        entity.actions[PULSE_ACTION] = 0.0
        entity.actions[3] = 0.0
        entity.actions[5] = 1.0
        entity.actions[6] = 0.0
        if target is None:
            entity.actions[2] = bot.rng.uniform(0.55, 1.0)
            entity.actions[1] = bot.rng.uniform(-0.65, 0.65)
            bot.next_decision_at = now + bot.rng.uniform(1.5, 3.5)
            return

        dx, dy, dz = (target.pos[index] - entity.pos[index] for index in range(3))
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)
        combat = self.server.packet_cfg.combat
        forward = _forward(entity.rot)
        visible = False
        if distance <= min(450.0,combat.autocannon_range):
            origin = tuple(entity.pos[index]+forward[index]*4.5 for index in range(3))
            hit = self.server.physics.trace_segment(origin,target.pos,ignored_entity=entity.net_id)
            visible = bool(hit['hit']) and int(hit['entity_id']) == target.net_id
        bot.engaging = visible
        heading = (dx,dy)
        routed = True
        if not visible and self.navigation is not None:
            waypoint = self.navigation.waypoint(entity.pos,self._route_goals(bot.team))
            routed = waypoint is not None
            if waypoint is not None:
                heading = (waypoint[0]-entity.pos[0],waypoint[1]-entity.pos[1])
                length = math.hypot(*heading)
                if length > 1:
                    vx,vy = heading[0]/length,heading[1]/length
                    for other in self.server.entities.get_all():
                        if other is entity or other.unit_type not in (0,1) or other.health_points <= 0: continue
                        ax,ay = entity.pos[0]-other.pos[0],entity.pos[1]-other.pos[1]
                        apart = math.hypot(ax,ay)
                        if .01 < apart < 28:
                            weight = .7*(28-apart)/28
                            vx += weight*ax/apart; vy += weight*ay/apart
                    probe = (entity.pos[0]+vx*30,entity.pos[1]+vy*30)
                    if self.navigation.clear_line(entity.pos,probe): heading = (vx,vy)
        yaw_error = math.remainder(math.atan2(heading[1],heading[0])-entity.rot[2],math.tau)
        # Raw turn channel 1 is negated by current_input_sample. Damp angular
        # velocity so the tank settles on a heading instead of circling it.
        turn = 2.0 * yaw_error - 1.5 * entity.spin[2]
        entity.actions[1] = -max(-1.0, min(1.0, turn))
        entity.actions[6] = (max(-0.5,min(0.5,-math.atan2(dz,math.hypot(dx,dy))/1.4137167))
                             if visible else 0.0)
        stopping_distance = min(180.0, combat.autocannon_range * 0.5)
        entity.actions[2] = 0.85 if routed and not visible and abs(yaw_error) < 1.0 else 0.0
        bot.next_decision_at = now + 0.2
        if now >= bot.progress_check_at:
            if (bot.progress_position is not None and entity.actions[2] > .2
                    and math.dist(bot.progress_position[:2],entity.pos[:2]) < 8):
                bot.recovery_until = now+1.2
                bot.next_jump_at = now+.6
            bot.progress_position = entity.pos
            bot.progress_check_at = now+3
        if now < bot.recovery_until:
            entity.actions[2] = -.65
            entity.actions[3] = .65 if bot.player_id%2 else -.65
            return
        if distance <= 1.0e-6 or distance > combat.autocannon_range:
            return

        forward = _forward(entity.rot)
        alignment = sum(forward[index] * (target.pos[index] - entity.pos[index]) for index in range(3)) / distance
        if alignment < math.cos(math.radians(combat.autocannon_autoaim_degrees)):
            return
        origin = tuple(entity.pos[index] + forward[index] * 4.5 for index in range(3))
        hit = self.server.physics.trace_segment(origin, target.pos, ignored_entity=entity.net_id)
        if not hit["hit"] or int(hit["entity_id"]) != target.net_id:
            return
        if distance <= stopping_distance:
            entity.actions[2] = 0.0
        # Existing combat applies normal cooldowns, fuel cost, scatter and damage.
        entity.actions[AUTOCANNON_ACTION] = 1.0
        if not previous_pulse and distance < 250.0 and alignment > math.cos(math.radians(4.0)):
            entity.actions[PULSE_ACTION] = 1.0

    def step(self, now: float) -> None:
        if getattr(self.server, "map_change_transition", None) is not None:
            return
        self.prepare_navigation()
        for bot in tuple(self._bots):
            if bot.entity is None:
                if now >= bot.construction_ready_at:
                    self._spawn(bot, now)
                continue

            if not bot.entity.is_manned:
                continue

            entity = bot.entity
            if bot.spawn_position is not None:
                bot.furthest_travel = max(bot.furthest_travel,math.dist(entity.pos[:2],bot.spawn_position[:2]))
            changed = False
            if bot.jump_release_at is not None and now >= bot.jump_release_at:
                entity.actions[4] = 0.0
                bot.jump_release_at = None
                changed = True

            if now >= bot.next_decision_at:
                self._decide(bot, now)
                changed = True

            if bot.jump_release_at is None and now >= bot.next_jump_at:
                entity.actions[4] = 1.0
                bot.jump_release_at = now + 0.12
                bot.next_jump_at = math.inf
                changed = True

            if changed:
                bot.physics_input_sequence += 1
                entity.record_input_sample(sequence=bot.physics_input_sequence)
