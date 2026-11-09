"""Draw the G1 native PCB plan view from the geometry the saved board holds.

This is a *reconstruction*, not an editor screenshot: the input is
`g1_pads.json`, dumped from `dcx_main_board_g1.eprj2` through
`pcb_PrimitivePad.getAll()` (X/Y in mil, Cartesian Y up), the component
anchors, the board outline and the five TBD rectangles plus the eight DOT
marks read back from `pcb_PrimitivePolyline.getAll()`.

    python hardware/dcx_main/g1/make_g1_layout_svg.py

Writes `g1_layout.svg` next to this file.  It is review evidence for G1 only —
it is not a Gerber, a DRC report, or a manufacturability claim.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIL = 39.37007874015748  # mil per mm
MARGIN_MM = 4.0

# Net classes only affect the fill colour; they carry no electrical meaning here.
POWER = {"VOUT", "PGND", "VIN_P", "SW", "SEC1_A", "SEC1_B", "SEC2_A", "SEC2_B"}
SECONDARY = {"SEC3_A", "SEC3_B", "SEC4_A", "SEC4_B", "PRI_T1", "PRI_12", "CR_CT", "CT_LR"}


def net_fill(net: str) -> str:
    if net == "VOUT":
        return "#c0392b"
    if net == "PGND":
        return "#2c3e50"
    if net in POWER:
        return "#e67e22"
    if net in SECONDARY:
        return "#8e44ad"
    if net.startswith("VG") or net.startswith("VD"):
        return "#2980b9"
    return "#7f8c8d"


def pad_size(shape: list | None) -> tuple[float, float, list]:
    """Pad extents in mm; an unknown shape falls back to a 0.6 mm dot."""
    shape = shape or ["RECT", 20, 20, 0]
    if shape[0] == "POLYGON":
        nums = [v for v in shape[1] if isinstance(v, (int, float))]
        xs, ys = nums[0::2], nums[1::2]
        return (max(xs) - min(xs)) / MIL, (max(ys) - min(ys)) / MIL, shape
    if len(shape) > 2 and isinstance(shape[1], (int, float)) and isinstance(shape[2], (int, float)):
        return shape[1] / MIL, shape[2] / MIL, shape
    return 0.6, 0.6, ["ELLIPSE", 0.6 * MIL, 0.6 * MIL]


def pad_shape_svg(shape: list, w: float, h: float) -> str:
    if shape[0] == "ELLIPSE":
        return f'<ellipse cx="0" cy="0" rx="{w / 2:.3f}" ry="{h / 2:.3f}"/>'
    if shape[0] == "POLYGON":
        # pad-local points are mil, Cartesian Y up; the drawing is Y down
        nums = [v for v in shape[1] if isinstance(v, (int, float))]
        pts = " ".join(f"{x / MIL:.3f},{-y / MIL:.3f}" for x, y in zip(nums[0::2], nums[1::2]))
        return f'<polygon points="{pts}"/>'
    rx = min(w, h) / 2 if shape[0] == "OVAL" else 0
    return (f'<rect x="{-w / 2:.3f}" y="{-h / 2:.3f}" width="{w:.3f}" height="{h:.3f}" '
            f'rx="{rx:.3f}"/>')


def main() -> int:
    data = json.loads((HERE / "g1_pads.json").read_text(encoding="utf-8"))
    pads = data["pads"]
    board_w, board_d = data["board"]["w_mm"], data["board"]["d_mm"]

    width, height = board_w + 2 * MARGIN_MM, board_d + 2 * MARGIN_MM
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}mm" height="{height:.0f}mm" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">',
        '<rect width="100%" height="100%" fill="#101418"/>',
        f'<g transform="translate({MARGIN_MM},{MARGIN_MM})">',
        f'<rect x="0" y="0" width="{board_w}" height="{board_d}" fill="#1b1f24" '
        'stroke="#f1c40f" stroke-width="0.5"/>',
    ]

    # TBD zones: the six magnetic envelopes, still to be locked.
    for z in data["tbd_zones"]:
        out.append(
            f'<rect x="{z["x_mm"]:.2f}" y="{z["y_mm"]:.2f}" width="{z["w_mm"]:.2f}" '
            f'height="{z["d_mm"]:.2f}" fill="#8e44ad" fill-opacity="0.10" stroke="#bf6ee0" '
            'stroke-width="0.35" stroke-dasharray="1.2 0.8"/>'
        )
        out.append(
            f'<text x="{z["x_mm"] + z["w_mm"] / 2:.2f}" y="{z["y_mm"] + 2.4:.2f}" '
            'fill="#d7aefb" font-family="monospace" font-size="2.2" text-anchor="middle">'
            f'TBD {z["ref"]}</text>'
        )

    # Provisional-pad markers: the layer-13 6 mm boxes drawn around each free pad.
    for d in data.get("provisional_marks", []):
        s = d["size_mm"]
        out.append(
            f'<rect x="{d["x_mm"] - s / 2:.2f}" y="{d["y_mm"] - s / 2:.2f}" width="{s:.2f}" '
            f'height="{s:.2f}" fill="none" stroke="#f1c40f" stroke-width="0.22"/>'
        )

    # DOT marks: the layer-13 squares drawn around the dotted magnet terminals.
    for d in data["dot_marks"]:
        s = d["size_mm"]
        out.append(
            f'<rect x="{d["x_mm"] - s / 2:.2f}" y="{d["y_mm"] - s / 2:.2f}" width="{s:.2f}" '
            f'height="{s:.2f}" fill="none" stroke="#1abc9c" stroke-width="0.25"/>'
        )

    for p in pads:
        x_mm = p["X"] / MIL
        y_mm = -p["Y"] / MIL  # the board stores Cartesian Y-up; the drawing is Y-down
        w, h, shape = pad_size(p.get("Pad"))
        net = p.get("Net") or ""
        provisional = p.get("ref") is None
        stroke = ' stroke="#ffffff" stroke-width="0.18" stroke-dasharray="0.5 0.4"' if provisional else ""
        out.append(
            f'<g transform="translate({x_mm:.3f},{y_mm:.3f}) rotate({-p.get("Rotation") or 0})" '
            f'fill="{net_fill(net)}" fill-opacity="0.95"{stroke}>{pad_shape_svg(shape, w, h)}</g>'
        )

    for c in data["components"]:
        x_mm, y_mm = c["X"] / MIL, -c["Y"] / MIL
        out.append(
            f'<text x="{x_mm:.2f}" y="{y_mm - 1.6:.2f}" fill="#e8e8e8" '
            f'font-family="monospace" font-size="1.7" text-anchor="middle">{c["ref"]}</text>'
        )

    free = sum(1 for p in pads if p.get("ref") is None)
    out += [
        f'<text x="1.5" y="{board_d - 3.2:.1f}" fill="#95a5a6" font-family="monospace" '
        f'font-size="2.2">G1 plan view rebuilt from {len(pads)} saved pads '
        f'({free} boxed provisional magnet terminals, dashed) · '
        f'{board_w:.0f} x {board_d:.0f} mm</text>',
        f'<text x="1.5" y="{board_d - 1.0:.1f}" fill="#e74c3c" font-family="monospace" '
        'font-size="2.2">NO COPPER, NO ROUTING, NO DRC · NOT FOR FAB</text>',
        "</g></svg>",
    ]
    (HERE / "g1_layout.svg").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote g1_layout.svg ({len(pads)} pads, {len(data['tbd_zones'])} zones, "
          f"{len(data['dot_marks'])} dot marks, "
          f"{len(data.get('provisional_marks', []))} provisional marks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
