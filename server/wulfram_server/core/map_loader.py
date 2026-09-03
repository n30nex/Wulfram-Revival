# core/map_loader.py
import math
from typing import Dict, Tuple
from wulfram_server.core.entity_manager import EntityManager
from wulfram_server.core.entity import UpdateMask

# --- CONFIGURATION ---
UNIT_TYPE_MAP = {
    "e": 25, # Power Cell
    "s": 29, # Flak Turret
    "g": 30, # Gun Turret
    "r": 27, # Repair Pad
    "f": 26, # Refuel Pad
    "u": 20, # Uplink
    "h": 35, # Not sure, going with darklight for now
}

# Recovered from the stock map parser at 0x004E9F70. These are cargo item
# IDs, not entity unit types; deployment remaps them to unit types 25..36.
CARGO_ITEM_ID_MAP = {
    "e": 0,
    "f": 1,
    "r": 2,
    "h": 3,
    "s": 4,
    "g": 5,
    "M": 6,
    "L": 7,
    "p": 8,
    "o": 9,
    "d": 10,
    "b": 11,
}

class MapLoader:
    def __init__(self, entity_manager: EntityManager):
        self.em = entity_manager

    def load_from_string(self, map_data: str):
        """Parses the raw map text and spawns entities."""
        count = 0
        lines = map_data.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            parts = line.split()
            
            try:
                # 1. Detect Type and handling 'c' prefix
                char_code = parts[0]
                is_crate = False
                data_start_index = 1
                
                # Handle 'c' prefix (Crated unit)
                if char_code == 'c':
                    is_crate = True
                    char_code = parts[1] # The actual type is the next char
                    data_start_index = 2

                # 2. Resolve Unit Type ID
                unit_type_id = 0
                if is_crate:
                    unit_type_id = 19
                else:
                    unit_type_id = UNIT_TYPE_MAP.get(char_code, 0)

                if unit_type_id == 0:
                    print(f"[MapLoader] WARN: Unknown unit code '{char_code}'")
                    continue

                # 3. Parse Data
                # Syntax: [Type] [Team] [X] [Y] [Z] [RotX] [RotY] [RotZ] [Flag]
                team_id = int(parts[data_start_index])
                
                x = float(parts[data_start_index + 1])
                y = float(parts[data_start_index + 2])
                z = float(parts[data_start_index + 3])
                
                # Rotations
                rx = float(parts[data_start_index + 4])
                ry = float(parts[data_start_index + 5])
                rz = float(parts[data_start_index + 6])
                
                # 4. Create Entity
                # Note: Coordinate systems often differ. 
                # TODO: Check if needed to swap Y and Z or negate them.
                # Assuming direct mapping for now:
                pos = (x, y, z)
                
                entity = self.em.create_entity(unit_type=unit_type_id, team_id=team_id, pos=pos)
                if is_crate:
                    if char_code not in CARGO_ITEM_ID_MAP:
                        print(f"[MapLoader] WARN: Unknown cargo item code '{char_code}'")
                        self.em.remove_entity(entity.net_id)
                        continue
                    entity.cargo_item_id = CARGO_ITEM_ID_MAP[char_code]
                
                # Apply Rotation
                entity.rot = (rx, ry, rz)
                # A hard UPDATE_ARRAY containing both position and rotation
                # takes the original client through its authoritative-pose
                # path and calls PutBodyToSleep. Sleeping bodies are excluded
                # from contact impulses, so map-authored base units remain
                # stationary instead of being pushed into motion by players.
                entity.mark_dirty(UpdateMask.ROT | UpdateMask.HARD_SYNC)
                
                # Optional: Handle the last flag (Active state?)
                # state_flag = int(parts[data_start_index + 7])
                
                count += 1
                
            except (ValueError, IndexError) as e:
                print(f"[MapLoader] Error parsing line: {line} | {e}")

        print(f"[MapLoader] Successfully loaded {count} entities.")
