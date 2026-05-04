"""Main Tkinter GUI for the STEP -> NC1 converter."""
from __future__ import annotations

import os
import threading
from dataclasses import asdict
from tkinter import (Canvas, END, Frame, IntVar, Label, LabelFrame, Listbox,
                      Menu, OptionMenu, PhotoImage, Scrollbar, StringVar, Tk,
                      Toplevel, ttk, filedialog, messagebox)
from typing import List, Optional

from core.dstv_writer import NC1Header, default_header_from_filename, write_nc1
from core.feature_extractor import (ContourPoint, EndCut, FeatureSet, Hole,
                                     Marking, extract_features)
from core.profiles import DSTV_CODE, Profile, load_profiles, make_custom_profile
from core.section_detector import SectionResult, detect_section
from core.step_reader import load_step


# ------------------------------------------------------------------
# Helper widgets
# ------------------------------------------------------------------

def _entry_with_label(parent, label, value, width=12):
    """Pack a labeled entry into parent (using grid). Returns the StringVar."""
    var = StringVar(value=str(value))
    return var


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------

class App:
    def __init__(self, root: Tk):
        self.root = root
        root.title("STEP to NC1 Converter")
        root.geometry("1100x720")

        # State
        self.step_path: Optional[str] = None
        self.model = None
        self.section: Optional[SectionResult] = None
        self.features: Optional[FeatureSet] = None
        self.profiles: List[Profile] = load_profiles()

        self._build_menu()
        self._build_layout()

    # ---- layout --------------------------------------------------------

    def _build_menu(self):
        m = Menu(self.root)
        fm = Menu(m, tearoff=0)
        fm.add_command(label="Open STEP...", command=self.action_open,
                       accelerator="Ctrl+O")
        fm.add_command(label="Export NC1...", command=self.action_export,
                       accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="Quit", command=self.root.quit)
        m.add_cascade(label="File", menu=fm)

        em = Menu(m, tearoff=0)
        em.add_command(label="Add hole", command=self.action_add_hole)
        em.add_command(label="Add marking", command=self.action_add_marking)
        em.add_command(label="Edit selected hole", command=self.action_edit_hole)
        em.add_command(label="Delete selected hole", command=self.action_delete_hole)
        m.add_cascade(label="Features", menu=em)

        hm = Menu(m, tearoff=0)
        hm.add_command(label="DSTV NC1 reference", command=self._show_about)
        m.add_cascade(label="Help", menu=hm)
        self.root.config(menu=m)
        self.root.bind_all("<Control-o>", lambda e: self.action_open())
        self.root.bind_all("<Control-s>", lambda e: self.action_export())

    def _build_layout(self):
        # Top toolbar
        bar = Frame(self.root, padx=8, pady=6)
        bar.pack(fill="x", side="top")
        ttk.Button(bar, text="Open STEP...", command=self.action_open).pack(side="left")
        ttk.Button(bar, text="Re-detect", command=self.action_redetect).pack(side="left", padx=4)
        ttk.Button(bar, text="Export NC1...", command=self.action_export).pack(side="left", padx=4)
        self.file_label = Label(bar, text="(no file loaded)", anchor="w")
        self.file_label.pack(side="left", padx=12)

        # Main panes
        main = Frame(self.root)
        main.pack(fill="both", expand=True)

        # LEFT: profile + part info
        left = LabelFrame(main, text="Part / Profile", padx=8, pady=6)
        left.pack(side="left", fill="y", padx=8, pady=4)
        self._build_profile_panel(left)

        # CENTER: 2D preview canvas
        center = LabelFrame(main, text="Preview (top of part shown left to right)",
                            padx=4, pady=4)
        center.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.canvas = Canvas(center, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw_preview())

        # RIGHT: features
        right = LabelFrame(main, text="Features", padx=8, pady=6)
        right.pack(side="right", fill="y", padx=8, pady=4)
        self._build_features_panel(right)

        # Status bar
        self.status_var = StringVar(value="Ready. Open a STEP file to begin.")
        st = Label(self.root, textvariable=self.status_var, anchor="w",
                   bd=1, relief="sunken", padx=6)
        st.pack(side="bottom", fill="x")

    def _build_profile_panel(self, parent):
        row = 0
        Label(parent, text="Family:").grid(row=row, column=0, sticky="e", pady=2)
        self.family_var = StringVar(value="W")
        OptionMenu(parent, self.family_var,
                   "W", "C", "L", "HSS",
                   command=lambda v: self._on_family_change()).grid(
            row=row, column=1, sticky="w", pady=2)
        row += 1

        Label(parent, text="Profile:").grid(row=row, column=0, sticky="e", pady=2)
        self.profile_var = StringVar()
        self.profile_combo = ttk.Combobox(parent, textvariable=self.profile_var, width=18)
        self.profile_combo.grid(row=row, column=1, sticky="w", pady=2)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self._on_profile_select())
        row += 1

        # Editable dimensions (overrides if user wants)
        self.dim_vars = {}
        for label_text, key in (("Length (mm)", "length"),
                                  ("Depth d (mm)", "d"),
                                  ("Width bf (mm)", "bf"),
                                  ("Flange tf (mm)", "tf"),
                                  ("Web tw (mm)", "tw"),
                                  ("Wall t (mm)", "t_wall"),
                                  ("Fillet k (mm)", "k")):
            Label(parent, text=label_text).grid(row=row, column=0, sticky="e", pady=2)
            v = StringVar(value="0.00")
            ttk.Entry(parent, textvariable=v, width=12).grid(row=row, column=1, sticky="w", pady=2)
            self.dim_vars[key] = v
            row += 1

        # Header data
        sep = ttk.Separator(parent, orient="horizontal")
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        Label(parent, text="Header Data", font=("TkDefaultFont", 10, "bold")
              ).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        self.header_vars = {}
        for label_text, key, default in (("Order #", "order_number", ""),
                                            ("Drawing #", "drawing_number", ""),
                                            ("Phase #", "phase_number", "1"),
                                            ("Piece #", "piece_number", "1"),
                                            ("Material", "steel_quality", "A992"),
                                            ("Quantity", "quantity", "1")):
            Label(parent, text=label_text).grid(row=row, column=0, sticky="e", pady=2)
            v = StringVar(value=default)
            ttk.Entry(parent, textvariable=v, width=18).grid(row=row, column=1, sticky="w", pady=2)
            self.header_vars[key] = v
            row += 1

        # End cut angles
        sep2 = ttk.Separator(parent, orient="horizontal")
        sep2.grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        Label(parent, text="End Cuts (degrees)",
              font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        self.endcut_vars = {}
        for lt, k in (("Web start", "web_start"), ("Web end", "web_end"),
                       ("Flange start", "flange_start"), ("Flange end", "flange_end")):
            Label(parent, text=lt).grid(row=row, column=0, sticky="e", pady=2)
            v = StringVar(value="0.00")
            ttk.Entry(parent, textvariable=v, width=12).grid(row=row, column=1, sticky="w", pady=2)
            self.endcut_vars[k] = v
            row += 1

        self._on_family_change()  # populate profile list

    def _build_features_panel(self, parent):
        Label(parent, text="Holes", font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        f1 = Frame(parent)
        f1.pack(fill="both")
        sb1 = Scrollbar(f1, orient="vertical")
        self.holes_list = Listbox(f1, height=10, width=42, yscrollcommand=sb1.set)
        sb1.config(command=self.holes_list.yview)
        sb1.pack(side="right", fill="y")
        self.holes_list.pack(side="left", fill="both", expand=True)

        bf = Frame(parent)
        bf.pack(fill="x", pady=2)
        ttk.Button(bf, text="Add", command=self.action_add_hole).pack(side="left")
        ttk.Button(bf, text="Edit", command=self.action_edit_hole).pack(side="left", padx=2)
        ttk.Button(bf, text="Delete", command=self.action_delete_hole).pack(side="left", padx=2)

        Label(parent, text="Markings", font=("TkDefaultFont", 10, "bold")
              ).pack(anchor="w", pady=(8, 0))
        f2 = Frame(parent)
        f2.pack(fill="both")
        sb2 = Scrollbar(f2, orient="vertical")
        self.marks_list = Listbox(f2, height=6, width=42, yscrollcommand=sb2.set)
        sb2.config(command=self.marks_list.yview)
        sb2.pack(side="right", fill="y")
        self.marks_list.pack(side="left", fill="both", expand=True)

        bf2 = Frame(parent)
        bf2.pack(fill="x", pady=2)
        ttk.Button(bf2, text="Add Mark", command=self.action_add_marking).pack(side="left")
        ttk.Button(bf2, text="Delete Mark", command=self.action_delete_marking).pack(side="left", padx=2)

    # ---- file actions --------------------------------------------------

    def action_open(self):
        path = filedialog.askopenfilename(
            title="Open STEP file",
            filetypes=[("STEP files", "*.step *.stp *.STEP *.STP"),
                       ("All files", "*.*")])
        if not path:
            return
        self.load_step_file(path)

    def load_step_file(self, path: str):
        self.status_var.set(f"Loading {os.path.basename(path)}...")
        self.root.update_idletasks()
        try:
            model, _ = load_step(path)
            sec = detect_section(model)
            features = extract_features(model, sec)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse:\n{e}")
            self.status_var.set("Error.")
            return
        self.step_path = path
        self.model = model
        self.section = sec
        self.features = features
        self.file_label.config(text=os.path.basename(path))
        self._sync_section_to_ui()
        self._sync_features_to_ui()
        self.redraw_preview()
        self.status_var.set(
            f"Loaded {sec.profile.name}, length {sec.length_in:.2f}\", "
            f"{len(features.holes)} holes detected. {sec.notes}")

    def action_redetect(self):
        if not self.model:
            return
        try:
            self.section = detect_section(self.model)
            self.features = extract_features(self.model, self.section)
        except Exception as e:
            messagebox.showerror("Error", f"Re-detect failed:\n{e}")
            return
        self._sync_section_to_ui()
        self._sync_features_to_ui()
        self.redraw_preview()
        self.status_var.set(f"Re-detected: {self.section.notes}")

    def action_export(self):
        if not self.section or not self.features:
            messagebox.showwarning("Nothing to export", "Open a STEP file first.")
            return
        # Pull edits from UI back into the FeatureSet
        try:
            self._apply_ui_to_features()
        except Exception as e:
            messagebox.showerror("Invalid input", str(e))
            return
        suggested = (os.path.splitext(self.step_path or "part.step")[0] + ".nc1") \
            if self.step_path else "part.nc1"
        out = filedialog.asksaveasfilename(
            title="Save NC1",
            defaultextension=".nc1",
            initialfile=os.path.basename(suggested),
            filetypes=[("DSTV NC1", "*.nc1"), ("All files", "*.*")])
        if not out:
            return
        header = NC1Header(
            order_number=self.header_vars["order_number"].get(),
            drawing_number=self.header_vars["drawing_number"].get(),
            phase_number=self.header_vars["phase_number"].get() or "1",
            piece_number=self.header_vars["piece_number"].get() or "1",
            steel_quality=self.header_vars["steel_quality"].get() or "A992",
            quantity=int(self.header_vars["quantity"].get() or "1"),
            profile_name=self.profile_var.get() or self.section.profile.name,
            profile_code=DSTV_CODE.get(self.family_var.get(), "I"),
        )
        try:
            write_nc1(self.features, out, header=header,
                      source_file=self.step_path or "")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))
            return
        self.status_var.set(f"Wrote {out}")
        messagebox.showinfo("Exported", f"NC1 saved to\n{out}")

    # ---- feature edits -------------------------------------------------

    def action_add_hole(self):
        if not self.features:
            return
        dlg = HoleDialog(self.root, "Add hole")
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.features.holes.append(dlg.result)
            self._sync_features_to_ui()
            self.redraw_preview()

    def action_edit_hole(self):
        if not self.features: return
        sel = self.holes_list.curselection()
        if not sel:
            return
        idx = sel[0]
        h = self.features.holes[idx]
        dlg = HoleDialog(self.root, "Edit hole", hole=h)
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.features.holes[idx] = dlg.result
            self._sync_features_to_ui()
            self.redraw_preview()

    def action_delete_hole(self):
        if not self.features: return
        sel = self.holes_list.curselection()
        if not sel:
            return
        del self.features.holes[sel[0]]
        self._sync_features_to_ui()
        self.redraw_preview()

    def action_add_marking(self):
        if not self.features:
            return
        dlg = MarkingDialog(self.root, "Add marking")
        self.root.wait_window(dlg.top)
        if dlg.result:
            self.features.markings.append(dlg.result)
            self._sync_features_to_ui()
            self.redraw_preview()

    def action_delete_marking(self):
        if not self.features: return
        sel = self.marks_list.curselection()
        if not sel:
            return
        del self.features.markings[sel[0]]
        self._sync_features_to_ui()
        self.redraw_preview()

    # ---- profile / family ---------------------------------------------

    def _on_family_change(self):
        fam = self.family_var.get()
        names = sorted(p.name for p in self.profiles if p.family == fam)
        self.profile_combo["values"] = names
        if names and self.profile_var.get() not in names:
            self.profile_var.set(names[0])
            self._on_profile_select()

    def _on_profile_select(self):
        name = self.profile_var.get()
        for p in self.profiles:
            if p.name == name and p.family == self.family_var.get():
                self.dim_vars["d"].set(f"{p.d_mm:.2f}")
                self.dim_vars["bf"].set(f"{p.bf_mm:.2f}")
                self.dim_vars["tf"].set(f"{p.tf_mm:.2f}")
                self.dim_vars["tw"].set(f"{p.tw_mm:.2f}")
                self.dim_vars["t_wall"].set(f"{p.t_wall_mm:.2f}")
                self.dim_vars["k"].set(f"{p.k_mm:.2f}")
                if self.section:
                    self.section.profile = p
                    self.section.family = p.family
                self.redraw_preview()
                return

    def _sync_section_to_ui(self):
        if not self.section: return
        s = self.section
        self.family_var.set(s.family)
        self._on_family_change()  # populate combo for family
        self.profile_var.set(s.profile.name)
        self.dim_vars["length"].set(f"{s.length_in * 25.4:.2f}")
        self.dim_vars["d"].set(f"{s.profile.d_mm:.2f}")
        self.dim_vars["bf"].set(f"{s.profile.bf_mm:.2f}")
        self.dim_vars["tf"].set(f"{s.profile.tf_mm:.2f}")
        self.dim_vars["tw"].set(f"{s.profile.tw_mm:.2f}")
        self.dim_vars["t_wall"].set(f"{s.profile.t_wall_mm:.2f}")
        self.dim_vars["k"].set(f"{s.profile.k_mm:.2f}")
        if self.step_path:
            base = os.path.splitext(os.path.basename(self.step_path))[0]
            self.header_vars["order_number"].set(base)
            self.header_vars["drawing_number"].set(base)

    def _sync_features_to_ui(self):
        if not self.features:
            return
        self.holes_list.delete(0, END)
        for i, h in enumerate(self.features.holes):
            self.holes_list.insert(END,
                f"{i+1:3d}. surf={h.surface}  x={h.x_mm:7.2f}  y={h.y_mm:7.2f}  "
                f"d={h.diameter_mm:5.2f}" + (
                    f"  slot {h.slot_length_mm:.1f}@{h.slot_angle_deg:.0f}°"
                    if h.slotted else ""))
        self.marks_list.delete(0, END)
        for i, m in enumerate(self.features.markings):
            self.marks_list.insert(END,
                f"{i+1:3d}. {m.surface}  x={m.x_mm:7.2f}  y={m.y_mm:7.2f}  '{m.text}'")
        # End-cut angles
        ec = self.features.end_cuts
        self.endcut_vars["web_start"].set(f"{ec.web_start_deg:.2f}")
        self.endcut_vars["web_end"].set(f"{ec.web_end_deg:.2f}")
        self.endcut_vars["flange_start"].set(f"{ec.flange_start_deg:.2f}")
        self.endcut_vars["flange_end"].set(f"{ec.flange_end_deg:.2f}")

    def _apply_ui_to_features(self):
        if not self.section: return
        # Update profile from UI
        fam = self.family_var.get()
        try:
            d = float(self.dim_vars["d"].get())
            bf = float(self.dim_vars["bf"].get())
            tf = float(self.dim_vars["tf"].get() or "0")
            tw = float(self.dim_vars["tw"].get() or "0")
            t_wall = float(self.dim_vars["t_wall"].get() or "0")
            k = float(self.dim_vars["k"].get() or "0")
            length_mm = float(self.dim_vars["length"].get())
        except ValueError:
            raise ValueError("Dimensions must be numeric (mm)")

        # Build the profile, looking up named profile if it matches
        named = None
        for p in self.profiles:
            if p.family == fam and p.name == self.profile_var.get():
                named = p
                break
        if named is not None and abs(named.d_mm - d) < 0.5 and abs(named.bf_mm - bf) < 0.5:
            self.section.profile = named
        else:
            self.section.profile = make_custom_profile(
                fam, d=d / 25.4, bf=bf / 25.4,
                tf=tf / 25.4, tw=tw / 25.4, t_wall=t_wall / 25.4, k=k / 25.4)
        self.section.family = fam
        self.section.length_in = length_mm / 25.4

        # End cuts
        try:
            self.features.end_cuts = EndCut(
                web_start_deg=float(self.endcut_vars["web_start"].get() or 0),
                web_end_deg=float(self.endcut_vars["web_end"].get() or 0),
                flange_start_deg=float(self.endcut_vars["flange_start"].get() or 0),
                flange_end_deg=float(self.endcut_vars["flange_end"].get() or 0),
            )
        except ValueError:
            raise ValueError("End-cut angles must be numeric")

    # ---- preview drawing ----------------------------------------------

    def redraw_preview(self):
        c = self.canvas
        c.delete("all")
        if not self.section:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2,
                          text="Open a STEP file to see the part preview.",
                          fill="#888")
            return
        try:
            self._apply_ui_to_features()
        except Exception:
            pass
        s = self.section
        p = s.profile
        # Draw side view of the part with holes overlaid.
        cw = max(c.winfo_width(), 100)
        ch = max(c.winfo_height(), 100)
        margin = 30
        length_mm = s.length_in * 25.4
        depth_mm = p.d_mm
        if length_mm <= 0 or depth_mm <= 0:
            return
        sx = (cw - 2 * margin) / length_mm
        sy = (ch - 2 * margin) / max(depth_mm, 1)
        scale = min(sx, sy)
        view_w = length_mm * scale
        view_h = depth_mm * scale
        ox = (cw - view_w) / 2
        oy = (ch - view_h) / 2

        # Web silhouette
        c.create_rectangle(ox, oy, ox + view_w, oy + view_h,
                           fill="#3a4f6b", outline="#9ec5f7", width=1)

        # Flange thickness lines (top + bottom)
        if p.tf_mm > 0:
            c.create_rectangle(ox, oy, ox + view_w, oy + p.tf_mm * scale,
                                fill="#5070a0", outline="")
            c.create_rectangle(ox, oy + view_h - p.tf_mm * scale,
                                ox + view_w, oy + view_h,
                                fill="#5070a0", outline="")

        # Holes
        if self.features:
            for h in self.features.holes:
                hx = ox + h.x_mm * scale
                hy_offset = h.y_mm * scale
                if h.surface in ("v", "h"):
                    # Web hole: draw at vertical position from BOTTOM of web
                    cy = oy + view_h - hy_offset
                    color = "#ffae00" if h.surface == "v" else "#ff7000"
                elif h.surface == "o":
                    # Top flange - draw on top edge
                    cy = oy + p.tf_mm * scale * 0.5
                    color = "#7ce97c"
                elif h.surface == "u":
                    cy = oy + view_h - p.tf_mm * scale * 0.5
                    color = "#7ce97c"
                else:
                    cy = oy + view_h / 2
                    color = "#cccccc"
                rad = max(2, (h.diameter_mm / 2) * scale)
                c.create_oval(hx - rad, cy - rad, hx + rad, cy + rad,
                              outline=color, width=2)

        # Length/depth labels
        c.create_text(ox + view_w / 2, oy - 10,
                      text=f"L = {length_mm:.1f} mm   ({s.length_in:.2f}\")",
                      fill="#dddddd")
        c.create_text(ox - 8, oy + view_h / 2,
                      text=f"d = {depth_mm:.1f}", angle=90, fill="#dddddd")
        c.create_text(ox + view_w + 8, oy + view_h / 2,
                      text=f"{p.name}", angle=90, fill="#dddddd")

    # ---- about ---------------------------------------------------------

    def _show_about(self):
        messagebox.showinfo("DSTV NC1",
            "DSTV NC1 is the standard exchange format for CNC structural-steel\n"
            "machines (drilling, sawing, marking, plasma).\n\n"
            "Blocks: ST (header), BO (holes), AK (outer contour), IK (inner),\n"
            "SI (text marking), PU (punch marks), EN (end).\n\n"
            "Surface codes: v=web front, h=web back, o=top flange, u=bottom.")


