"""Import original game content into a new directory outside this source tree."""
from pathlib import Path
import argparse
import re
import shutil
import zipfile


REQUIRED_SHAPES = """tank_1_s tank_2_s scout_1_s scout_2_s pulse_shell_s cargo_s
energy_1_s energy_2_s refuel_1_s refuel_2_s repair_1_s repair_2_s
flak_turret_1_s flak_turret_2_s gun_turret_1_s gun_turret_2_s""".split()


def import_content(client: Path, destination: Path, maps: list[str]) -> None:
    client, destination = client.resolve(), destination.resolve()
    source_root = Path(__file__).resolve().parents[1]
    if destination.is_relative_to(source_root):
        raise ValueError("Keep original game assets outside the source checkout")
    if destination.exists():
        raise FileExistsError(f"Choose a new content directory: {destination}")
    shapes = {}
    for archive in ("shapes.zip", "shapes2.zip"):
        with zipfile.ZipFile(client / "data" / archive) as zipped:
            for name in zipped.namelist():
                if re.fullmatch(r"[a-z0-9_]+_s", name):
                    shapes[name] = zipped.read(name)
    missing = sorted(set(REQUIRED_SHAPES) - shapes.keys())
    if missing:
        raise ValueError(f"Missing collision models: {', '.join(missing)}")
    for name in maps:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name) is None:
            raise ValueError(f"Invalid map name: {name!r}")
        for filename in ("land", "state"):
            path = client / "data" / "maps" / name / filename
            if not path.is_file():
                raise FileNotFoundError(path)
    (destination / "collision").mkdir(parents=True)
    for name, content in shapes.items():
        (destination / "collision" / name).write_bytes(content)
    for filename in ("gameplay.toml", "packets.toml"):
        shutil.copy2(source_root / "server/wulfram_server/content" / filename,
                     destination / filename)
    for name in maps:
        shutil.copytree(client / "data/maps" / name,
                        destination / "shared/data/maps" / name)
    print(f"Imported {len(shapes)} collision models and {len(maps)} maps to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--maps", nargs="+", default=["crossroads"])
    args = parser.parse_args()
    import_content(args.client, args.destination, args.maps)
