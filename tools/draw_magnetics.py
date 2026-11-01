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
from matplotlib.patches import Rectangle

from magnetics_design import CORE, winding_stack

matplotlib.rcParams["svg.fonttype"] = "none"
COPPER = "#c87533"
INSULATION = "#7fa8c9"
CORE_GREY = "#8a8f98"
GLUE = "#d9c27a"


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("design/v3/magnetics"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print(draw_winding_stack(args.out / "winding_cross_section.svg"))
    print(draw_height_stack(args.out / "height_stackup.svg"))


if __name__ == "__main__":
    main()
