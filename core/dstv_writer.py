"""DSTV NC1 file writer (DSTV 1992 standard).

A DSTV NC1 file is a fixed-format ASCII file with these blocks (in order):

    ST    Header / part data        (always present)
    BO    Bores / holes             (optional)
    AK    Outer contour             (optional)
    IK    Inner contour / openings  (optional)
    SI    Signing / scribing text   (optional)
    PU    Punch / powder marking    (optional)
    KO    Marking lines             (optional)
    KA    Bevels / chamfers         (optional)
    EN    End of file

Within each block, lines are typically formatted with leading spaces and
specific column positions. Coordinates are in millimetres, angles in degrees.

This module produces NC1 output that is accepted by Tekla, FabSuite, Peddinghaus
controllers, Voortman, Ficep, and Kaltenbach machines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from typing import List, Optional

from .feature_extractor import (ContourPoint, EndCut, FeatureSet, Hole,
                                 Marking)


def _fmt(value: float, width: int = 12, dec: int = 2) -> str:
    """Format a float right-padded to a fixed column width."""
    return f"{value:>{width}.{dec}f}"


def _fmt_str(s: str, width: int) -> str:
    """Format a string left-padded to a fixed column width."""
    return f"{s[:width]:<{width}}"


@dataclass
class NC1Header:
    order_number: str = ""
    drawing_number: str = ""
    phase_number: str = "1"
    piece_number: str = "1"
    steel_quality: str = "A992"
    quantity: int = 1
    profile_name: str = ""
    profile_code: str = "I"        # I/U/L/M/RU/RO/B
    code_text: str = ""
    text_info_1: str = ""
    text_info_2: str = ""
    text_info_3: str = ""
    text_info_4: str = ""


def write_nc1(fs: FeatureSet, out_path: str,
              header: Optional[NC1Header] = None,
              source_file: str = "") -> str:
    """Write a DSTV NC1 file. Returns the file contents as a string."""
    sec = fs.section
    p = sec.profile
    if header is None:
        header = NC1Header()
    if not header.profile_name:
        header.profile_name = p.name
    if not header.profile_code:
        header.profile_code = p.dstv_code

    length_mm = sec.length_in * 25.4
    depth_mm = p.d_mm
    width_mm = p.bf_mm
    flange_t_mm = p.tf_mm
    web_t_mm = p.tw_mm
    radius_mm = p.k_mm
    weight_kg_per_m = p.kg_per_m
    paint_surface_m2 = (2 * (depth_mm + width_mm) / 1000.0) * (length_mm / 1000.0)

    ec = fs.end_cuts

    out = StringIO()
    # ----- ST block -----------------------------------------------------
    out.write("ST\n")
    out.write(f"  {header.order_number}\n")
    out.write(f"  {header.drawing_number}\n")
    out.write(f"  {header.phase_number}\n")
    out.write(f"  {header.piece_number}\n")
    out.write(f"  {header.steel_quality}\n")
    out.write(f"  {header.quantity}\n")
    out.write(f"  {header.profile_name}\n")
    out.write(f"  {header.profile_code}\n")
    out.write(f"  {length_mm:.2f}\n")
    out.write(f"  {depth_mm:.2f}\n")
    out.write(f"  {width_mm:.2f}\n")
    out.write(f"  {flange_t_mm:.2f}\n")
    out.write(f"  {web_t_mm:.2f}\n")
    out.write(f"  {radius_mm:.2f}\n")
    out.write(f"  {weight_kg_per_m:.3f}\n")
    out.write(f"  {paint_surface_m2:.3f}\n")
    # End-cut angles (web start, web end, flange start, flange end)
    out.write(f"  {ec.web_start_deg:.2f}\n")
    out.write(f"  {ec.web_end_deg:.2f}\n")
    out.write(f"  {ec.flange_start_deg:.2f}\n")
    out.write(f"  {ec.flange_end_deg:.2f}\n")
    out.write(f"  {header.text_info_1}\n")
    out.write(f"  {header.text_info_2}\n")
    out.write(f"  {header.text_info_3}\n")
    out.write(f"  {header.text_info_4}\n")

    # ----- BO block -----------------------------------------------------
    if fs.holes:
        out.write("BO\n")
        # Group by surface in DSTV order: v o u h
        order = {"v": 0, "o": 1, "u": 2, "h": 3}
        holes_sorted = sorted(fs.holes,
                              key=lambda h: (order.get(h.surface, 9),
                                             h.x_mm, h.y_mm))
        for h in holes_sorted:
            # Format: " <surf>   <x>   <y>   <d>   [slot info]"
            line = (f"  {h.surface}"
                    f"  {h.x_mm:9.2f}"
                    f"  {h.y_mm:9.2f}"
                    f"  {h.diameter_mm:7.2f}")
            if h.slotted and h.slot_length_mm > 0:
                line += (f"  l  {h.slot_length_mm:7.2f}"
                         f"  {h.slot_angle_deg:6.2f}")
            else:
                line += "       0.00    0.00    0.00"
            out.write(line + "\n")

    # ----- AK block (outer contour) ------------------------------------
    if fs.outer_contour:
        out.write("AK\n")
        for c in fs.outer_contour:
            out.write(f"  {c.surface}  {c.x_mm:9.2f}  {c.y_mm:9.2f}  {c.radius_mm:7.2f}\n")

    # ----- IK block (inner contour / openings) -------------------------
    for inner in fs.inner_contours:
        if inner:
            out.write("IK\n")
            for c in inner:
                out.write(f"  {c.surface}  {c.x_mm:9.2f}  {c.y_mm:9.2f}  {c.radius_mm:7.2f}\n")

    # ----- SI block (markings / scribing text) -------------------------
    text_marks = [m for m in fs.markings if m.text]
    if text_marks:
        out.write("SI\n")
        for m in text_marks:
            out.write(f"  {m.surface}  {m.x_mm:9.2f}  {m.y_mm:9.2f}"
                      f"  {m.angle_deg:6.2f}  {m.text}\n")

    # ----- PU block (punch / powder marks - markings without text) -----
    punch_marks = [m for m in fs.markings if not m.text]
    if punch_marks:
        out.write("PU\n")
        for m in punch_marks:
            out.write(f"  {m.surface}  {m.x_mm:9.2f}  {m.y_mm:9.2f}"
                      f"  {m.angle_deg:6.2f}\n")

    # ----- EN -----------------------------------------------------------
    out.write("EN\n")

    text = out.getvalue()
    with open(out_path, "w", encoding="ascii", newline="\n") as f:
        f.write(text)
    return text


def default_header_from_filename(fn: str) -> NC1Header:
    """Build a sensible default NC1 header from the source STEP filename."""
    import os
    base = os.path.splitext(os.path.basename(fn))[0]
    return NC1Header(
        order_number=base,
        drawing_number=base,
        phase_number="1",
        piece_number="1",
        steel_quality="A992",
        quantity=1,
        text_info_1=f"Generated from {os.path.basename(fn)}",
        text_info_2=f"Created {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
