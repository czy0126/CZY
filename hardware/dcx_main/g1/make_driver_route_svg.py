"""Render the driver-region copper that was read back from the saved route copy.

Input is ``driver_route_readback.json`` (native reopen readback), not the plan,
so the picture shows what is actually in the file: 77 parts, 299 pads and the
25 layer-1 lines.  Review aid only -- not a Gerber, DRC or fab claim.

    python hardware/dcx_main/g1/make_driver_route_svg.py
"""

from __future__ import annotations

import json
from pathlib import Path

import make_g1_layout_svg as base

HERE = Path(__file__).resolve().parent
MIL = base.MIL
X0, X1, Y0, Y1 = 39.0, 67.0, 43.0, 71.0  # driver window, mm Y down
COLORS = {"GH_DRV": "#f1c40f", "GH": "#f39c12", "GL_DRV": "#3498db",
          "GL": "#5dade2", "HB": "#2ecc71"}


def main() -> int:
    data = json.loads((HERE / "driver_route_readback.json").read_text(encoding="utf-8"))["value"]
    scale = 8  # mm per drawing unit; the window is 28 x 28 mm
    w, h = (X1 - X0) * scale, (Y1 - Y0) * scale
    layer = [f'<g transform="translate({-X0 * scale},{-Y0 * scale}) scale({scale})">']
    for p in data["pads"]:
        x, y = p["X"] / MIL, -p["Y"] / MIL
        if not (X0 <= x <= X1 and Y0 <= y <= Y1):
            continue
        pw, ph, shape = base.pad_size(p.get("Pad"))
        layer.append(
            f'<g transform="translate({x:.3f},{y:.3f}) rotate({-p.get("Rotation") or 0})" '
            f'fill="{base.net_fill(p.get("Net") or "")}" fill-opacity="0.95">'
            f'{base.pad_shape_svg(shape, pw, ph)}</g>')
    for line in data["lines"]:
        x1, y1 = line["x1"] / MIL, -line["y1"] / MIL
        x2, y2 = line["x2"] / MIL, -line["y2"] / MIL
        layer.append(
            f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
            f'stroke="{COLORS.get(line["net"], "#ecf0f1")}" '
            f'stroke-width="{line["width"] / MIL:.3f}" stroke-linecap="round"/>')
    for c in data["components"]:
        x, y = c["X"] / MIL, -c["Y"] / MIL
        if not (X0 <= x <= X1 and Y0 <= y <= Y1):
            continue
        layer.append(f'<text x="{x:.2f}" y="{y - 1.5:.2f}" fill="#e8e8e8" '
                     f'font-family="monospace" font-size="1.5" text-anchor="middle">{c["ref"]}</text>')
    legend = " · ".join(f"{k} {v}" for k, v in COLORS.items())
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#101418"/>',
        *layer,
        "</g>",
        f'<text x="8" y="{h - 46}" fill="#95a5a6" font-family="monospace" font-size="11">'
        f'driver window {X1 - X0:.0f} x {Y1 - Y0:.0f} mm · 25 layer-1 lines · '
        'read back from dcx_main_board_g1_driver_route.eprj2</text>',
        f'<text x="8" y="{h - 28}" fill="#ecf0f1" font-family="monospace" font-size="11">'
        f'routed nets ({legend})</text>',
        f'<text x="8" y="{h - 10}" fill="#e74c3c" font-family="monospace" font-size="12">'
        'PARTIAL ROUTING · NO NATIVE DRC · NOT FOR FAB</text>',
        "</svg>",
    ]
    (HERE / "driver_route.svg").write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"wrote driver_route.svg ({len(data['lines'])} lines, {len(data['pads'])} pads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
