"""One weapon layout for Behavior, entity updates and owner/spawn vitals."""
from wulfram_server.network.translation_config import get_config_by_index

# Retail slot names: 0 autocannon/machine gun, 1 repair beam, 4 pulse, 5 piercer.
READY_SLOTS = {0: (0, 4, 5), 1: (0, 1), 2: (), 3: (0,)}


def write_ready_mask(writer, table, mask):
    width = len(READY_SLOTS[table])
    writer.write_bits(mask & ((1 << width) - 1), width)


def write_local_weapon_state(writer, table, mask, pulse_charge=1.0, repair_charge=1.0):
    write_ready_mask(writer, table, mask)
    for slot, index, value in ((4, 13, pulse_charge), (1, 14, repair_charge)):
        if slot in READY_SLOTS[table]:
            _, encoded, width = get_config_by_index(index).compress(value)
            writer.write_bits(encoded, width)
