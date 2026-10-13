from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import threading
import time
from typing import Any

from wulfram_server.core.entity import GameEntity
from wulfram_server.core.combat import AUTOCANNON_ACTION, PULSE_ACTION, REPAIR_ACTION, PIERCER_ACTION, _forward
from wulfram_server.vehicles import LOADOUTS, apply_loadout
from wulfram_server.matches import PlayerScore
from wulfram_server.network.packets import (
    AddToRosterPacket,
    BirthNoticePacket,
    DeathNoticePacket,
    RemoveFromRosterPacket,
)


REPAIR_PAD_UNIT_TYPE = 27
BOT_NAME_LIMIT = 24
BOT_SPAWN_HEIGHT_OFFSET = 15.0
BOT_TARGET_UNIT_TYPES = frozenset((0, 1, 25, 26, 27, 29, 30))
BOT_ROLES = ("assault", "flank", "guard", "assault", "interceptor", "flank", "guard", "assault")


@dataclass
class BotSession:
    """A server-owned player which deliberately has no network transport."""

    server: Any
    player_id: int
    name: str
    team: int
    vehicle_loadout: str = "tank"
    resupplying: bool = False
    score: PlayerScore = field(default_factory=PlayerScore)
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
    tactical_slot: int = 0
    role: str = "assault"
    order: str = "assault"
    goal: tuple[float, float] | None = None
    objective_id: int = 0
    target_id: int = 0
    approach_done: bool = False
    next_plan_at: float = 0.0
    wants_move: bool = False
    rng: random.Random = field(default_factory=random.Random, repr=False)


