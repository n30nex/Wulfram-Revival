# core/entity_manager.py
from typing import Dict, List, Optional
from wulfram_server.core.entity import GameEntity, UpdateMask
from wulfram_server.network.packets.update_array import UpdateArrayPacket
from wulfram_server.network.packets.gameplay import DeleteObjectPacket

class EntityManager:
    def __init__(self):
        self._entities: Dict[int, GameEntity] = {}
        self._next_net_id = 1  # Start at 1, 0 might be reserved or null

    def create_entity(
        self,
        unit_type: int,
        team_id: int,
        pos: tuple = (0, 0, 0),
        override_net_id: Optional[int] = None,
        *,
        rot: tuple = (0, 0, 0),
        is_manned: bool = True,
        register: bool = True,
    ) -> GameEntity:
        """Creates, stores, and returns a new entity."""
        if override_net_id is not None:
            net_id = override_net_id
        else:
            net_id = self._next_net_id
            self._next_net_id += 1

        print(f"[DEBUG] create_entity: net_id={net_id} unit_type={unit_type} team_id={team_id} pos={pos}")

        entity = GameEntity(net_id=net_id, unit_type=unit_type, team_id=team_id)
        entity.pos = pos
        entity.rot = rot
        entity.is_manned = is_manned
        entity.health = 1.0
        entity.max_health = {
            6: 40.0,
            29: 550.0,
            30: 300.0,
        }.get(unit_type, 100.0)
        entity.health_points = entity.max_health
        if unit_type == 30:
            # Behavior weapon table 3 is the Gun Turret table. Include the
            # empty ready-state channel in its initial definition/update so a
            # client never temporarily decodes it as a Tank inventory.
            entity.weapon_table_id = 3
        # Marking DEFINITION as dirty will make sure it gets spawned
        # And HEALTH and POS will make sure those stats are updated at the same time
        initial_mask = (
            UpdateMask.DEFINITION
            | UpdateMask.HEALTH
            | UpdateMask.POS
            | UpdateMask.ROT
        )
        if unit_type == 30:
            initial_mask |= UpdateMask.WEAPON
        entity.mark_dirty(initial_mask)
        
        if register:
            self._entities[net_id] = entity
        return entity

    def register_entity(self, entity: GameEntity) -> None:
        """Publish a fully initialized entity using its reserved network ID."""
        existing = self._entities.get(entity.net_id)
        if existing is entity:
            return
        if existing is not None:
            raise ValueError(f"network entity ID {entity.net_id} is already registered")
        self._entities[entity.net_id] = entity

    def remove_entity(self, net_id: int) -> Optional[DeleteObjectPacket]:
        """
        Removes the entity from the registry and returns the DeleteObjectPacket.
        The caller is responsible for broadcasting this packet.
        """
        if net_id in self._entities:
            del self._entities[net_id]
            return DeleteObjectPacket(net_id=net_id)
        
        return None

    def get_entity(self, net_id: int) -> Optional[GameEntity]:
        return self._entities.get(net_id)

    def get_all(self) -> List[GameEntity]:
        return list(self._entities.values())
    
    def get_dirty_entities(self) -> List[GameEntity]:
        """Returns a list of all entities that have changed this tick."""
        return [e for e in self._entities.values() if e.pending_mask > 0]

    def get_view_dirty_entities(self) -> List[GameEntity]:
        """Returns entities awaiting an owner/view update."""
        return [e for e in self._entities.values() if e.pending_view_mask > 0]

    def clear_update_dirty_flags(self):
        """Clears changes consumed by remote update-array packets."""
        for entity in self._entities.values():
            entity.clear_update_dirty()

    def clear_view_dirty_flags(self):
        """Clears changes consumed by owner/view packets."""
        for entity in self._entities.values():
            entity.clear_view_dirty()

    def clear_all_dirty_flags(self):
        """Clears dirty flags for both packet streams."""
        for e in self._entities.values():
            e.clear_dirty()

    # --- PACKET GENERATION ---

    def build_update_packet(self, entities: List[GameEntity], sequence_num: int, 
                           is_view_update: bool, 
                           local_stats: tuple[float, float] | None = None,
                           viewer_team: int | None = None) -> Optional[bytes]:
        """
        Constructs the payload for an UpdateArrayPacket.
        Crucially, this does NOT clear dirty flags, allowing you to reuse 
        the dirty state for multiple clients.
        """
        # If no entities changed and we aren't forcing local stats (like a heartbeat), return None
        if not entities and not local_stats:
            return None

        packet = UpdateArrayPacket(
            sequence_id=sequence_num,
            is_view_update=is_view_update,
            viewer_team=viewer_team,
        )
        
        # 1. Set Local Stats (Health/Energy) - Only used for 0x0F (View)
        if local_stats:
            packet.set_local_stats(*local_stats)
            
        # 2. Add Entities
        for entity in entities:
             # If the DEFINITION bit is set, we must tell the packet to write the full spawn info
             force_spawn = bool(entity.pending_mask & UpdateMask.DEFINITION)
             packet.add_entity(entity, force_spawn=force_spawn)

        return packet.get_bytes()

    def build_forced_update_packet(
        self,
        entities: List[GameEntity],
        sequence_num: int,
        is_view_update: bool,
        forced_mask: int,
        local_stats: tuple[float, float] | None = None,
        force_spawn: bool = True,
        viewer_team: int | None = None,
        reconciliation_tick: int | None = None,
        acknowledged_input_marker: int | None = None,
        acknowledged_input_tick: int | None = None,
    ) -> Optional[bytes]:
        """
        Constructs an UpdateArray payload with an explicit mask instead of each
        entity's pending dirty state. This is useful for join-in-progress catch-up
        snapshots where the target client missed an earlier DEFINITION update.
        """
        if not entities and not local_stats:
            return None

        packet = UpdateArrayPacket(
            sequence_id=sequence_num,
            is_view_update=is_view_update,
            viewer_team=viewer_team,
            reconciliation_tick=reconciliation_tick,
            acknowledged_input_marker=acknowledged_input_marker,
            acknowledged_input_tick=acknowledged_input_tick,
        )
        if local_stats:
            packet.set_local_stats(*local_stats)

        for entity in entities:
            packet.add_entity(entity, force_spawn=force_spawn, forced_mask=forced_mask)

        return packet.get_bytes()

    def get_snapshot_packet(
        self,
        sequence_num: int,
        health: float = 1.0,
        energy: float = 1.0,
        viewer_team: int | None = None,
    ) -> bytes:
        """
        Returns a packet containing the FULL state of the world + Local Stats.
        THREAD-SAFE: Does not modify entity state.
        """
        packet = UpdateArrayPacket(
            sequence_id=sequence_num,
            is_view_update=True,
            viewer_team=viewer_team,
        )

        # Tell the client it is alive
        packet.set_local_stats(health=health, energy=energy)

        # Include both pose vectors with HARD_SYNC. The original client applies
        # that combination as an authoritative pose and puts the body to sleep;
        # omitting HARD_SYNC explicitly wakes it. This keeps map-loaded base
        # units stationary for clients receiving a full/join-in-progress world
        # snapshot as well as for clients present during the initial broadcast.
        snapshot_mask = (
            UpdateMask.DEFINITION
            | UpdateMask.POS
            | UpdateMask.VEL
            | UpdateMask.ROT
            | UpdateMask.HEALTH
            | UpdateMask.WEAPON
            | UpdateMask.OWNER
            | UpdateMask.HARD_SYNC
        )
        
        for entity in self._entities.values():
            # Pass the mask explicitly. Do NOT touch entity.pending_mask.
            packet.add_entity(
                entity, 
                force_spawn=True, 
                forced_mask=snapshot_mask
            )

        return b'\x0F' + packet.get_bytes()

    def get_dirty_packet(self, sequence_num: int, health: float = 1.0, energy: float = 1.0) -> Optional[bytes]:
        """
        Returns a packet containing ONLY changed entities.
        Used in the main 10Hz update loop.
        Automatically clears the dirty flags of processed entities.
        """
        dirty_entities = [e for e in self._entities.values() if e.pending_mask > 0]
        
        # OPTIMIZATION: If nothing changed, we MIGHT still want to send stats 
        # to keep the health bar synced, but usually we only send if entities move.
        # For now, let's only send if there are entity updates OR if we want to force a heartbeat.
        if not dirty_entities:
            return None

        packet = UpdateArrayPacket(sequence_id=sequence_num, is_view_update=False)
        packet.set_local_stats(health=health, energy=energy)
        
        for entity in dirty_entities:
            packet.add_entity(entity, force_spawn=False)

        payload = packet.get_bytes()

        # Need to clear_dirty AFTER we call packet.get_bytes()!
        for entity in dirty_entities:
            # Reset flags so we don't send it again until it changes
            entity.clear_dirty()

        return b'\x0E' + payload
    
    def get_dirty_packet_view(self, sequence_num: int, health: float = 1.0, energy: float = 1.0) -> Optional[bytes]:
        """
        Returns a packet containing ONLY changed entities.
        Used in the main update loop.
        Automatically clears the dirty flags of processed entities.
        """
        dirty_entities = [e for e in self._entities.values() if e.pending_mask > 0]
        
        # OPTIMIZATION: If nothing changed, we MIGHT still want to send stats 
        # to keep the health bar synced, but usually we only send if entities move.
        # For now, let's only send if there are entity updates OR if we want to force a heartbeat.
        if not dirty_entities:
            return None

        packet = UpdateArrayPacket(sequence_id=sequence_num, is_view_update=True)
        packet.set_local_stats(health=health, energy=energy)
        
        for entity in dirty_entities:
            packet.add_entity(entity, force_spawn=False)

        payload = packet.get_bytes()

        # Need to clear_dirty AFTER we call packet.get_bytes()!
        for entity in dirty_entities:
            # Reset flags so we don't send it again until it changes
            entity.clear_dirty()

        return b'\x0F' + payload
