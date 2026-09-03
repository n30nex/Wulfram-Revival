from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


JetPoint = tuple[float, float, float, float, float, float, int]


@dataclass(frozen=True, slots=True)
class JetShapeBlock:
    points: tuple[JetPoint, ...]
    trailing_scalar: float = 0.0


@dataclass(frozen=True, slots=True)
class JetLayoutProfile:
    name: str
    description: str
    tank_red: JetShapeBlock
    tank_blue: JetShapeBlock
    scout_red: JetShapeBlock
    scout_blue: JetShapeBlock

    @property
    def identity(self) -> str:
        encoded = json.dumps(
            {
                "tank_red": (self.tank_red.points, self.tank_red.trailing_scalar),
                "tank_blue": (self.tank_blue.points, self.tank_blue.trailing_scalar),
                "scout_red": (self.scout_red.points, self.scout_red.trailing_scalar),
                "scout_blue": (self.scout_blue.points, self.scout_blue.trailing_scalar),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()[:16]


def _fixed1616(value: float) -> float:
    """Return the exact value the client receives after wire quantization."""
    return round(value * 65536.0) / 65536.0


def _point(x: float, y: float, z: float) -> JetPoint:
    return (x, y, z, 0.0, 0.0, -1.0, 0)


def _block(points: tuple[tuple[float, float, float], ...]) -> JetShapeBlock:
    return JetShapeBlock(tuple(_point(*point) for point in points))


def _symmetric_block(
    full_extents: tuple[float, float, float],
    *,
    z_override: float | None = None,
    xy_inset: float = 0.0,
) -> JetShapeBlock:
    x = _fixed1616(full_extents[0] * 0.45 - xy_inset)
    y = _fixed1616(full_extents[1] * 0.45 - xy_inset)
    z = _fixed1616(
        full_extents[2] * -0.30 if z_override is None else z_override
    )
    return _block((
        (+x, -y, z),
        (+x, +y, z),
        (-x, -y, z),
        (-x, +y, z),
    ))


# Exact signed-16.16 bounds from both mesh records in the current Wulfram II
# collision assets. Tank Red and Blue share geometry; Scout variants do not.
_TANK_FULL_EXTENTS = (13.559906005859375, 9.65728759765625, 3.70416259765625)
_SCOUT_RED_FULL_EXTENTS = (9.876220703125, 8.28326416015625, 2.8673095703125)
_SCOUT_BLUE_FULL_EXTENTS = (11.09765625, 7.7896728515625, 2.45428466796875)

# Preserve Wulfram 1's exact absolute probe-to-hull-bottom clearance when
# applying its horizontal bounds ratios to the Wulfram II Tank hull.
_WULFRAM1_TANK_BOTTOM_Z = -1.3065032958984375
_WULFRAM1_TANK_PROBE_Z = -0.783905029296875
_WULFRAM2_TANK_BOTTOM_Z = -1.852081298828125
_TANK_CLEARANCE_PROBE_Z = _WULFRAM2_TANK_BOTTOM_Z + (
    _WULFRAM1_TANK_PROBE_Z - _WULFRAM1_TANK_BOTTOM_Z
)
_TANK_MIDPOINT_PROBE_Z = _fixed1616(
    (_TANK_CLEARANCE_PROBE_Z + _WULFRAM2_TANK_BOTTOM_Z) * 0.5
)


PRE_RATIO_PROFILE = JetLayoutProfile(
    name="pre-ratio",
    description="Four selected bottom-plane vertices used before bounds-ratio testing.",
    tank_red=_block((
        (+3.334503173828125, -2.5984954833984375, -1.3065032958984375),
        (+3.334503173828125, +2.5984954833984375, -1.3065032958984375),
        (-4.6044921875, -2.5984954833984375, -1.3065032958984375),
        (-4.6044921875, +2.5984954833984375, -1.3065032958984375),
    )),
    tank_blue=_block((
        (+2.8860015869140625, -2.47650146484375, -1.149993896484375),
        (+2.8860015869140625, +2.47650146484375, -1.149993896484375),
        (-4.5619964599609375, -2.47650146484375, -1.149993896484375),
        (-4.5619964599609375, +2.47650146484375, -1.149993896484375),
    )),
    scout_red=_block((
        (+1.858428955078125, -4.141632080078125, -1.43365478515625),
        (+1.858428955078125, +4.141632080078125, -1.43365478515625),
        (-2.07080078125, -4.141632080078125, -1.43365478515625),
        (-2.07080078125, +4.141632080078125, -1.43365478515625),
    )),
    scout_blue=_block((
        (+1.173797607421875, -3.89483642578125, -1.227142333984375),
        (+1.173797607421875, +3.89483642578125, -1.227142333984375),
        (-5.548828125, -3.89483642578125, -1.227142333984375),
        (-5.548828125, +3.89483642578125, -1.227142333984375),
    )),
)

W1_RATIO_PROFILE = JetLayoutProfile(
    name="w1-ratio",
    description="Wulfram 1 bounds ratios applied independently to each Wulfram II shape.",
    tank_red=_symmetric_block(_TANK_FULL_EXTENTS),
    tank_blue=_symmetric_block(_TANK_FULL_EXTENTS),
    scout_red=_symmetric_block(_SCOUT_RED_FULL_EXTENTS),
    scout_blue=_symmetric_block(_SCOUT_BLUE_FULL_EXTENTS),
)

W1_CLEARANCE_PROFILE = JetLayoutProfile(
    name="w1-clearance",
    description="W1-ratio X/Y with Wulfram 1's absolute Tank hull clearance.",
    tank_red=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_CLEARANCE_PROBE_Z,
    ),
    tank_blue=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_CLEARANCE_PROBE_Z,
    ),
    scout_red=_symmetric_block(_SCOUT_RED_FULL_EXTENTS),
    scout_blue=_symmetric_block(_SCOUT_BLUE_FULL_EXTENTS),
)

