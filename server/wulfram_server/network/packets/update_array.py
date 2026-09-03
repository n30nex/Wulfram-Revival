from wulfram_server.network.streams import PacketWriter
from wulfram_server.network.translation_config import *
from wulfram_server.core.config import get_ticks
from wulfram_server.core.entity import GameEntity, UpdateMask

class EntitySerializer:
    """
    Helper class that handles the specific bit-writing order 
    required by the C++ client's 'WIP_read_array_from_bitstream'.
    """
    def __init__(self, writer: PacketWriter):
        self.writer = writer

    def serialize(
        self,
        entity: GameEntity,
        force_definition=False,
        forced_mask: int | None = None,
        viewer_team: int | None = None,
    ):
        # 1. Determine the Mask
        # If forced_mask is provided, use it. Otherwise, use entity's current dirty state.
        mask = forced_mask if forced_mask is not None else entity.pending_mask
        
        # If forcing definition (spawning), ensure Bit 0 is set
        if force_definition:
            mask |= UpdateMask.DEFINITION
        # Only entity types with an enabled Behavior weapon table may carry
        # the compact inventory state. Tank uses table 0; Gun Turret uses 3.
        if entity.unit_type not in (0, 30):
            mask &= ~UpdateMask.WEAPON
            
        # 2. Write Header (Standard for every entity)
        self.writer.write_int32(entity.net_id)
        self.writer.write_bool(entity.is_manned)

        # Ensure we write the calculated 'mask', NOT entity.pending_mask
        self.writer.write_bits(mask, 10)
        
        # Bank Selector
        # C++ reads Index[0].header bits. We defined this as BANK_SELECTOR_BITS (16).
        # We write '0' to choose Bank 0 (Index 16).
        self.writer.write_bits(0, BANK_SELECTOR_BITS) 

        # 3. Handle Bit 0: Definition (The "Creation" block)
        if mask & UpdateMask.DEFINITION:
            # unit_type (8 bits usually)
            self.writer.write_bits(entity.unit_type, ID_BITS_UNIT)
            # team_id (8 bits)
            self.writer.write_bits(entity.team_id, ID_BITS_TEAM)
            # team_id_also_maybe (State/Sub-team)
            self.writer.write_bits(entity.team_id, ID_BITS_TEAM) 

            # TODO: 37 = decoration, figure out what the ints are for
            if entity.unit_type == 37:
                self.writer.write_int32(0)
                self.writer.write_int32(0)
            elif entity.unit_type == 19:
                # The stock client treats item ID 13 as "ENEMY CARGO
                # (LOCKED)". Preserve the real ID on the server and reveal it
                # only to clients on the cargo's team.
                cargo_item_id = (
                    entity.cargo_item_id
                    if viewer_team is None or viewer_team == entity.team_id
                    else 13
                )
                self.writer.write_bits(cargo_item_id, ID_BITS_UNIT_CARGO)
            
            # is_teleport_or_snap (Force Snap)
            self.writer.write_bool(True) 
        
        # 4. The Dynamic Data Loop
        # The C++ client iterates bits 1 through 9. Order is strict.

        # Bit 1: Position
        if mask & UpdateMask.POS:
            self._write_vec(entity.pos, COMPRESSOR_POS)
            
        # Bit 2: Velocity
        if mask & UpdateMask.VEL:
            self._write_vec(entity.vel, COMPRESSOR_VEL)
            
        # Bit 3: Rotation
        if mask & UpdateMask.ROT:
            self._write_vec(entity.rot, COMPRESSOR_ROT)
            
        # Bit 4: Spin (Angular Velocity)
        if mask & UpdateMask.SPIN:
            self._write_vec(entity.spin, COMPRESSOR_SPIN) 

        # Bit 5: Health
        if mask & UpdateMask.HEALTH:
            _, val, bits = COMPRESSOR_STAT.compress(entity.health)
            self.writer.write_bits(val, bits) 

        # Bit 6: Weapon Inventory
        if mask & UpdateMask.WEAPON:
            # Net_Read_Weapon_Inventory first selects the compact Behavior
            # table, then consumes only the bit groups enabled by that table.
            self.writer.write_bits(entity.weapon_table_id, GLOBAL_CONFIGS[1]['head'])
            if entity.weapon_table_id == 0:
                # Tank Behavior enables the firing-state channel for slots 0
                # and 4, in slot order.
                self.writer.write_bits(entity.weapon_ready_mask & 0b11, 2)
            elif entity.weapon_table_id == 1:
                # Scout Behavior enables the machine-gun and repair channels.
                self.writer.write_bits(entity.weapon_ready_mask & 0b11, 2)
            elif entity.weapon_table_id == 3:
                # Gun Turret enables the ready/firing-state channel only for
                # slot zero.
                self.writer.write_bits(entity.weapon_ready_mask & 0b1, 1)

        # Bit 7: Energy
        if mask & UpdateMask.ENERGY:
             _, val, bits = COMPRESSOR_STAT.compress(entity.energy)
             self.writer.write_bits(val, bits)

        # Bit 8: Owner/New Player
        if mask & UpdateMask.OWNER:
            self.writer.write_int32(entity.related_object_id)

        # Bit 9: Hard Update
        # No payload; just a flag.
        pass

    def _write_vec(self, vec, compressor: TranslationConfig):
        """
        Writes a 3D vector dynamically matching C++ logic:
        [Header] [X_Data] [Y_Data] [Z_Data]
        """
        # 1. Determine "High Quality" Priority
        # We want the max resolution defined in the config.
        # If header_bits is 2, max value is 3 (binary 11).
        priority = (1 << compressor.precision_header_bits) - 1
        
        # 2. Write the Header ONCE
        # The client reads 'precision_header_bits' here.
        self.writer.write_bits(priority, compressor.precision_header_bits)

        # 3. Write X, Y, Z
        for val in vec:
            # We enforce the priority we just wrote
            p, compressed_val, num_bits = compressor.compress(val, priority=priority)

            #print(f"[DEBUG] pri={p} val={compressed_val} bits={num_bits}")
            
            # Write the compressed int using the calculated bit count
            self.writer.write_bits(compressed_val, num_bits)