class BotManager:
    """Owns CPU tanks which steer and fight through ordinary player controls."""

    def __init__(self, server: Any):
        self.server = server
        self._bots: list[BotSession] = []
        self._next_default_name = 1
        # Bot respawns and human UDP requests share the same pad reservation.
        self.spawn_lock = threading.Lock()
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

    def _spawn_pad(self, team: int, *, require_free: bool = False,
                   preferred_id: int | None = None, preferred_index: int = 0) -> GameEntity | None:
        entities = self.server.entities.get_all()
        preferred = self.server.entities.get_entity(preferred_id) if preferred_id is not None else None
        pads = sorted(
            (
                entity
                for entity in entities
                if entity.unit_type == REPAIR_PAD_UNIT_TYPE
                and entity.team_id == team
                and entity.health_points > 0.0
            ),
            key=lambda entity: (math.dist(entity.pos, preferred.pos) if preferred else 0, entity.net_id),
        )
        if pads:
            split = preferred_index % len(pads)
            pads = pads[split:] + pads[:split]
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

    def add(self, name: str | None = None, team: int | None = None, loadout: str | None = None) -> BotSession:
        if team is None:
            team = self._choose_team()
        if team not in (1, 2):
            raise ValueError("bot team must be 1 or 2")
        if loadout is None:
            team_index = sum(bot.team == team for bot in self._bots)
            loadout = ("tank", "tank", "scout", "tank", "siege", "tank", "scout", "tank")[team_index % 8]
        if loadout not in LOADOUTS:
            raise ValueError("unknown bot loadout")
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
            vehicle_loadout=loadout,
            rng=random.Random(player_id),
        )
        occupied = {other.tactical_slot for other in self._bots if other.team == team}
        bot.tactical_slot = next(slot for slot in range(len(occupied)+1) if slot not in occupied)
        bot.role = BOT_ROLES[bot.tactical_slot % len(BOT_ROLES)]
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
        with self.spawn_lock:
            return self._spawn_locked(bot, now)

    def _spawn_locked(self, bot: BotSession, now: float) -> bool:
        if getattr(self.server, "map_change_transition", None) is not None:
            return False
        # Try every friendly pad before queuing an overlapping respawn.
        pad = self._spawn_pad(bot.team, require_free=True, preferred_index=bot.tactical_slot)
        if pad is None:
            return False

        spawn_pos = (
            pad.pos[0],
            pad.pos[1],
            pad.pos[2] + BOT_SPAWN_HEIGHT_OFFSET,
        )
        entity = self.server.entities.create_entity(
            unit_type=LOADOUTS[bot.vehicle_loadout][0],
            team_id=bot.team,
            pos=spawn_pos,
            register=False,
        )
        entity.rot = pad.rot
        entity.is_manned = True
        apply_loadout(entity, bot.vehicle_loadout)
        bot.resupplying = False
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
        bot.next_plan_at = 0
        bot.objective_id = 0
        bot.approach_done = False
        bot.goal = None

        from wulfram_server import application as app

        app._note_entity_spawn(bot, entity, "bot_respawn")
        self.server.entities.register_entity(entity)
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

    def _plan(self, bot: BotSession, now: float, targets: list[GameEntity]) -> None:
        """Persistent jobs, shared team radar, and distinct terrain-safe approaches."""
        entity = bot.entity
        friendly = [unit for unit in self.server.entities.get_all()
                    if unit.team_id == bot.team and unit.unit_type in (25,26,27,29,30)
                    and unit.health_points > 0]
        pads = [unit for unit in friendly if unit.unit_type == REPAIR_PAD_UNIT_TYPE]
        homes = pads or friendly
        home = (tuple(sum(unit.pos[i] for unit in homes)/len(homes) for i in (0,1))
                if homes else (bot.spawn_position or entity.pos)[:2])
        structures = sorted((unit for unit in targets if unit.unit_type not in (0,1)),
                            key=lambda unit: (unit.unit_type != 27,unit.net_id))
        vehicles = [unit for unit in targets if unit.unit_type in (0,1)]
        threats = [unit for unit in vehicles
                   if any(math.dist(unit.pos[:2],base.pos[:2]) < 850 for base in homes)]
        slot = bot.tactical_slot
        bot.order = bot.role
        if bot.role in ("guard", "interceptor") and threats:
            # Different defenders can cover different incursions.
            threats.sort(key=lambda unit: (math.dist(unit.pos[:2],home),unit.net_id))
            target = threats[(slot//4) % len(threats)]
            destination = target.pos[:2]
            bot.order = "intercept"
        elif bot.role == "guard" and friendly:
            anchor = homes[(slot//4) % len(homes)]
            # Patrol outside the spawn pads, with two stops and staggered phases.
            angle = (slot//4)*math.pi/2 + (int(now/18 + slot) % 2)*.8
            destination = (anchor.pos[0]+280*math.cos(angle),anchor.pos[1]+280*math.sin(angle))
            target = None
        else:
            target = (structures[(slot//2) % len(structures)] if structures else
                      min(vehicles,key=lambda unit: math.dist(entity.pos,unit.pos),default=None))
            if target is None:
                bot.goal = None
                bot.order = "hold"
                bot.next_plan_at = now+2
                return
            if target.net_id != bot.objective_id:
                bot.objective_id = target.net_id
                bot.approach_done = False
            if target.unit_type in (0,1):
                destination = target.pos[:2]
                bot.order = "intercept"
            else:
                dx,dy = target.pos[0]-home[0],target.pos[1]-home[1]
                length = max(1,math.hypot(dx,dy))
                lane = (-1 if slot%8 == 1 else 1) if bot.role == "flank" else (-1,0,1)[slot%3]
                offset = min(length*.3,750 if bot.role == "flank" else 350)*lane
                rally = (home[0]+dx*.5-dy/length*offset,home[1]+dy*.5+dx/length*offset)
                if self.navigation is not None:
                    rally = self.navigation.reachable_near(entity.pos,rally)
                if rally is None or math.dist(entity.pos[:2],rally) < 120:
                    bot.approach_done = True
                # Do not turn back to a staging point after already passing it.
                if ((entity.pos[0]-home[0])*dx+(entity.pos[1]-home[1])*dy)/length > length*.65:
                    bot.approach_done = True
                angle = slot*2.3999632297
                destination = ((target.pos[0]+130*math.cos(angle),target.pos[1]+130*math.sin(angle))
                               if bot.approach_done else rally)
        if bot.order == "intercept":
            # Share bounded, coarse route fields instead of rebuilding one for
            # every moving target on every steering tick. Aim still uses live pose.
            destination = tuple(math.floor(value/200)*200+100 for value in destination)
        bot.goal = (self.navigation.reachable_near(entity.pos,destination)
                    if self.navigation is not None else destination)
        bot.next_plan_at = now+2+bot.rng.random()*.6

    def _decide(self, bot: BotSession, now: float) -> None:
        entity = bot.entity
        if entity is None:
            return
        all_entities = self.server.entities.get_all()
        targets = [
            target for target in all_entities
            if target.team_id in (1, 2) and target.team_id != bot.team
            and target.unit_type in BOT_TARGET_UNIT_TYPES
            and target.health_points > 0.0
        ]
        combat = self.server.packet_cfg.combat
        if entity.energy < 0.18 or entity.health < 0.3:
            bot.resupplying = True
        service_targets = []
        if bot.resupplying:
            if entity.health >= 0.9 and entity.energy >= 0.85:
                bot.resupplying = False
            else:
                desired_pad = 27 if entity.health < 0.9 else 26
                service_targets = [item for item in all_entities if item.unit_type == desired_pad
                                   and item.team_id == bot.team and item.health_points > 0]
        healing_targets = []
        if entity.unit_type == 1 and not bot.resupplying:
            healing_targets = [item for item in all_entities
                               if item is not entity and item.team_id == bot.team and 0 < item.health < 0.85
                               and item.unit_type in (0, 1, 25, 26, 27, 29, 30)
                               and math.dist(item.pos, entity.pos) <= 600]
        support = min(service_targets or healing_targets,
                      key=lambda unit: math.dist(entity.pos,unit.pos),default=None)
        if support is not None:
            bot.order = 'resupply' if service_targets else 'support'
            bot.goal = (support.pos[:2] if service_targets else
                        tuple(math.floor(value/200)*200+100 for value in support.pos[:2]))
        else:
            if bot.order in ('resupply','support'):
                bot.next_plan_at = 0
            if now >= bot.next_plan_at:
                self._plan(bot,now,targets)
        if bot.vehicle_loadout == "siege":
            nearby = [item for item in targets if item.unit_type in (0, 1) and math.dist(item.pos, entity.pos) < 250]
            bases = [item for item in targets if item.unit_type in (25, 26, 27, 29, 30)]
            targets = nearby or bases or targets
        entity.actions[AUTOCANNON_ACTION] = 0.0
        previous_pulse = entity.actions.get(PULSE_ACTION, 0.0)
        entity.actions[PULSE_ACTION] = 0.0
        entity.actions[REPAIR_ACTION] = 0.0
        entity.actions[PIERCER_ACTION] = 0.0
        entity.actions[3] = 0.0
        entity.actions[5] = 1.0
        entity.actions[6] = 0.0
        combat = self.server.packet_cfg.combat
        forward = _forward(entity.rot)
        nearby = [unit for unit in targets if math.dist(entity.pos,unit.pos) <= min(450,combat.autocannon_range)]
        if support is not None:
            nearby = ([support] if healing_targets and math.dist(entity.pos,support.pos) <= combat.repair_range else [])
        nearby.sort(key=lambda unit: (unit.unit_type not in (0,1),
                                    math.dist(entity.pos,unit.pos)*(0.75 if unit.net_id == bot.target_id else 1)))
        target = None
        origin = tuple(entity.pos[index]+forward[index]*4.5 for index in range(3))
        for candidate in nearby[:3]:
            hit = self.server.physics.trace_segment(origin,candidate.pos,ignored_entity=entity.net_id)
            if hit['hit'] and int(hit['entity_id']) == candidate.net_id:
                target = candidate
                break
        visible = target is not None
        bot.engaging = visible
        bot.target_id = target.net_id if target is not None else 0
        dx,dy,dz = ((target.pos[index]-entity.pos[index] for index in range(3))
                    if visible else (0.,0.,0.))
        distance = math.sqrt(dx*dx+dy*dy+dz*dz)
        waypoint = bot.goal
        if not visible and waypoint is not None and self.navigation is not None:
            waypoint = self.navigation.waypoint(entity.pos,[waypoint])
        # Reaching an intermediate cell is not arriving at the tactical goal.
        arrival = 15 if service_targets else 35
        wants_move = bot.goal is not None and math.dist(entity.pos[:2],bot.goal) > arrival
        routed = waypoint is not None and wants_move
        heading = (dx,dy) if visible else ((waypoint[0]-entity.pos[0],waypoint[1]-entity.pos[1])
                                           if waypoint is not None else (math.cos(entity.rot[2]),math.sin(entity.rot[2])))
        speed = .85
        if not visible and routed:
            length = math.hypot(*heading)
            speed = min(speed,max(.25,length/90))
            if length > 1:
                vx,vy = heading[0]/length,heading[1]/length
                for other in self.server.entities.get_all():
                    if other is entity or other.unit_type not in (0,1) or other.health_points <= 0: continue
                    ax,ay = entity.pos[0]-other.pos[0],entity.pos[1]-other.pos[1]
                    apart = math.hypot(ax,ay)
                    if .01 < apart < 65:
                        ahead = -(vx*ax+vy*ay)/apart
                        if ahead > .7:
                            speed = min(speed,max(.15,.85*(apart-15)/50))
                            side = 1 if bot.tactical_slot%2 else -1
                            vx,vy = vx-vy*.4*side,vy+vx*.4*side
                        weight = 1.2*(65-apart)/65
                        vx += weight*ax/apart; vy += weight*ay/apart
                probe = (entity.pos[0]+vx*30,entity.pos[1]+vy*30)
                if self.navigation is None or self.navigation.clear_line(entity.pos,probe): heading = (vx,vy)
        yaw_error = math.remainder(math.atan2(heading[1],heading[0])-entity.rot[2],math.tau)
        # Raw turn channel 1 is negated by current_input_sample. Damp angular
        # velocity so the tank settles on a heading instead of circling it.
        turn = 2.0 * yaw_error - 1.5 * entity.spin[2]
        entity.actions[1] = -max(-1.0, min(1.0, turn))
        entity.actions[6] = (max(-0.5,min(0.5,-math.atan2(dz,math.hypot(dx,dy))/1.4137167))
                             if visible else 0.0)
        stopping_distance = min(180.0, combat.autocannon_range * 0.5)
        entity.actions[2] = speed if routed and not visible and abs(yaw_error) < 1.0 else 0.0
        bot.wants_move = bool(wants_move and not visible)
        # Keep 80 decision timers from collapsing onto the same physics frame.
        bot.next_decision_at = now + bot.rng.uniform(.18,.22)
        if now >= bot.progress_check_at:
            if (bot.progress_position is not None and bot.wants_move
                    and math.dist(bot.progress_position[:2],entity.pos[:2]) < 8):
                bot.recovery_until = now+1.2
                bot.next_jump_at = now+.6
            bot.progress_position = entity.pos
            bot.progress_check_at = now+3
        if now < bot.recovery_until:
            entity.actions[2] = -.65
            entity.actions[3] = .65 if bot.tactical_slot%2 else -.65
            return
        if service_targets:
            return
        if healing_targets:
            if visible and abs(yaw_error) < math.radians(10):
                entity.actions[REPAIR_ACTION] = 1.0
            return
        if not visible or distance <= 1.0e-6 or distance > combat.autocannon_range:
            return

        forward = _forward(entity.rot)
        alignment = sum(forward[index] * (target.pos[index] - entity.pos[index]) for index in range(3)) / distance
        if alignment < math.cos(math.radians(combat.autocannon_autoaim_degrees)):
            return
        if distance <= stopping_distance:
            entity.actions[2] = 0.0
        # Existing combat applies normal cooldowns, fuel cost, scatter and damage.
        entity.actions[AUTOCANNON_ACTION] = 1.0
        if bot.vehicle_loadout == "siege" and alignment > math.cos(math.radians(4.0)):
            entity.actions[PIERCER_ACTION] = 1.0
        if entity.unit_type == 0 and not previous_pulse and distance < 250.0 and alignment > math.cos(math.radians(4.0)):
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