W1_INSET_040_PROFILE = JetLayoutProfile(
    name="w1-inset-0.40",
    description="W1-clearance Tank probes moved inward by 0.40 on X and Y.",
    tank_red=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_CLEARANCE_PROBE_Z,
        xy_inset=0.40,
    ),
    tank_blue=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_CLEARANCE_PROBE_Z,
        xy_inset=0.40,
    ),
    scout_red=_symmetric_block(_SCOUT_RED_FULL_EXTENTS),
    scout_blue=_symmetric_block(_SCOUT_BLUE_FULL_EXTENTS),
)

W1_MIDPOINT_PROFILE = JetLayoutProfile(
    name="w1-midpoint",
    description="W1-ratio X/Y with Tank Z halfway from W1 clearance to hull bottom.",
    tank_red=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_MIDPOINT_PROBE_Z,
    ),
    tank_blue=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_TANK_MIDPOINT_PROBE_Z,
    ),
    scout_red=_symmetric_block(_SCOUT_RED_FULL_EXTENTS),
    scout_blue=_symmetric_block(_SCOUT_BLUE_FULL_EXTENTS),
)

W1_BOTTOM_PLANE_PROFILE = JetLayoutProfile(
    name="w1-bottom-plane",
    description="W1-ratio X/Y with Tank probes on the Wulfram II hull bottom plane.",
    tank_red=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_WULFRAM2_TANK_BOTTOM_Z,
    ),
    tank_blue=_symmetric_block(
        _TANK_FULL_EXTENTS,
        z_override=_WULFRAM2_TANK_BOTTOM_Z,
    ),
    scout_red=_symmetric_block(_SCOUT_RED_FULL_EXTENTS),
    scout_blue=_symmetric_block(_SCOUT_BLUE_FULL_EXTENTS),
)

JET_LAYOUT_PROFILES = {
    profile.name: profile
    for profile in (
        PRE_RATIO_PROFILE,
        W1_RATIO_PROFILE,
        W1_CLEARANCE_PROFILE,
        W1_INSET_040_PROFILE,
        W1_MIDPOINT_PROFILE,
        W1_BOTTOM_PLANE_PROFILE,
    )
}
JET_LAYOUT_PROFILE_NAMES = tuple(JET_LAYOUT_PROFILES)
DEFAULT_JET_LAYOUT_PROFILE = W1_CLEARANCE_PROFILE.name


def get_jet_layout_profile(name: str) -> JetLayoutProfile:
    try:
        return JET_LAYOUT_PROFILES[name]
    except KeyError as error:
        choices = ", ".join(JET_LAYOUT_PROFILE_NAMES)
        raise ValueError(
            f"unknown jet-layout profile {name!r}; expected one of: {choices}"
        ) from error
