from __future__ import annotations

from dataclasses import dataclass
import math
import random

from wulfram_server.core.entity import GameEntity, NEUTRAL_TEAM_ID, UpdateMask


AUTOCANNON_ACTION = 8
PULSE_ACTION = 12
REPAIR_ACTION = 9
PIERCER_ACTION = 13
FLAK_SHELL_UNIT_TYPE = 5
PULSE_UNIT_TYPE = 6
TANK_UNIT_TYPE = 0
FLAK_TURRET_UNIT_TYPE = 29
GUN_TURRET_UNIT_TYPE = 30
PLAYER_VEHICLE_UNIT_TYPES = frozenset({0, 1})
GUN_TURRET_MUZZLE_OFFSET = 6.5

# Named `missile_pos` attachment points recovered from the full Wulfram II
# Tank models.  The client autocannon path explicitly uses the separate `gun`
# attachment, while spawned projectiles use this mount.  The executable maps
# Team 1 to tank_2 and Team 2 to tank_1.
TANK_PULSE_MUZZLE_LOCAL_BY_TEAM = {
    1: (-0.5304718, 2.9183197, 1.0609436),
    2: (-0.6392670, 0.2301331, 1.3495941),
}


@dataclass(frozen=True, slots=True)
class Destruction:
    entity_id: int
    explosion: bool = True
    killer_player_id: int = 0


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(v, scalar):
    return (v[0] * scalar, v[1] * scalar, v[2] * scalar)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(v):
    return math.sqrt(_dot(v, v))


def _normalize(v, fallback=(1.0, 0.0, 0.0)):
    length = _length(v)
    return _scale(v, 1.0 / length) if length > 1.0e-8 else fallback


def _can_damage(attacker_team: int, victim_team: int, friendly_fire: bool) -> bool:
    """Apply ordinary team damage rules while keeping Neutral protected."""
    if victim_team == NEUTRAL_TEAM_ID:
        return False
    return victim_team != attacker_team or friendly_fire


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _forward(euler):
    # First column of Matrix3d::FromEulerAngles: local +X in world space.
    pitch = euler[1]
    yaw = euler[2]
    cosine_pitch = math.cos(pitch)
    return _normalize((
        math.cos(yaw) * cosine_pitch,
        math.sin(yaw) * cosine_pitch,
        -math.sin(pitch),
    ))


def _transform_local(local, euler):
    """Transform a model-space point with recovered Matrix3d Euler order."""
    angle0, angle1, angle2 = euler
    c0, s0 = math.cos(angle0), math.sin(angle0)
    c1, s1 = math.cos(angle1), math.sin(angle1)
    c2, s2 = math.cos(angle2), math.sin(angle2)
    x, y, z = local
    return (
        x * (c2 * c1) + y * ((c2 * s1) * s0 - s2 * c0)
        + z * (s2 * s0 + (c2 * c0) * s1),
        x * (s2 * c1) + y * ((s1 * s0) * s2 + c2 * c0)
        + z * ((s1 * c0) * s2 - c2 * s0),
        x * -s1 + y * (c1 * s0) + z * (c0 * c1),
    )


def _rotation_toward(direction, roll=0.0):
    direction = _normalize(direction)
    horizontal = math.hypot(direction[0], direction[1])
    return (
        roll,
        math.atan2(-direction[2], horizontal),
        math.atan2(direction[1], direction[0]),
    )


def _closest_point_on_segment(point, start, end):
    segment = _sub(end, start)
    length_squared = _dot(segment, segment)
    if length_squared <= 1.0e-12:
        return start, _length(_sub(point, start))
    amount = max(0.0, min(1.0, _dot(_sub(point, start), segment) / length_squared))
    closest = _add(start, _scale(segment, amount))
    return closest, _length(_sub(point, closest))


