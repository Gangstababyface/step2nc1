"""Entry point for the STEP -> NC1 converter GUI.

Usage:
    python main.py                  # launch the GUI
    python main.py file.step        # batch convert one file
    python main.py *.step           # batch convert several files
"""
from __future__ import annotations

import os
import sys


def _add_project_to_path():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def cli_convert(paths):
    from core.step_reader import load_step
    from core.section_detector import detect_section
    from core.feature_extractor import extract_features
    from core.dstv_writer import write_nc1, default_header_from_filename

    for path in paths:
        if not os.path.exists(path):
            print(f"  ! not found: {path}")
            continue
        print(f"-- converting: {path}")
        model, _ = load_step(path)
        sec = detect_section(model)
        fs = extract_features(model, sec)
        out = os.path.splitext(path)[0] + ".nc1"
        header = default_header_from_filename(path)
        write_nc1(fs, out, header=header, source_file=path)
        print(f"   {sec.profile.name}  L={sec.length_in:.2f}\"  "
              f"holes={len(fs.holes)}  -> {out}")


def main():
    _add_project_to_path()
    args = sys.argv[1:]
    if args:
        cli_convert(args)
    else:
        from gui.app import main as gui_main
        gui_main()


if __name__ == "__main__":
    main()