# ------------------------------------------------------------------
# Hole dialog
# ------------------------------------------------------------------

class HoleDialog:
    def __init__(self, parent, title, hole: Optional[Hole] = None):
        self.result: Optional[Hole] = None
        top = self.top = Toplevel(parent)
        top.title(title)
        top.transient(parent)
        top.grab_set()

        frm = Frame(top, padx=10, pady=10)
        frm.pack(fill="both", expand=True)

        defaults = hole or Hole(surface="v", x_mm=0, y_mm=0, diameter_mm=22.0)

        Label(frm, text="Surface (v/h/o/u):").grid(row=0, column=0, sticky="e")
        self.v_surface = StringVar(value=defaults.surface)
        OptionMenu(frm, self.v_surface, "v", "o", "u", "h").grid(row=0, column=1, sticky="w")
        Label(frm, text="X (mm, along length)").grid(row=1, column=0, sticky="e")
        self.v_x = StringVar(value=f"{defaults.x_mm:.2f}")
        ttk.Entry(frm, textvariable=self.v_x).grid(row=1, column=1)
        Label(frm, text="Y (mm, in surface)").grid(row=2, column=0, sticky="e")
        self.v_y = StringVar(value=f"{defaults.y_mm:.2f}")
        ttk.Entry(frm, textvariable=self.v_y).grid(row=2, column=1)
        Label(frm, text="Diameter (mm)").grid(row=3, column=0, sticky="e")
        self.v_d = StringVar(value=f"{defaults.diameter_mm:.2f}")
        ttk.Entry(frm, textvariable=self.v_d).grid(row=3, column=1)

        # Slot
        self.v_slot = IntVar(value=1 if defaults.slotted else 0)
        ttk.Checkbutton(frm, text="Slotted", variable=self.v_slot).grid(row=4, column=0, columnspan=2, sticky="w")
        Label(frm, text="Slot length (mm)").grid(row=5, column=0, sticky="e")
        self.v_sl = StringVar(value=f"{defaults.slot_length_mm:.2f}")
        ttk.Entry(frm, textvariable=self.v_sl).grid(row=5, column=1)
        Label(frm, text="Slot angle (deg)").grid(row=6, column=0, sticky="e")
        self.v_sa = StringVar(value=f"{defaults.slot_angle_deg:.2f}")
        ttk.Entry(frm, textvariable=self.v_sa).grid(row=6, column=1)

        bf = Frame(top, pady=8)
        bf.pack(side="bottom", fill="x")
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right", padx=8)
        ttk.Button(bf, text="Cancel", command=top.destroy).pack(side="right")

    def _ok(self):
        try:
            self.result = Hole(
                surface=self.v_surface.get(),
                x_mm=float(self.v_x.get()),
                y_mm=float(self.v_y.get()),
                diameter_mm=float(self.v_d.get()),
                slotted=bool(self.v_slot.get()),
                slot_length_mm=float(self.v_sl.get()),
                slot_angle_deg=float(self.v_sa.get()),
            )
        except ValueError as e:
            messagebox.showerror("Bad input", str(e))
            return
        self.top.destroy()


