#!/usr/bin/env python3
# Parametric case for the Songbird approval token:
#   base  - cradles an ESP32-S3-DevKitC-1, open dual-USB-C end
#   lid   - friction-fits on top, holds the 0.96" OLED behind a window
#
# Units: millimetres. Edit the PARAMS block and re-run to retune the fit.
# Outputs base.stl, lid.stl + preview PNGs next to this file.
import os
import numpy as np
import trimesh

D = os.path.dirname(os.path.abspath(__file__))

# ======================= PARAMS =======================
# ESP32-S3-DevKitC-1 board
board_l   = 76.0      # length  (+3mm)  <-- measure yours and set exactly
board_w   = 25.5      # width                          <-- measure yours and set exactly
board_t   = 1.6       # PCB thickness

# fit / shell
tol       = 0.4       # clearance around the board (each side)
wall      = 2.0       # outer wall thickness
floor_t   = 1.5       # base floor thickness
under_gap = 3.0       # clearance UNDER the board (solder tails). Bump to ~9 if
                      # male header pins point DOWN.
ledge     = 2.0       # shelf width the board rests on
shelf_t   = 2.0       # shelf thickness

# OLED rests directly on top of the board, on the ESP32 shield can.
oled_standoff = 3.2   # chip-can height the OLED back rests on, above board top
oled_body     = 4.0   # OLED module thickness (back driver -> front glass)
wire_gap  = oled_standoff + oled_body   # gap above board = OLED stack height

# dual USB-C cutout at the x=0 end
usb_cut_w = 24.0      # spans both USB-C connectors
usb_cut_h = 7.0       # height above the PCB top

# lid
plate_t   = 2.0       # top plate thickness
lip_h     = 5.0       # how far the lid lip drops into the base
lip_wall  = 1.5       # lip wall thickness
lip_tol   = 0.3       # lip clearance inside the cavity (per side)

# 0.96" OLED module
oled_w    = 27.4      # module outer (along board length, X)
oled_h    = 27.4      # module outer (across, Y)
oled_tol  = 0.4
oled_win_w = 16.5     # screen window along the case LENGTH (short screen axis)
oled_win_h = 25.0     # screen window across the case WIDTH  (long screen axis, horizontal)
oled_win_yoff = 0.0   # shift window toward header edge if needed
frame_t   = 0.8       # thin frame the module front rests against
oled_center_x = None  # None = at the FAR end from USB (matches the build); else x of OLED centre
oled_far_gap  = 3.0   # gap from the OLED's far edge to the far inner wall
# ======================================================

EPS = 0.05
width_pad = 4.0                          # extra width (+3mm over OLED clearance)
inner_l = board_l + 2 * tol
# widen to clear the OLED (27.4 mm > board 25.5 mm) plus a little margin
inner_w = max(board_w, oled_w) + 2 * tol + width_pad
out_l = inner_l + 2 * wall
out_w = inner_w + 2 * wall
# shelves reach under the (narrower) centred board's edges
ledge = (inner_w - board_w) / 2.0 + 2.0
brd_bottom = floor_t + under_gap        # z of board underside
base_h = floor_t + under_gap + board_t + wire_gap
if oled_center_x is None:
    # USB cutout is at x=0; OLED sits at the opposite (far) end, as built
    oled_center_x = out_l - wall - oled_far_gap - oled_w / 2.0


def box(sx, sy, sz, cx, cy, cz):
    b = trimesh.creation.box(extents=[sx, sy, sz])
    b.apply_translation([cx, cy, cz])
    return b


def build_base():
    outer = box(out_l, out_w, base_h, out_l/2, out_w/2, base_h/2)
    cavity = box(inner_l, inner_w, base_h, out_l/2, out_w/2,
                 floor_t + base_h/2 + EPS)
    base = outer.difference(cavity)

    # shelves along the two long walls for the board to rest on
    sh_cz = brd_bottom - shelf_t/2
    left = box(inner_l, ledge, shelf_t, out_l/2, wall + ledge/2, sh_cz)
    right = box(inner_l, ledge, shelf_t, out_l/2, out_w - wall - ledge/2, sh_cz)
    base = base.union(left).union(right)

    # dual USB-C cutout through the x=0 end wall
    usb = box(wall*3, usb_cut_w, board_t + usb_cut_h,
              wall/2, out_w/2, brd_bottom + (board_t + usb_cut_h)/2 - 0.5)
    base = base.difference(usb)
    return base


def build_lid():
    plate = box(out_l, out_w, plate_t, out_l/2, out_w/2, base_h + plate_t/2)

    # lip that drops into the base cavity (friction fit)
    lo_l, lo_w = inner_l - 2*lip_tol, inner_w - 2*lip_tol
    lip_out = box(lo_l, lo_w, lip_h, out_l/2, out_w/2, base_h - lip_h/2)
    lip_in = box(lo_l - 2*lip_wall, lo_w - 2*lip_wall, lip_h + EPS,
                 out_l/2, out_w/2, base_h - lip_h/2)
    lip = lip_out.difference(lip_in)
    lid = plate.union(lip)

    # OLED pocket on the underside + screen window through the top
    pocket_depth = plate_t - frame_t
    pocket = box(oled_w + oled_tol, oled_h + oled_tol, pocket_depth + EPS,
                 oled_center_x, out_w/2, base_h + pocket_depth/2)
    lid = lid.difference(pocket)
    window = box(oled_win_w, oled_win_h, plate_t + 2,
                 oled_center_x, out_w/2 + oled_win_yoff, base_h + plate_t/2)
    lid = lid.difference(window)
    return lid


def preview(meshes_colors, path, elev=28, azim=-60):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    fig = plt.figure(figsize=(7, 5))
    ax = fig.add_subplot(111, projection="3d")
    allpts = []
    for m, c in meshes_colors:
        tris = m.vertices[m.faces]
        allpts.append(m.vertices)
        pc = Poly3DCollection(tris, alpha=1.0, facecolor=c,
                              edgecolor=(0, 0, 0, 0.12), linewidths=0.2)
        ax.add_collection3d(pc)
    pts = np.vstack(allpts)
    mid = pts.mean(0)
    r = (pts.max(0) - pts.min(0)).max() / 2
    ax.set_xlim(mid[0]-r, mid[0]+r)
    ax.set_ylim(mid[1]-r, mid[1]+r)
    ax.set_zlim(mid[2]-r, mid[2]+r)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    base = build_base()
    lid = build_lid()
    base.export(os.path.join(D, "base.stl"))
    lid.export(os.path.join(D, "lid.stl"))
    print("base watertight:", base.is_watertight, "vol_cm3=%.1f" % (base.volume/1000))
    print("lid  watertight:", lid.is_watertight, "vol_cm3=%.1f" % (lid.volume/1000))
    print("overall footprint: %.1f x %.1f mm, base_h=%.1f" % (out_l, out_w, base_h))

    preview([(base, "#7bb0ff")], os.path.join(D, "preview_base.png"))
    preview([(lid, "#ffd166")], os.path.join(D, "preview_lid.png"), elev=-35, azim=-60)
    # assembled: lid sitting on base
    preview([(base, "#7bb0ff"), (lid, "#ffd166")],
            os.path.join(D, "preview_assembled.png"))
    print("wrote STLs + previews")
