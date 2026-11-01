"""Generate the two SVG drawings that accompany the magnetic design package.

Both drawings are schematic cross-sections, not scale mechanical drawings.  The
numeric values come from tools/magnetics_design.py so a design change cannot
leave an old number in the picture.

Usage:
    python tools/draw_magnetics.py --out design/v3/magnetics
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle, Rectangle

from board_netlist import winding_layout
from magnetics_design import CORE, winding_stack

matplotlib.rcParams["svg.fonttype"] = "none"
COPPER = "#c87533"
INSULATION = "#7fa8c9"
CORE_GREY = "#8a8f98"
GLUE = "#d9c27a"
DOT = "#111111"
WIRE = "#333333"


def draw_winding_stack(path: Path) -> Path:
    layers, total = winding_stack()
    window_h = float(CORE["window_height_m"]) * 1e3
    window_w = (float(CORE["outer_length_m"]) - float(CORE["centre_leg_width_m"])) / 2 * 1e3
    carrier = 0.20

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    ax.add_patch(Rectangle((0, 0), window_w, window_h, fill=False, lw=1.6, ec="black"))
    ax.add_patch(Rectangle((0, 0), window_w, carrier, fc="#e8e2d2", ec="black", lw=0.6))
    ax.text(window_w / 2, carrier / 2, "carrier 0.20", ha="center", va="center", fontsize=8)

    y = carrier
    x0 = 0.35
    x1 = window_w - 0.35
    n = len(layers)
    label_ys = [0.10 + i * (2.85 / (n - 1)) for i in range(n)]
    for (name, thickness_mm), label_y in zip(layers, label_ys):
        h = thickness_mm * 1e3
        colour = COPPER if "Cu" in name else INSULATION
        if name.startswith("Outer"):
            colour = "#d8d8d8"
        ax.add_patch(Rectangle((x0, y), x1 - x0, h, fc=colour, ec="black", lw=0.5, alpha=0.9))
        y_mid = y + h / 2
        ax.plot([x1, window_w + 0.10, window_w + 2.10], [y_mid, label_y, label_y],
                color="0.45", lw=0.5, clip_on=False)
        ax.text(window_w + 2.20, label_y, name, fontsize=7.5, va="center")
        y += h

    clearance = window_h - total * 1e3 - carrier
    ax.annotate("", xy=(-0.10, carrier), xytext=(-0.10, y),
                arrowprops={"arrowstyle": "<->", "lw": 0.8})
    ax.text(-0.18, (carrier + y) / 2, "stack 1.10 mm\n(+0.20 carrier)",
            fontsize=8, va="center", ha="right")
    ax.annotate("", xy=(2.0, y), xytext=(2.0, window_h),
                arrowprops={"arrowstyle": "<->", "lw": 0.8})
    ax.text(2.10, (y + window_h) / 2, f"clearance {clearance:.2f} mm",
            fontsize=8, va="center")

    ax.set_xlim(-1.9, window_w + 5.2)
    ax.set_ylim(-0.15, window_h + 0.15)
    ax.set_aspect("equal")
    ax.set_xlabel("window width per side 5.70 mm (schematic)")
    ax.set_ylabel("height in window (mm)")
    ax.set_title("ELP32 window cross-section: P1 / S_A / P2 / S_B / P3 + outer tape")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def draw_height_stack(path: Path) -> Path:
    elp = 6.35
    plate = 3.15
    glue = 0.05
    label = 0.05
    nominal = elp + plate + glue + label
    worst = float(CORE["height_max_m"]) * 1e3 + 0.08 + 0.06
    limit = 10.00

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    width = 1.0
    parts = [
        ("ELP half 6.35", elp, CORE_GREY),
        ("I plate 3.15", plate, CORE_GREY),
        ("glue 0.05", glue, GLUE),
        ("label 0.05", label, "#f0ead6"),
    ]
    y = 0.0
    thin_ys = [8.40, 8.05]
    thin_i = 0
    for text, h, colour in parts:
        ax.add_patch(Rectangle((0, y), width, h, fc=colour, ec="black", lw=0.6))
        if h > 0.5:
            ax.text(width / 2, y + h / 2, text, ha="center", va="center", fontsize=9)
        else:
            label_y = thin_ys[thin_i]
            thin_i += 1
            ax.annotate(text, xy=(width, y + h / 2), xytext=(width + 0.15, label_y),
                        fontsize=8, va="center",
                        arrowprops={"arrowstyle": "-", "lw": 0.5, "color": "0.35"})
        y += h

    ax.axhline(elp + plate, color="#444444", lw=0.8, ls="-.")
    ax.text(-0.10, 8.85, "core stack 9.50", fontsize=8,
            ha="right", va="center", color="#444444")
    ax.axhline(limit, color="#b03030", lw=1.4, ls="--")
    ax.text(width + 0.15, limit + 0.12, "10.00 mm limit", color="#b03030", fontsize=9,
            va="bottom")
    ax.axhline(worst, color="#2f6f3e", lw=1.0, ls=":")
    ax.text(width + 0.15, 9.30,
            "worst case 9.94\n(9.80 core + 0.08 + 0.06)",
            color="#2f6f3e", fontsize=8, va="top")
    ax.text(-0.10, 9.72, f"nominal {nominal:.2f}", fontsize=8, ha="right", va="center")
    ax.text(width + 0.15, 1.2, "0.5 mm pocket: 9.44 worst", fontsize=8, va="center")

    ax.annotate("", xy=(0.12, 0.0), xytext=(0.12, nominal),
                arrowprops={"arrowstyle": "<->", "lw": 0.8})
    ax.text(0.2, nominal / 2, f"nominal\n{nominal:.2f} mm", fontsize=8, va="center")
    ax.set_xlim(-1.7, width + 3.9)
    ax.set_ylim(-0.2, limit + 0.7)
    ax.set_ylabel("height above PCB (mm)")
    ax.set_xticks([])
    ax.set_title("Height stack-up: no metal clamp, adhesive + label only")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _dot(ax, x: float, y: float) -> None:
    ax.add_patch(Circle((x, y), 0.055, fc=DOT, ec=DOT, zorder=6))


def _vertical_coil(ax, x: float, y_top: float, turns: int, seg: float, colour: str) -> list[float]:
    """A series chain drawn top-to-bottom; each hump starts at its top end."""
    starts = []
    for k in range(turns):
        yc = y_top - seg / 2 - k * seg
        ax.add_patch(Arc((x, yc), seg, seg, theta1=-90, theta2=90, lw=1.6, color=colour))
        starts.append(y_top - k * seg)
    return starts


def _half_coil(ax, x0: float, x1: float, y: float, colour: str) -> None:
    """One secondary half from x0 to x1, drawn as a single upward hump."""
    ax.add_patch(Arc(((x0 + x1) / 2, y), x1 - x0, x1 - x0, theta1=0, theta2=180,
                     lw=1.6, color=colour))


def draw_winding_connections(path: Path) -> Path:
    """Terminal-level DOT map: the one drawing the shop floor builds from.

    Every DOT is a winding START.  Primary: each turn's non-dot end meets the next
    turn's dot end (series-aiding).  Secondary: CTAP is S_A's DOT but S_B's
    NON-dot, so the tap is NOT two dots joined -- this is the point issue #1 is
    about.  Node order and pin names are asserted by board_netlist.winding_layout().
    """
    report = winding_layout()
    if not report["ok"]:
        raise SystemExit("refusing to draw: polarity checks failed")
    names = list(report["transformers"])
    fig, ax = plt.subplots(figsize=(12.0, 0.62 * len(names) + 3.4))
    row_h, seg = 2.60, 0.55
    x_pri, x_ctap, half = 2.20, 6.40, 1.20
    bus_y = -(len(names) - 0.5) * row_h - 1.05

    for n, name in enumerate(names):
        y_top = -n * row_h
        y_mid = y_top - 1.5 * seg
        ax.text(x_pri - 2.00, y_mid, name, fontsize=12, fontweight="bold", va="center")
        starts = _vertical_coil(ax, x_pri, y_top, 3, seg, COPPER)
        for k, ys in enumerate(starts):
            _dot(ax, x_pri, ys)
            ax.text(x_pri - 0.34, ys, f"P{k + 1} DOT", fontsize=7, ha="right", va="center")
        ax.text(x_pri + 0.42, y_top + 0.10, "PRI_A (DOT)", fontsize=7.5, va="bottom")
        ax.text(x_pri + 0.42, y_top - 3 * seg - 0.10, "PRI_B (NON-DOT)",
                fontsize=7.5, va="top")
        # Primary series: this unit's non-dot to the next unit's dot.
        if n + 1 < len(names):
            ax.plot([x_pri, x_pri - 0.55, x_pri - 0.55, x_pri],
                    [y_top - 3 * seg, y_top - 3 * seg, y_top - row_h, y_top - row_h],
                    color=WIRE, lw=1.2)
        else:
            ax.plot([x_pri, x_pri], [y_top - 3 * seg, y_top - 3 * seg - 0.35],
                    color=WIRE, lw=1.2)
            ax.plot([x_pri - 0.22, x_pri + 0.22], [y_top - 3 * seg - 0.35] * 2,
                    color=WIRE, lw=1.6)
            ax.text(x_pri + 0.40, y_top - 3 * seg - 0.70, "PGND", fontsize=7.5, va="center")

        # Secondary: SEC_A --(S_A, dot at right)-- CTAP --(S_B, dot at right)-- SEC_B
        _half_coil(ax, x_ctap - half, x_ctap, y_mid, COPPER)
        _half_coil(ax, x_ctap, x_ctap + half, y_mid, COPPER)
        _dot(ax, x_ctap, y_mid)
        _dot(ax, x_ctap + half, y_mid)
        ax.text(x_ctap - half / 2, y_mid + 0.10, "S_A", fontsize=8, ha="center", va="bottom")
        ax.text(x_ctap + half / 2, y_mid + 0.10, "S_B", fontsize=8, ha="center", va="bottom")
        ax.plot([x_ctap - half, x_ctap - half], [y_mid, y_mid - 0.30], color=WIRE, lw=1.2)
        ax.plot([x_ctap + half, x_ctap + half], [y_mid, y_mid - 0.30], color=WIRE, lw=1.2)
        ax.plot([x_ctap, x_ctap], [y_mid, bus_y], color=WIRE, lw=1.2)
        ax.text(x_ctap - half, y_mid - 0.42, f"SEC_{n + 1}A", fontsize=7.5, ha="center")
        ax.text(x_ctap + half, y_mid - 0.42, f"SEC_{n + 1}B", fontsize=7.5, ha="center")
        ax.text(x_ctap, y_mid + 0.62, "CTAP", fontsize=7.5, ha="center", va="bottom",
                color="#8a2f2f", fontweight="bold")

    ax.plot([x_ctap] * 2, [bus_y, bus_y], color=WIRE, lw=2.0)
    ax.plot([x_ctap - 2.0, x_ctap + 2.0], [bus_y, bus_y], color=WIRE, lw=2.0)
    ax.text(x_ctap + 2.1, bus_y, "VOUT bus (all four CTAP)", fontsize=8.5, va="center")
    ax.text(0.0, 1.35,
            "DOT = winding START.  SPICE puts the DOT on an L element's first node, and positive K couples DOT to DOT.\n"
            "Deck:  Lsa_i out a_i  ->  CTAP is S_A's DOT;   Lsb_i b_i out  ->  SEC_B is S_B's DOT, CTAP is S_B's NON-dot.\n"
            "Do NOT join the two DOTs at the centre tap: that makes both halves the same phase and the rectifier stops working.",
            fontsize=8.2, va="bottom", family="monospace")
    ax.set_xlim(-1.2, 9.6)
    ax.set_ylim(bus_y - 0.9, 3.2)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("T1-T4 winding connections with DOTs (generated from the deck by board_netlist.winding_layout)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("design/v3/magnetics"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print(draw_winding_stack(args.out / "winding_cross_section.svg"))
    print(draw_height_stack(args.out / "height_stackup.svg"))
    print(draw_winding_connections(args.out / "winding_connections.svg"))


if __name__ == "__main__":
    main()