# ------------------------------------------------------------------
# Marking dialog
# ------------------------------------------------------------------

class MarkingDialog:
    def __init__(self, parent, title, marking: Optional[Marking] = None):
        self.result: Optional[Marking] = None
        top = self.top = Toplevel(parent)
        top.title(title)
        top.transient(parent)
        top.grab_set()
        frm = Frame(top, padx=10, pady=10)
        frm.pack(fill="both", expand=True)
        defaults = marking or Marking(surface="v", x_mm=0, y_mm=0)
        Label(frm, text="Surface").grid(row=0, column=0, sticky="e")
        self.v_surface = StringVar(value=defaults.surface)
        OptionMenu(frm, self.v_surface, "v", "o", "u", "h").grid(row=0, column=1, sticky="w")
        Label(frm, text="X (mm)").grid(row=1, column=0, sticky="e")
        self.v_x = StringVar(value=f"{defaults.x_mm:.2f}"); ttk.Entry(frm, textvariable=self.v_x).grid(row=1, column=1)
        Label(frm, text="Y (mm)").grid(row=2, column=0, sticky="e")
        self.v_y = StringVar(value=f"{defaults.y_mm:.2f}"); ttk.Entry(frm, textvariable=self.v_y).grid(row=2, column=1)
        Label(frm, text="Angle (deg)").grid(row=3, column=0, sticky="e")
        self.v_a = StringVar(value=f"{defaults.angle_deg:.2f}"); ttk.Entry(frm, textvariable=self.v_a).grid(row=3, column=1)
        Label(frm, text="Text").grid(row=4, column=0, sticky="e")
        self.v_t = StringVar(value=defaults.text); ttk.Entry(frm, textvariable=self.v_t, width=24).grid(row=4, column=1)
        bf = Frame(top, pady=8); bf.pack(side="bottom", fill="x")
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right", padx=8)
        ttk.Button(bf, text="Cancel", command=top.destroy).pack(side="right")

    def _ok(self):
        try:
            self.result = Marking(
                surface=self.v_surface.get(),
                x_mm=float(self.v_x.get()),
                y_mm=float(self.v_y.get()),
                angle_deg=float(self.v_a.get()),
                text=self.v_t.get(),
            )
        except ValueError as e:
            messagebox.showerror("Bad input", str(e))
            return
        self.top.destroy()


def main():
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
