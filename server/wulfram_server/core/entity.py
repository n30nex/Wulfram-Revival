from collections import deque
from dataclasses import dataclass, field
from enum import IntFlag


# InstallTeamInfoAndCreateNeutralTeam at 0x00417C90 writes zero to the
# client-created Neutral TeamInfo's teamId field.
NEUTRAL_TEAM_ID = 0
RED_TEAM_ID = 1
BLUE_TEAM_ID = 2
TEAM_ID_BY_SIDE = {
    "neutral": NEUTRAL_TEAM_ID,
    "red": RED_TEAM_ID,
    "blue": BLUE_TEAM_ID,
}
TEAM_SIDE_BY_ID = {team_id: side for side, team_id in TEAM_ID_BY_SIDE.items()}


@dataclass(frozen=True, slots=True)
class VehicleControls:
    turn: float = 0.0
    move: float = 0.0
    strafe: float = 0.0
    jet: float = 0.0
    tilt: float = 0.0
    roll: float = 0.0
    jump: float = 0.0


@dataclass(frozen=True, slots=True)
class InputSample:
    sequence: int
    controls: VehicleControls
    client_time_or_sequence: int = 0
    client_flags: int = 0


@dataclass(frozen=True, slots=True)
class PendingTransientEvent:
    """One client presentation event awaiting a reliable broadcast attempt."""

    event_type: int
    position: tuple[float, float, float] | None = None
    entity_id: int | None = None
    # Jump needs an immediate soft owner correction before its sound. Docking
    # must not send one because a soft pose update wakes the sleeping body.
    requires_owner_motion_update: bool = False

    def __post_init__(self) -> None:
        if (self.position is None) == (self.entity_id is None):
            raise ValueError(
                "a transient event must reference exactly one position or entity"
            )

class UpdateMask(IntFlag):
    """
    Maps directly to the r_update_bitmask in the C++ client.
    """
    # Bit 0: Definition (0 = Delta/Move, 1 = Full Create/Def)
    DEFINITION = 1 << 0  
    # Bit 1-4: Physics Vectors
    POS        = 1 << 1  
    VEL        = 1 << 2  
    ROT        = 1 << 3  
    SPIN       = 1 << 4  
    # Bit 5-8: State/Stats
    HEALTH     = 1 << 5  
    WEAPON     = 1 << 6  
    ENERGY     = 1 << 7  
    OWNER      = 1 << 8  
    # Bit 9: Hard Sync (Forces position snap, no interpolation)
    HARD_SYNC  = 1 << 9 

