"""Community loadouts using the retail client's supported vehicle models."""
LOADOUTS = {"tank": (0, 100.0), "scout": (1, 75.0), "siege": (0, 180.0)}


def chosen_loadout(session, requested_unit):
    preference = getattr(session, "vehicle_loadout", "auto")
    return ("scout" if requested_unit == 1 else "tank") if preference == "auto" else preference


def apply_loadout(entity, name):
    unit, health = LOADOUTS[name]
    if entity.unit_type != unit:
        raise ValueError("loadout and vehicle model disagree")
    entity.vehicle_loadout = name
    entity.weapon_table_id = unit
    entity.max_health = health
    entity.set_health_points(health)
