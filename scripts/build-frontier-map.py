"""Create an original, symmetrical Wulfram map; no original assets are copied."""
from pathlib import Path
import argparse
import math

NAME = "frontier"
GRID = 129
SIZE = 5600.0
SPACING = SIZE / (GRID - 1)


def elevation(x, y):
    # Broad approaches let a large CPU match leave both bases without jams.
    base_distance = min(math.hypot(x - 875, y - 2800), math.hypot(x - 4725, y - 2800))
    hill = sum(145 * math.exp(-((x-cx)/420)**2 - ((y-cy)/300)**2)
               for cx in (2187.5, 3412.5) for cy in (2187.5, 3412.5))
    edge = min(x, y, SIZE-x, SIZE-y)
    ridge = 240 * max(0, 1-edge/525)**2
    lane_distance = min(abs(y-lane) for lane in (1575, 2800, 4025))
    road_blend = min(1, max(0, (lane_distance-87.5)/175))
    base_blend = min(1, max(0, (base_distance-525)/262.5))
    return 25 + (hill * road_blend + ridge) * base_blend


def generate(destination: Path):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    land = [f"{GRID}x{GRID}", f"{SIZE:.6f}x{SIZE:.6f}"]
    for iy in range(GRID):
        y = iy * SPACING
        for ix in range(GRID):
            x = ix * SPACING
            z = elevation(x, y)
            road = min(abs(y-lane) for lane in (1575, 2800, 4025)) <= 87.5
            tile = 1 if road else 2 if z > 90 else 0
            land.append(f"{tile} {z:.6f}")
    (destination / "land").write_text("\n".join(land) + "\n", encoding="ascii", newline="\n")
    # Rule values are XORed with 15 by the retail parser: zero fills all corners.
    textures = ("4sand001", "Bdt001", "canyon003")
    (destination / "tagmap2").write_text("".join(f"+0template {name} 0 \n" for name in textures), encoding="ascii", newline="\n")
    (destination / "tagmap").write_text("".join(f"{i}:{name}\n" for i, name in enumerate(textures)), encoding="ascii", newline="\n")
    (destination / "start_script").write_text('sky_names "sunset"\nmap_name "Canadaverse Frontier"\n', encoding="ascii", newline="\n")
    state = ["# Canadaverse Frontier: original map, eight repair pads per team."]

    def unit(kind, team, x, y, yaw=0):
        state.append(f"{kind} {team} {x:.6f} {y:.6f} {elevation(x,y):.6f} 0 0 {yaw:.6f} 1")

    for team, centre, direction in ((1, 875, 1), (2, 4725, -1)):
        yaw = 0 if team == 1 else math.pi
        for dx in (-131.25, 131.25):
            for dy in (-262.5, -87.5, 87.5, 262.5):
                unit("r", team, centre+dx, 2800+dy, yaw)
        for dy in (-437.5, 437.5):
            unit("f", team, centre, 2800+dy, yaw)
            unit("e", team, centre-direction*262.5, 2800+dy, yaw)
            unit("g", team, centre+direction*350, 2800+dy, yaw)
            unit("s", team, centre+direction*175, 2800+dy*1.4, yaw)
    for y in (1575, 2800, 4025):
        unit("c g", 0, 2712.5, y)
        unit("c r", 0, 2887.5, y)
    (destination / "state").write_text("\n".join(state) + "\n", encoding="ascii", newline="\n")
    (destination / "README.txt").write_text(
        "Canadaverse Frontier\nOriginal terrain and layout by the Canadaverse revival project.\n"
        "Three broad approaches, eight repair pads per team, and midfield construction cargo.\n"
        "Uses the original game's installed terrain textures and unit models.\n", encoding="ascii", newline="\n")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="a new maps/frontier directory")
    args = parser.parse_args()
    print(generate(args.destination))