@dataclass
class GameEntity:
    net_id: int
    unit_type: int = 0
    team_id: int = 0
    
    # State Data
    pos: tuple = (0.0, 0.0, 0.0)
    vel: tuple = (0.0, 0.0, 0.0)
    rot: tuple = (0.0, 0.0, 0.0)
    spin: tuple = (0.0, 0.0, 0.0)
    # Contact-derived tolerance written by the portable physics solver. This
    # is not a jet-probe or terrain distance.
    settling_contact_threshold: float = 0.0
    # The native trace tick of this body's most recent collision constraint.
    # Keeping the tick (instead of a sticky boolean) lets gameplay evaluate
    # settling once per authoritative physics step.
    physics_step_tick: int = 0
    physics_contact_tick: int = 0
    health: float = 1.0
    health_points: float = 100.0
    max_health: float = 100.0
    energy: float = 1.0

    # Cargo boxes (unit type 19) carry the compact item ID used by the stock
    # client. IDs 0..11 select deployable unit types 25..36; 13 is only the
    # redacted "enemy cargo" wire value and is never the authoritative item.
    cargo_item_id: int = 0

    # The bit-8 field is polymorphic in the original protocol: Tanks use it
    # for their selected autocannon target while projectiles use it for their
    # shooter/mother object.
    related_object_id: int = 0
    weapon_table_id: int = 0
    weapon_ready_mask: int = 0
    autocannon_cooldown: float = 0.0
    pulse_cooldown: float = 0.0
    pulse_charge: float = 1.0
    pulse_strength: float = 0.0
    projectile_age: float = 0.0
    projectile_target_id: int = 0
    turret_cooldown: float = 0.0
    turret_anchor_pos: tuple | None = None
    turret_recoil_offset: float = 0.0
    turret_recoil_velocity: float = 0.0
    previous_weapon_actions: int = 0

    # Input / Actions State
    # Maps ActionID (int) -> Value (float)
    # e.g. { 5: 0.5, 1: 1.0 }
    actions: dict = field(default_factory=dict)
    input_sequence: int = 0
    last_processed_input: int = 0
    # Unity reconciliation metadata. The authoritative native sequence remains
    # server-owned; these echo the raw client marker and server tick associated
    # with the latest processed sample.
    last_processed_client_marker: int = 0
    last_processed_client_tick: int = 0
    pending_inputs: deque[InputSample] = field(
        default_factory=lambda: deque(maxlen=256),
        repr=False,
    )
    # Accepted gameplay events are queued by the native authority and drained
    # only after every ready client has received the matching transient array.
    pending_transient_events: list[PendingTransientEvent] = field(
        default_factory=list,
        repr=False,
    )
    
    # Flags
    is_manned: bool = True
    is_docked: bool = False
    
    # Remote update-array and owner/view packets have independent clocks, so
    # each needs to retain changes until its next send.
    pending_mask: int = 0
    pending_view_mask: int = 0

    def mark_dirty(self, mask: UpdateMask):
        """Flag specific fields to be sent in the next update."""
        self.pending_mask |= mask
        self.pending_view_mask |= mask

    def clear_update_dirty(self):
        """Reset flags consumed by remote update-array packets."""
        self.pending_mask = 0

    def clear_view_dirty(self):
        """Reset flags consumed by the owning client's view packet."""
        self.pending_view_mask = 0

    def clear_dirty(self):
        """Reset both packet streams, primarily for initialization/tests."""
        self.clear_update_dirty()
        self.clear_view_dirty()

    def set_pos(self, x, y, z):
        self.pos = (x, y, z)
        # Usually when pos changes, we want a hard sync or standard pos update
        self.mark_dirty(UpdateMask.POS)

    def set_stats(self, health=None, energy=None):
        if health is not None:
            self.health = health
            self.health_points = max(0.0, min(self.max_health, float(health) * self.max_health))
            self.mark_dirty(UpdateMask.HEALTH)
        if energy is not None:
            self.energy = energy
            self.mark_dirty(UpdateMask.ENERGY)

    def set_health_points(self, value: float) -> None:
        self.health_points = max(0.0, min(self.max_health, float(value)))
        self.health = self.health_points / self.max_health if self.max_health > 0.0 else 0.0
        self.mark_dirty(UpdateMask.HEALTH)

    def apply_damage(self, amount: float) -> bool:
        """Apply damage to a live entity and report whether it became lethal."""
        if amount <= 0.0 or self.health_points <= 0.0:
            return False
        self.set_health_points(self.health_points - amount)
        return self.health_points <= 0.0

    def repair(self, amount: float) -> bool:
        """Repair an existing damaged entity without permitting resurrection."""
        if amount <= 0.0 or self.health_points <= 0.0 or self.health_points >= self.max_health:
            return False
        self.set_health_points(self.health_points + amount)
        return True

    def current_input_sample(
        self,
        *,
        client_time_or_sequence: int = 0,
        client_flags: int = 0,
    ) -> InputSample:
        # The recovered Tank controller negates raw channels 1 and 3. Channel
        # Channel 4 is a server-authoritative binary jump request; jet
        # strength remains channel 5.
        controls = VehicleControls(
            turn=-float(self.actions.get(1, 0.0) or 0.0),
            move=float(self.actions.get(2, 0.0) or 0.0),
            strafe=-float(self.actions.get(3, 0.0) or 0.0),
            jet=float(self.actions.get(5, 0.0) or 0.0),
            tilt=float(self.actions.get(6, 0.0) or 0.0),
            roll=float(self.actions.get(7, 0.0) or 0.0),
            jump=1.0 if float(self.actions.get(4, 0.0) or 0.0) != 0.0 else 0.0,
        )
        return InputSample(
            sequence=self.input_sequence,
            controls=controls,
            client_time_or_sequence=client_time_or_sequence,
            client_flags=client_flags,
        )

    def record_input_sample(
        self,
        *,
        sequence: int | None = None,
        client_time_or_sequence: int = 0,
        client_flags: int = 0,
    ) -> InputSample:
        # The authoritative server owns this monotonic sequence. The two raw
        # packet markers are retained for diagnostics but are not trusted as an
        # authoritative clock until their protocol semantics are proved.
        if sequence is None:
            sequence = self.input_sequence + 1
        if sequence <= self.input_sequence:
            raise ValueError("input sequence must increase monotonically")
        self.input_sequence = sequence
        sample = self.current_input_sample(
            client_time_or_sequence=client_time_or_sequence,
            client_flags=client_flags,
        )
        self.pending_inputs.append(sample)
        return sample
