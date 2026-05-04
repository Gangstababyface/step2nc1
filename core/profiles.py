"""AISC profile database loader + cross-section matching."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# DSTV profile codes (per the DSTV 1992 NC1 spec)
DSTV_CODE = {
    "W": "I",     # I-beam (and W, S, HP)
    "C": "U",     # U-channel
    "L": "L",     # equal/unequal leg angle
    "HSS": "M",   # rectangular hollow (Mannesmann)
    "HSS_R": "RU",  # round hollow (rohr-rund)
    "PLATE": "B", # plate / flat bar
}


@dataclass
class Profile:
    name: str
    family: str          # 'W', 'C', 'L', 'HSS'
    d: float             # overall depth (inches)
    bf: float            # flange/leg width (inches)
    tf: float            # flange thickness (inches), or 0 for HSS/L
    tw: float            # web thickness (inches), or 0 for HSS/L
    t_wall: float        # wall thickness (HSS / L)
    k: float             # fillet radius (inches)
    weight_per_ft: float
    dstv_code: str

    @property
    def d_mm(self) -> float: return self.d * 25.4
    @property
    def bf_mm(self) -> float: return self.bf * 25.4
    @property
    def tf_mm(self) -> float: return self.tf * 25.4
    @property
    def tw_mm(self) -> float: return self.tw * 25.4
    @property
    def t_wall_mm(self) -> float: return self.t_wall * 25.4
    @property
    def k_mm(self) -> float: return self.k * 25.4
    @property
    def kg_per_m(self) -> float: return self.weight_per_ft * 1.488


def load_profiles(path: Optional[str] = None) -> List[Profile]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "aisc_profiles.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out: List[Profile] = []
    for fam in ("W", "C", "L", "HSS"):
        if fam not in raw:
            continue
        for name, p in raw[fam].items():
            if fam in ("L", "HSS"):
                t = float(p.get("t", 0.0))
                tf = tw = 0.0
                t_wall = t
            else:
                tf = float(p.get("tf", 0.0))
                tw = float(p.get("tw", 0.0))
                t_wall = 0.0
            out.append(Profile(
                name=name,
                family=fam,
                d=float(p["d"]),
                bf=float(p["bf"]),
                tf=tf,
                tw=tw,
                t_wall=t_wall,
                k=float(p.get("k", 0.0)),
                weight_per_ft=float(p.get("w", 0.0)),
                dstv_code=DSTV_CODE[fam],
            ))
    return out


def match_profile(family: str, depth_in: float, width_in: float,
                   web_in: float = 0.0, flange_in: float = 0.0,
                   wall_in: float = 0.0,
                   profiles: Optional[List[Profile]] = None,
                   tol_in: float = 0.06) -> Optional[Profile]:
    """Find best AISC match for given dimensions (inches)."""
    if profiles is None:
        profiles = load_profiles()
    best: Optional[Profile] = None
    best_err = math.inf
    for p in profiles:
        if p.family != family:
            continue
        err = (p.d - depth_in) ** 2 + (p.bf - width_in) ** 2
        if family in ("W", "C") and flange_in > 0:
            err += 4.0 * (p.tf - flange_in) ** 2
        if family in ("W", "C") and web_in > 0:
            err += 4.0 * (p.tw - web_in) ** 2
        if family in ("L", "HSS") and wall_in > 0:
            err += 4.0 * (p.t_wall - wall_in) ** 2
        if err < best_err:
            best_err = err
            best = p
    if best is None:
        return None
    # accept only if reasonably close on depth/width
    if abs(best.d - depth_in) > tol_in * max(2.0, depth_in / 4) or \
       abs(best.bf - width_in) > tol_in * max(2.0, width_in / 4):
        # too far - return as None so caller can fall back to a custom section
        return None
    return best


def make_custom_profile(family: str, d: float, bf: float, tf: float = 0.0,
                         tw: float = 0.0, t_wall: float = 0.0, k: float = 0.0,
                         length_in: float = 0.0) -> Profile:
    """Create an unnamed profile from raw measurements."""
    if family == "W":
        name = f"W{d:.2f}X{bf:.2f}".replace(".00", "").replace(".", "_")
    elif family == "C":
        name = f"C{d:.2f}X{bf:.2f}".replace(".00", "").replace(".", "_")
    elif family == "L":
        name = f"L{d:.2f}X{bf:.2f}X{t_wall:.3f}".replace(".000", "").replace(".", "_")
    elif family == "HSS":
        name = f"HSS{d:.2f}X{bf:.2f}X{t_wall:.3f}".replace(".000", "").replace(".", "_")
    else:
        name = f"PL{d:.2f}X{bf:.2f}"
    # estimate weight from cross-section area * 0.2836 lb/in^3 * 12 in/ft
    if family == "W":
        area = bf * d - (bf - tw) * (d - 2 * tf)  # outer minus subtractive web cutouts
    elif family == "C":
        area = bf * d - (bf - tw) * (d - 2 * tf)
    elif family == "L":
        area = t_wall * (d + bf - t_wall)
    elif family == "HSS":
        area = bf * d - (bf - 2 * t_wall) * (d - 2 * t_wall)
    else:
        area = bf * d
    weight_per_ft = max(area, 0.0) * 0.2836 * 12.0
    return Profile(
        name=name, family=family, d=d, bf=bf, tf=tf, tw=tw,
        t_wall=t_wall, k=k, weight_per_ft=weight_per_ft, dstv_code=DSTV_CODE[family],
    )
