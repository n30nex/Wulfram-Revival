from __future__ import annotations

from dataclasses import dataclass, field
import random
import time
from typing import Any

from wulfram_server.core.entity import GameEntity
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
    rng: random.Random = field(default_factory=random.Random, repr=False)


class BotManager:
    """Owns bot roster entries, vehicles, and the initial wandering AI."""

    def __init__(self, server: Any):
        self.server = server
        self._bots: list[BotSession] = []
        self._next_default_name = 1

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

    def _spawn_pad(self, team: int) -> GameEntity | None:
        pads = sorted(
            (
                entity
                for entity in self.server.entities.get_all()
                if entity.unit_type == REPAIR_PAD_UNIT_TYPE
            ),
            key=lambda entity: entity.net_id,
        )
        matching = [pad for pad in pads if pad.team_id == team]
        choices = matching or pads
        return choices[0] if choices else None

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
            raise ValueError("the active map has no repair pad for bot spawning")

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
        pad = self._spawn_pad(bot.team)
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
        bot.next_jump_at = now + bot.rng.uniform(4.0, 9.0)
        bot.jump_release_at = None

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

    def step(self, now: float) -> None:
        for bot in tuple(self._bots):
            if bot.entity is None:
                if now >= bot.construction_ready_at:
                    self._spawn(bot, now)
                continue

            if not bot.entity.is_manned:
                continue

            entity = bot.entity
            changed = False
            if bot.jump_release_at is not None and now >= bot.jump_release_at:
                entity.actions[4] = 0.0
                bot.jump_release_at = None
                changed = True

            if now >= bot.next_decision_at:
                # Keep the hover jets raised, drive forward, and occasionally
                # change steering direction. This is intentionally wandering,
                # not pathfinding.
                entity.actions[2] = bot.rng.uniform(0.55, 1.0)
                entity.actions[1] = bot.rng.uniform(-0.65, 0.65)
                entity.actions[3] = bot.rng.uniform(-0.2, 0.2)
                entity.actions[5] = 1.0
                bot.next_decision_at = now + bot.rng.uniform(1.5, 3.5)
                changed = True

            if bot.jump_release_at is None and now >= bot.next_jump_at:
                entity.actions[4] = 1.0
                bot.jump_release_at = now + 0.12
                bot.next_jump_at = now + bot.rng.uniform(5.0, 12.0)
                changed = True

            if changed:
                bot.physics_input_sequence += 1
                entity.record_input_sample(sequence=bot.physics_input_sequence)