class CombatSystem:
    """Authoritative vehicle/base weapons, projectile flight, and lethality.

    Numerical obstruction queries and impulses go through PhysicsWorldHost so
    combat observes the same terrain and registered collision bodies as motion.
    The provisional weapon constants live in PacketConfig.combat and are also
    reflected in the Behavior packet sent to the original client.
    """

    def __init__(self, server):
        self.server = server
        self.cfg = server.packet_cfg.combat
        self._shot_sequence = 0
        self._pulse_positions: dict[int, tuple[float, float, float]] = {}
        self._flak_positions: dict[int, tuple[float, float, float]] = {}
        self._flak_previous_target_distance: dict[int, float] = {}
        self._flak_miss_fuses: dict[int, float] = {}

    def step(self, seconds: float) -> list[Destruction]:
        if seconds <= 0.0 or self.server.physics is None:
            return []
        destroyed: dict[int, Destruction] = {}
        # Cancel every attacker's shield before resolving any incoming shot,
        # regardless of entity iteration order or whether it can afford to fire.
        for entity in self.server.entities.get_all():
            if entity.spawn_protection_remaining > 0:
                attacking = any(entity.actions.get(action, 0) for action in
                                (AUTOCANNON_ACTION, PULSE_ACTION, PIERCER_ACTION))
                entity.spawn_protection_remaining = (0.0 if attacking else
                    max(0.0, entity.spawn_protection_remaining - seconds))
        live_pulse_ids = {
            entity.net_id
            for entity in self.server.entities.get_all()
            if entity.unit_type == PULSE_UNIT_TYPE
        }
        for entity_id in set(self._pulse_positions) - live_pulse_ids:
            self._pulse_positions.pop(entity_id, None)
        live_flak_ids = {
            entity.net_id
            for entity in self.server.entities.get_all()
            if entity.unit_type == FLAK_SHELL_UNIT_TYPE
        }
        for entity_id in set(self._flak_positions) - live_flak_ids:
            self._forget_flak_shell(entity_id)
        self._advance_pulse_shells(seconds, destroyed)
        self._advance_flak_shells(seconds, destroyed)
        for entity in sorted(self.server.entities.get_all(), key=lambda item: item.net_id):
            if entity.net_id in destroyed:
                continue
            if entity.unit_type == TANK_UNIT_TYPE:
                self._advance_tank_weapons(entity, seconds, destroyed)
            elif entity.unit_type == 1:
                self._advance_scout_weapons(entity, seconds, destroyed)
            elif entity.unit_type == GUN_TURRET_UNIT_TYPE:
                self._advance_gun_turret(entity, seconds, destroyed)
            elif entity.unit_type == FLAK_TURRET_UNIT_TYPE:
                self._advance_flak_turret(entity, seconds)
        self._service_pads(seconds)
        return list(destroyed.values())

    def _set_weapon_mask(self, entity: GameEntity, mask: int) -> None:
        if entity.weapon_ready_mask != mask:
            entity.weapon_ready_mask = mask
            entity.mark_dirty(UpdateMask.WEAPON)

    def _autocannon_parameters(self, entity):
        if entity.unit_type == 1:
            return (self.cfg.scout_machinegun_damage, self.cfg.scout_machinegun_fuel_cost,
                    self.cfg.scout_machinegun_refire_seconds, self.cfg.scout_machinegun_range,
                    self.cfg.scout_machinegun_autoaim_degrees)
        return (self.cfg.autocannon_damage, self.cfg.autocannon_fuel_cost,
                self.cfg.autocannon_refire_seconds, self.cfg.autocannon_range,
                self.cfg.autocannon_autoaim_degrees)

    def _advance_scout_weapons(self, scout, seconds, destroyed):
        if not scout.is_manned or scout.health_points <= 0:
            return
        scout.autocannon_cooldown = max(0.0, scout.autocannon_cooldown - seconds)
        previous_charge = scout.repair_charge
        mask, repairing = 0, False
        if scout.actions.get(REPAIR_ACTION, 0) and scout.repair_charge > 0:
            forward = _forward(scout.rot)
            candidates = []
            for target in self.server.entities.get_all():
                if (target is scout or target.team_id != scout.team_id or target.health_points <= 0
                        or target.health_points >= target.max_health or target.unit_type not in (0, 1, 25, 26, 27, 29, 30)):
                    continue
                offset = _sub(target.pos, scout.pos)
                distance = _length(offset)
                if 0.001 < distance <= self.cfg.repair_range and _dot(forward, _scale(offset, 1/distance)) >= math.cos(math.radians(12)):
                    candidates.append((target.health, distance, target.net_id, target))
            target = min(candidates, default=(None, None, None, None))[-1]
            if target is not None:
                hit = self.server.physics.trace_segment(_add(scout.pos, _scale(forward, 4.5)),
                                                       target.pos, ignored_entity=scout.net_id)
                duration = min(seconds, scout.repair_charge * self.cfg.repair_capacity_seconds)
                if (hit["hit"] and int(hit["entity_id"]) == target.net_id
                        and self.server.physics.spend_fuel(scout, self.cfg.repair_fuel_per_second * duration)):
                    restored = min(target.max_health-target.health_points, self.cfg.repair_health_per_second * duration)
                    target.set_health_points(target.health_points + restored)
                    scout.repair_charge = max(0.0, scout.repair_charge - duration / self.cfg.repair_capacity_seconds)
                    self._set_turret_target(scout, target)
                    mask, repairing = 2, True
                    from wulfram_server.matches import record_repair
                    record_repair(self.server, scout.score_owner_id, restored)
        if not repairing:
            scout.repair_charge = min(1.0, scout.repair_charge + seconds / self.cfg.repair_regeneration_seconds)
            if scout.actions.get(AUTOCANNON_ACTION, 0):
                _, cost, interval, _, _ = self._autocannon_parameters(scout)
                mask = 1
                if scout.autocannon_cooldown <= 0 and self.server.physics.spend_fuel(scout, cost):
                    self._fire_autocannon(scout, destroyed)
                    scout.autocannon_cooldown = max(0.0, interval + scout.autocannon_cooldown)
        if abs(previous_charge - scout.repair_charge) > 1.0e-9:
            scout.mark_dirty(UpdateMask.WEAPON)
        self._set_weapon_mask(scout, mask)

    def _service_pads(self, seconds):
        pads = [entity for entity in self.server.entities.get_all()
                if entity.unit_type in (26, 27) and entity.health_points > 0]
        for session in self.server.sessions:
            entity = session.entity
            if entity is None or not entity.is_manned or entity.health_points <= 0 or _length(entity.vel) > 25:
                continue
            serviced = set()
            for pad in pads:
                if pad.team_id != entity.team_id or pad.unit_type in serviced:
                    continue
                offset = _sub(entity.pos, pad.pos)
                if math.hypot(offset[0], offset[1]) > 22 or abs(offset[2]) > 35:
                    continue
                serviced.add(pad.unit_type)
                if pad.unit_type == 26:
                    self.server.physics.refuel(entity, 3000.0 * seconds)
                elif entity.health_points < entity.max_health:
                    entity.set_health_points(entity.health_points + 30.0 * seconds)

    def _select_turret_target(
        self,
        turret: GameEntity,
        minimum_range: float,
        maximum_range: float,
    ) -> GameEntity | None:
        best: tuple[tuple[float, int], GameEntity] | None = None
        for candidate in self.server.entities.get_all():
            if (
                candidate.net_id == turret.net_id
                or candidate.unit_type not in PLAYER_VEHICLE_UNIT_TYPES
                or not candidate.is_manned
                or candidate.health_points <= 0.0
                or not _can_damage(
                    turret.team_id,
                    candidate.team_id,
                    self.cfg.friendly_fire,
                )
            ):
                continue
            distance = _length(_sub(candidate.pos, turret.pos))
            if distance < minimum_range or distance > maximum_range:
                continue
            key = (distance, candidate.net_id)
            if best is None or key < best[0]:
                best = (key, candidate)
        return best[1] if best is not None else None

    @staticmethod
    def _set_turret_target(turret: GameEntity, target: GameEntity | None) -> None:
        target_id = target.net_id if target is not None else 0
        if turret.related_object_id != target_id:
            turret.related_object_id = target_id
            turret.mark_dirty(UpdateMask.OWNER)

    @staticmethod
    def _aim_turret(turret: GameEntity, direction) -> None:
        rotation = _rotation_toward(direction, turret.rot[0])
        if any(abs(rotation[index] - turret.rot[index]) > 1.0e-7 for index in range(3)):
            turret.rot = rotation
            turret.mark_dirty(UpdateMask.ROT)

    def _advance_gun_turret(
        self,
        turret: GameEntity,
        seconds: float,
        destroyed: dict[int, Destruction],
    ) -> None:
        if turret.weapon_table_id != 3:
            turret.weapon_table_id = 3
            turret.mark_dirty(UpdateMask.WEAPON)
        turret.turret_cooldown = max(0.0, turret.turret_cooldown - seconds)
        target = self._select_turret_target(turret, 0.0, self.cfg.gun_turret_range)
        self._set_turret_target(turret, target)
        self._set_weapon_mask(turret, 1 if target is not None else 0)
        if target is None:
            return
        self._aim_turret(turret, _sub(target.pos, turret.pos))
        if turret.turret_cooldown > 0.0:
            return
        self._fire_gun_turret(turret, target, destroyed)
        turret.turret_cooldown = max(
            0.0,
            self.cfg.gun_turret_refire_seconds + turret.turret_cooldown,
        )

    def _fire_gun_turret(
        self,
        turret: GameEntity,
        target: GameEntity,
        destroyed: dict[int, Destruction],
    ) -> None:
        forward = _forward(turret.rot)
        origin = _add(turret.pos, _scale(forward, GUN_TURRET_MUZZLE_OFFSET))
        hit = self.server.physics.trace_segment(
            origin,
            target.pos,
            ignored_entity=turret.net_id,
        )
        if not hit["hit"] or int(hit["entity_id"]) == 0:
            return
        victim = self.server.entities.get_entity(int(hit["entity_id"]))
        if (
            victim is None
            or victim.net_id in destroyed
            or not _can_damage(
                turret.team_id,
                victim.team_id,
                self.cfg.friendly_fire,
            )
        ):
            return
        if victim.apply_damage(self.cfg.gun_turret_damage):
            destroyed[victim.net_id] = Destruction(victim.net_id, killer_player_id=turret.score_owner_id)

    def _advance_flak_turret(self, turret: GameEntity, seconds: float) -> None:
        self._advance_flak_recoil(turret, seconds)
        turret.turret_cooldown = max(0.0, turret.turret_cooldown - seconds)
        target = self._select_turret_target(
            turret,
            self.cfg.flak_turret_minimum_range,
            self.cfg.flak_turret_maximum_range,
        )
        self._set_turret_target(turret, target)
        if target is None:
            return
        direction = self._flak_intercept_direction(turret.pos, target)
        self._aim_turret(turret, direction)
        if turret.turret_cooldown > 0.0:
            return
        self._fire_flak_shell(turret, target, direction)
        turret.turret_cooldown = (
            self.cfg.flak_turret_refire_tank_seconds
            if target.unit_type in PLAYER_VEHICLE_UNIT_TYPES
            else self.cfg.flak_turret_refire_other_seconds
        )
        turret.turret_recoil_velocity -= self.cfg.flak_turret_recoil_speed

    def _advance_flak_recoil(self, turret: GameEntity, seconds: float) -> None:
        if turret.turret_anchor_pos is None:
            turret.turret_anchor_pos = tuple(turret.pos)
        acceleration = (
            -self.cfg.flak_turret_recoil_spring * turret.turret_recoil_offset
            - self.cfg.flak_turret_recoil_damping * turret.turret_recoil_velocity
        )
        turret.turret_recoil_velocity += acceleration * seconds
        turret.turret_recoil_offset += turret.turret_recoil_velocity * seconds
        turret.turret_recoil_offset = max(-5.0, min(0.5, turret.turret_recoil_offset))
        if (
            abs(turret.turret_recoil_offset) < 1.0e-5
            and abs(turret.turret_recoil_velocity) < 1.0e-4
        ):
            turret.turret_recoil_offset = 0.0
            turret.turret_recoil_velocity = 0.0
        forward = _forward(turret.rot)
        position = _add(
            turret.turret_anchor_pos,
            _scale(forward, turret.turret_recoil_offset),
        )
        velocity = _scale(forward, turret.turret_recoil_velocity)
        if position != turret.pos or velocity != turret.vel:
            turret.pos = position
            turret.vel = velocity
            turret.mark_dirty(UpdateMask.POS | UpdateMask.VEL)

    def _flak_intercept_direction(self, origin, target: GameEntity):
        relative = _sub(target.pos, origin)
        target_velocity = target.vel
        speed = max(self.cfg.flak_turret_muzzle_speed, 1.0e-6)
        a = _dot(target_velocity, target_velocity) - speed * speed
        b = 2.0 * _dot(relative, target_velocity)
        c = _dot(relative, relative)
        intercept_time = None
        if abs(a) <= 1.0e-8:
            if abs(b) > 1.0e-8:
                candidate = -c / b
                if candidate > 0.0:
                    intercept_time = candidate
        else:
            discriminant = b * b - 4.0 * a * c
            if discriminant >= 0.0:
                root = math.sqrt(discriminant)
                candidates = [
                    value
                    for value in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a))
                    if value > 0.0
                ]
                if candidates:
                    intercept_time = min(candidates)
        maximum_lead = self.cfg.flak_turret_maximum_range / speed
        if intercept_time is None or intercept_time > maximum_lead:
            intercept_time = 0.0
        return _normalize(_add(relative, _scale(target_velocity, intercept_time)))

    def _fire_flak_shell(self, turret: GameEntity, target: GameEntity, direction) -> None:
        muzzle = _add(
            turret.pos,
            _scale(direction, self.cfg.flak_turret_muzzle_offset),
        )
        projectile = self.server.entities.create_entity(
            unit_type=FLAK_SHELL_UNIT_TYPE,
            team_id=turret.team_id,
            pos=muzzle,
        )
        projectile.is_manned = False
        projectile.rot = _rotation_toward(direction)
        projectile.vel = _scale(direction, self.cfg.flak_turret_muzzle_speed)
        projectile.related_object_id = turret.net_id
        projectile.score_owner_id = turret.score_owner_id
        projectile.projectile_target_id = target.net_id
        self._flak_positions[projectile.net_id] = projectile.pos
        self._flak_previous_target_distance[projectile.net_id] = _length(
            _sub(target.pos, projectile.pos)
        )
        projectile.mark_dirty(
            UpdateMask.POS
            | UpdateMask.VEL
            | UpdateMask.ROT
            | UpdateMask.OWNER
            | UpdateMask.HEALTH
        )

    def _advance_tank_weapons(
        self,
        tank: GameEntity,
        seconds: float,
        destroyed: dict[int, Destruction],
    ) -> None:
        tank.autocannon_cooldown = max(0.0, tank.autocannon_cooldown - seconds)
        tank.pulse_cooldown = max(0.0, tank.pulse_cooldown - seconds)
        tank.piercer_cooldown = max(0.0, tank.piercer_cooldown - seconds)
        previous_charge = tank.pulse_charge
        tank.pulse_charge = min(
            1.0,
            tank.pulse_charge + seconds / max(self.cfg.pulse_regeneration_seconds, 1.0e-6),
        )
        if abs(tank.pulse_charge - previous_charge) > 1.0e-9:
            tank.mark_dirty(UpdateMask.WEAPON)

        autocannon_pressed = float(tank.actions.get(AUTOCANNON_ACTION, 0.0) or 0.0) != 0.0
        pulse_pressed = float(tank.actions.get(PULSE_ACTION, 0.0) or 0.0) != 0.0
        previous_pulse_pressed = bool(tank.previous_weapon_actions & (1 << PULSE_ACTION))

        firing_mask = 0
        if autocannon_pressed:
            firing_mask |= 1
            if (
                tank.autocannon_cooldown <= 0.0
                and self.server.physics.spend_fuel(tank, self.cfg.autocannon_fuel_cost)
            ):
                self._fire_autocannon(tank, destroyed)
                # At most one discharge per server tick, preserving the
                # original timer's overrun without burst catch-up.
                tank.autocannon_cooldown = max(
                    0.0,
                    self.cfg.autocannon_refire_seconds + tank.autocannon_cooldown,
                )

        if pulse_pressed:
            firing_mask |= 2
        if (
            pulse_pressed
            and not previous_pulse_pressed
            and tank.pulse_cooldown <= 0.0
            and tank.pulse_charge >= self.cfg.pulse_minimum_strength
            and self.server.physics.spend_fuel(tank, self.cfg.pulse_fuel_cost)
        ):
            self._fire_pulse(tank)
            tank.pulse_charge = 0.0
            tank.pulse_cooldown = self.cfg.pulse_refire_seconds

        if tank.actions.get(PIERCER_ACTION, 0):
            firing_mask |= 4
            if tank.piercer_cooldown <= 0 and self.server.physics.spend_fuel(tank, self.cfg.piercer_fuel_cost):
                self._fire_pulse(tank, piercer=True)
                tank.piercer_cooldown = self.cfg.piercer_refire_seconds

        if pulse_pressed:
            tank.previous_weapon_actions |= 1 << PULSE_ACTION
        else:
            tank.previous_weapon_actions &= ~(1 << PULSE_ACTION)
        self._set_weapon_mask(tank, firing_mask)

    def _select_autocannon_target(self, tank: GameEntity, origin, forward):
        _, _, _, maximum_range, aim = self._autocannon_parameters(tank)
        cosine_limit = math.cos(math.radians(aim))
        best = None
        for candidate in self.server.entities.get_all():
            if (
                candidate.net_id == tank.net_id
                or candidate.health_points <= 0.0
                or candidate.team_id == NEUTRAL_TEAM_ID
            ):
                continue
            # Friendly fire permits a manually aimed hit but does not make a
            # friendly entity an autocannon auto-aim candidate.
            if candidate.team_id == tank.team_id:
                continue
            offset = _sub(candidate.pos, origin)
            distance = _length(offset)
            if distance <= 1.0e-6 or distance > maximum_range:
                continue
            direction = _scale(offset, 1.0 / distance)
            cosine = _dot(forward, direction)
            if cosine < cosine_limit:
                continue
            key = (-cosine, distance, candidate.net_id)
            if best is None or key < best[0]:
                best = (key, candidate, direction, cosine)
        return best

    def _fire_autocannon(
        self,
        tank: GameEntity,
        destroyed: dict[int, Destruction],
    ) -> None:
        damage, _, _, maximum_range, aim = self._autocannon_parameters(tank)
        forward = _forward(tank.rot)
        origin = _add(tank.pos, _scale(forward, 4.5))
        selected = self._select_autocannon_target(tank, origin, forward)
        target_id = selected[1].net_id if selected is not None else 0
        if tank.related_object_id != target_id:
            tank.related_object_id = target_id
            tank.mark_dirty(UpdateMask.OWNER)

        direction = selected[2] if selected is not None else forward
        if selected is not None:
            angle = math.acos(max(-1.0, min(1.0, selected[3])))
            error_ratio = angle / math.radians(aim)
        else:
            error_ratio = 0.6
        self._shot_sequence += 1
        rng = random.Random((tank.net_id << 32) ^ self._shot_sequence)
        scatter = (
            self.cfg.autocannon_base_scatter
            + rng.random() * self.cfg.autocannon_random_scatter
        ) * self.cfg.autocannon_scatter_factor * error_ratio
        if selected is not None and selected[1].unit_type == PULSE_UNIT_TYPE:
            scatter *= 0.4
        if scatter > 0.0:
            right = _normalize(_cross(direction, (0.0, 0.0, 1.0)), (0.0, 1.0, 0.0))
            up = _normalize(_cross(right, direction), (0.0, 0.0, 1.0))
            azimuth = rng.random() * math.tau
            direction = _normalize(_add(
                direction,
                _add(
                    _scale(right, scatter * math.cos(azimuth)),
                    _scale(up, scatter * math.sin(azimuth)),
                ),
            ))

        end = _add(origin, _scale(direction, maximum_range))
        hit = self.server.physics.trace_segment(
            origin,
            end,
            ignored_entity=tank.net_id,
        )
        if not hit["hit"] or int(hit["entity_id"]) == 0:
            return
        victim = self.server.entities.get_entity(int(hit["entity_id"]))
        if victim is None or victim.net_id in destroyed:
            return
        if not _can_damage(
            tank.team_id,
            victim.team_id,
            self.cfg.friendly_fire,
        ):
            return
        if victim.apply_damage(damage):
            destroyed[victim.net_id] = Destruction(victim.net_id, killer_player_id=tank.score_owner_id)

    def _fire_pulse(self, tank: GameEntity, *, piercer: bool = False) -> None:
        forward = _forward(tank.rot)
        local_muzzle = TANK_PULSE_MUZZLE_LOCAL_BY_TEAM.get(
            tank.team_id,
            TANK_PULSE_MUZZLE_LOCAL_BY_TEAM[1],
        )
        muzzle = _add(tank.pos, _transform_local(local_muzzle, tank.rot))
        projectile = self.server.entities.create_entity(
            unit_type=PULSE_UNIT_TYPE,
            team_id=tank.team_id,
            pos=muzzle,
        )
        projectile.is_manned = False
        projectile.rot = tank.rot
        speed = self.cfg.piercer_launch_speed if piercer else self.cfg.pulse_launch_speed
        projectile.vel = _add(tank.vel, _scale(forward, speed))
        projectile.related_object_id = tank.net_id
        projectile.score_owner_id = tank.score_owner_id
        projectile.pulse_strength = 1.0 if piercer else tank.pulse_charge
        # Reuse the supported shell presentation; the authoritative fast
        # direct-hit variant has no pulse splash or area impulse.
        projectile.projectile_kind = "piercer" if piercer else "pulse"
        self._pulse_positions[projectile.net_id] = projectile.pos
        projectile.mark_dirty(
            UpdateMask.POS
            | UpdateMask.VEL
            | UpdateMask.ROT
            | UpdateMask.OWNER
            | UpdateMask.HEALTH
        )

    def _advance_pulse_shells(
        self,
        seconds: float,
        destroyed: dict[int, Destruction],
    ) -> None:
        for projectile in list(self.server.entities.get_all()):
            if projectile.unit_type != PULSE_UNIT_TYPE:
                continue
            start = self._pulse_positions.get(projectile.net_id, projectile.pos)
            projectile.projectile_age += seconds
            end = projectile.pos
            contact = self.server.physics.take_projectile_contact(projectile.net_id)
            if contact is not None and int(contact.get("other_entity_id", 0) or 0) in (
                projectile.net_id,
                projectile.related_object_id,
            ):
                # A newly launched shell can overlap the firing Tank for its
                # first native-physics frame.  The segment trace below already
                # excludes both bodies; apply the same rule to contact events
                # so the shell cannot detonate inside its owner's cockpit.
                contact = None
            if contact is not None:
                hit = {
                    "hit": True,
                    "entity_id": int(contact.get("other_entity_id", 0) or 0),
                    "point": tuple(contact["point"]),
                }
            else:
                hit = self.server.physics.trace_segment(
                    start,
                    end,
                    ignored_entity=projectile.net_id,
                    second_ignored_entity=projectile.related_object_id,
                )
            if hit["hit"]:
                projectile.pos = tuple(hit["point"])
                projectile.mark_dirty(UpdateMask.POS | UpdateMask.VEL)
                self._resolve_pulse_impact(projectile, int(hit["entity_id"]), destroyed)
                destroyed[projectile.net_id] = Destruction(projectile.net_id)
                self._pulse_positions.pop(projectile.net_id, None)
                continue
            self._pulse_positions[projectile.net_id] = end
            if projectile.projectile_age >= self.cfg.pulse_lifetime_seconds:
                destroyed[projectile.net_id] = Destruction(projectile.net_id, explosion=False)
                self._pulse_positions.pop(projectile.net_id, None)

    def _forget_flak_shell(self, entity_id: int) -> None:
        self._flak_positions.pop(entity_id, None)
        self._flak_previous_target_distance.pop(entity_id, None)
        self._flak_miss_fuses.pop(entity_id, None)

    def _advance_flak_shells(
        self,
        seconds: float,
        destroyed: dict[int, Destruction],
    ) -> None:
        maximum_lifetime = (
            self.cfg.flak_turret_maximum_range
            / max(self.cfg.flak_turret_muzzle_speed, 1.0e-6)
            + self.cfg.flak_shell_max_fuse_seconds
        )
        for projectile in list(self.server.entities.get_all()):
            if projectile.unit_type != FLAK_SHELL_UNIT_TYPE:
                continue
            start = self._flak_positions.get(projectile.net_id, projectile.pos)
            projectile.projectile_age += seconds
            end = _add(start, _scale(projectile.vel, seconds))
            hit = self.server.physics.trace_segment(
                start,
                end,
                ignored_entity=projectile.net_id,
                second_ignored_entity=projectile.related_object_id,
            )
            if hit["hit"]:
                projectile.pos = tuple(hit["point"])
                projectile.mark_dirty(UpdateMask.POS | UpdateMask.VEL)
                self._resolve_flak_impact(projectile, int(hit["entity_id"]), destroyed)
                destroyed[projectile.net_id] = Destruction(projectile.net_id)
                self._forget_flak_shell(projectile.net_id)
                continue

            detonation_point = None
            target = self.server.entities.get_entity(projectile.projectile_target_id)
            if target is not None and target.health_points > 0.0:
                closest, closest_distance = _closest_point_on_segment(target.pos, start, end)
                current_distance = _length(_sub(target.pos, end))
                previous_distance = self._flak_previous_target_distance.get(
                    projectile.net_id,
                    current_distance,
                )
                if (
                    projectile.projectile_age >= self.cfg.flak_shell_arm_seconds
                    and closest_distance <= self.cfg.flak_shell_minimum_radius
                ):
                    detonation_point = closest
                elif (
                    projectile.projectile_age >= self.cfg.flak_shell_arm_seconds
                    and current_distance > previous_distance
                ):
                    self._flak_miss_fuses.setdefault(
                        projectile.net_id,
                        self.cfg.flak_shell_miss_fuse_seconds,
                    )
                self._flak_previous_target_distance[projectile.net_id] = current_distance
            elif projectile.projectile_age >= self.cfg.flak_shell_arm_seconds:
                self._flak_miss_fuses.setdefault(
                    projectile.net_id,
                    self.cfg.flak_shell_miss_fuse_seconds,
                )

            if projectile.net_id in self._flak_miss_fuses:
                self._flak_miss_fuses[projectile.net_id] -= seconds
                if self._flak_miss_fuses[projectile.net_id] <= 0.0:
                    detonation_point = end

            projectile.pos = tuple(detonation_point if detonation_point is not None else end)
            projectile.mark_dirty(UpdateMask.POS)
            if detonation_point is not None:
                self._resolve_flak_impact(projectile, 0, destroyed)
                destroyed[projectile.net_id] = Destruction(projectile.net_id)
                self._forget_flak_shell(projectile.net_id)
                continue

            self._flak_positions[projectile.net_id] = projectile.pos
            if projectile.projectile_age >= maximum_lifetime:
                destroyed[projectile.net_id] = Destruction(projectile.net_id, explosion=False)
                self._forget_flak_shell(projectile.net_id)

    def _resolve_flak_impact(
        self,
        projectile: GameEntity,
        direct_entity_id: int,
        destroyed: dict[int, Destruction],
    ) -> None:
        direct = self.server.entities.get_entity(direct_entity_id) if direct_entity_id else None
        if direct is not None and _can_damage(
            projectile.team_id,
            direct.team_id,
            self.cfg.friendly_fire,
        ):
            if direct.apply_damage(self.cfg.flak_shell_direct_damage):
                destroyed[direct.net_id] = Destruction(direct.net_id, killer_player_id=projectile.score_owner_id)

        inner_radius = self.cfg.flak_shell_minimum_radius
        outer_radius = self.cfg.flak_shell_maximum_radius
        for victim in self.server.entities.get_all():
            if (
                victim.net_id == projectile.net_id
                or victim.net_id in destroyed
                or victim.health_points <= 0.0
                or not _can_damage(
                    projectile.team_id,
                    victim.team_id,
                    self.cfg.friendly_fire,
                )
            ):
                continue
            offset = _sub(victim.pos, projectile.pos)
            distance = _length(offset)
            if distance > max(outer_radius, self.cfg.flak_shell_force_radius):
                continue
            if distance <= outer_radius:
                if distance <= inner_radius:
                    damage_falloff = 1.0
                else:
                    damage_falloff = (outer_radius - distance) / max(
                        outer_radius - inner_radius,
                        1.0e-6,
                    )
                if victim.apply_damage(self.cfg.flak_shell_splash_damage * damage_falloff):
                    destroyed[victim.net_id] = Destruction(victim.net_id, killer_player_id=projectile.score_owner_id)
            if distance <= self.cfg.flak_shell_force_radius:
                impulse_falloff = 1.0 - distance / max(
                    self.cfg.flak_shell_force_radius,
                    1.0e-6,
                )
                direction = _normalize(offset, (0.0, 0.0, 1.0))
                self.server.physics.apply_linear_impulse(
                    victim.net_id,
                    _scale(direction, self.cfg.flak_shell_impulse * impulse_falloff),
                )

    def _resolve_pulse_impact(
        self,
        projectile: GameEntity,
        direct_entity_id: int,
        destroyed: dict[int, Destruction],
    ) -> None:
        direct = self.server.entities.get_entity(direct_entity_id) if direct_entity_id else None
        if projectile.projectile_kind == "piercer":
            if direct is not None and _can_damage(projectile.team_id, direct.team_id, self.cfg.friendly_fire):
                if direct.apply_damage(self.cfg.piercer_damage):
                    destroyed[direct.net_id] = Destruction(direct.net_id, killer_player_id=projectile.score_owner_id)
            return
        if direct is not None and _can_damage(
            projectile.team_id,
            direct.team_id,
            self.cfg.friendly_fire,
        ):
            if direct.apply_damage(self.cfg.pulse_direct_damage * projectile.pulse_strength):
                destroyed[direct.net_id] = Destruction(direct.net_id, killer_player_id=projectile.score_owner_id)

        radius = self.cfg.pulse_minimum_radius + (
            self.cfg.pulse_maximum_radius - self.cfg.pulse_minimum_radius
        ) * projectile.pulse_strength
        for victim in self.server.entities.get_all():
            if (
                victim.net_id == projectile.net_id
                or victim.net_id in destroyed
                or victim.health_points <= 0.0
                or not _can_damage(
                    projectile.team_id,
                    victim.team_id,
                    self.cfg.friendly_fire,
                )
            ):
                continue
            offset = _sub(victim.pos, projectile.pos)
            distance = _length(offset)
            if distance > radius:
                continue
            falloff = 1.0 - distance / max(radius, 1.0e-6)
            if victim.apply_damage(self.cfg.pulse_splash_damage * projectile.pulse_strength * falloff):
                destroyed[victim.net_id] = Destruction(victim.net_id, killer_player_id=projectile.score_owner_id)
            if distance <= self.cfg.pulse_force_radius and self.server.physics is not None:
                direction = _normalize(offset, (0.0, 0.0, 1.0))
                self.server.physics.apply_linear_impulse(
                    victim.net_id,
                    _scale(direction, self.cfg.pulse_impulse * projectile.pulse_strength * falloff),
                )