class UpdateArrayPacket:
    RECONCILIATION_MAGIC = 0x57505231  # "WPR1"

    def __init__(
        self,
        sequence_id: int,
        is_view_update=False,
        viewer_team: int | None = None,
        reconciliation_tick: int | None = None,
        acknowledged_input_marker: int | None = None,
        acknowledged_input_tick: int | None = None,
    ):
        self.writer = PacketWriter()
        self.sequence_id = sequence_id
        self.entities = []
        self.local_stats = None # Tuple: (Health, Energy)
        self.viewer_team = viewer_team
        self.reconciliation_tick = reconciliation_tick
        self.acknowledged_input_marker = acknowledged_input_marker
        self.acknowledged_input_tick = acknowledged_input_tick

        # Timestamp
        if (is_view_update):
            self.writer.write_int32(get_ticks())
        
        # Server Sequence
        self.writer.write_int32(self.sequence_id)

    def set_local_stats(
        self,
        health: float,
        energy: float,
        weapon_table_id: int = 0,
        weapon_ready_mask: int = 0,
        pulse_charge: float = 1.0,
    ):
        """
        Sets the HUD stats for the player receiving this packet.
        Corresponds to 'Parse_SpawnVitalStats' in C++.
        """
        self.local_stats = (
            health,
            energy,
            weapon_table_id,
            weapon_ready_mask,
            pulse_charge,
        )

    def add_entity(self, entity: GameEntity, force_spawn=False, forced_mask: int | None = None):
        """Adds an entity to be serialized in this packet."""
        self.entities.append((entity, force_spawn, forced_mask))

    def get_bytes(self):
        # --- SECTION 1: Local Stats (The "Weapon State/Vital Stats" part) ---
        if self.local_stats:
            # The client reads one bit: If 1, it reads stats.
            self.writer.write_bool(True) 
            
            self.writer.write_bits(self.local_stats[2], GLOBAL_CONFIGS[1]['head'])
            
            _, h_val, h_bits = COMPRESSOR_STAT.compress(self.local_stats[0])
            _, e_val, e_bits = COMPRESSOR_STAT.compress(self.local_stats[1])
            
            self.writer.write_bits(h_val, h_bits)
            self.writer.write_bits(e_val, e_bits)
            # Tank table 0 has two firing-state bits (autocannon, pulse) and
            # an enabled pulse slot, which makes the trailing charge required.
            if self.local_stats[2] == 0:
                self.writer.write_bits(self.local_stats[3] & 0b11, 2)
                pulse_config = get_config_by_index(13)
                _, pulse_val, pulse_bits = pulse_config.compress(self.local_stats[4])
                self.writer.write_bits(pulse_val, pulse_bits)
            elif self.local_stats[2] == 1:
                # Scout has two state channels plus the repair-charge scalar
                # required by its available slot 1. Repair is continuously
                # usable in the authoritative server, so publish full charge.
                self.writer.write_bits(self.local_stats[3] & 0b11, 2)
                repair_config = get_config_by_index(14)
                _, repair_val, repair_bits = repair_config.compress(1.0)
                self.writer.write_bits(repair_val, repair_bits)
        else:
            # If 0, client skips Parse_SpawnVitalStats
            self.writer.write_bool(False) 

        # --- SECTION 2: Entity Loop ---
        count = len(self.entities)
        
        # Total Entity Count (8 bits)
        self.writer.write_bits(count, 8)

        serializer = EntitySerializer(self.writer)
        
        for entity, force_spawn, forced_mask in self.entities:
            serializer.serialize(
                entity,
                force_definition=force_spawn,
                forced_mask=forced_mask,
                viewer_team=self.viewer_team,
            )

        # Wulfram's stock decoder stops after the counted entity loop. The
        # remaster consumes this optional bit-aligned trailer; old clients
        # safely ignore it as trailing packet data.
        if (
            self.reconciliation_tick is not None
            and self.acknowledged_input_marker is not None
            and self.acknowledged_input_tick is not None
        ):
            self.writer.write_int32(self.RECONCILIATION_MAGIC)
            self.writer.write_int32(self.reconciliation_tick)
            self.writer.write_int32(self.acknowledged_input_marker)
            self.writer.write_int32(self.acknowledged_input_tick)

        return self.writer.get_bytes()
