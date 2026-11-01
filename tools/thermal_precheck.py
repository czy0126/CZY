"""Thermal pre-check for the first-article bench (Stage E/F).

This is not a measurement.  It converts the 100 A loss budget into junction
temperature bounds so the bench has a numeric pass line before a probe is
connected: Tj <= 125 C at the rated current, with the datasheet's 50 K/W
junction-to-ambient (6 cm^2 copper) and a pessimistic 80 K/W estimate.

Usage:
    python tools/thermal_precheck.py --json design/v3/stage_f/thermal_precheck.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from magnetics_design import OP, OP_100, loss_budget

DEVICES = 8                      # 4 transformers x 2 secondary halves
RTH_JA_DATASHEET = 50.0          # K/W, on PCB with 6 cm^2 copper (datasheet max)
RTH_JA_NO_COPPER = 80.0          # K/W, estimate only, not a datasheet value
TJ_MAX_C = 125.0                 # derating target, not the 175 C absolute maximum


def per_device_sr_loss(p_sr_total_w: float) -> float:
    return p_sr_total_w / DEVICES


def junction_temp_c(p_device_w: float, ambient_c: float, rth_ja: float) -> float:
    return ambient_c + p_device_w * rth_ja


def max_ambient_c(p_device_w: float, rth_ja: float, tj_max_c: float = TJ_MAX_C) -> float:
    return tj_max_c - p_device_w * rth_ja


def report() -> dict[str, object]:
    budget_100 = loss_budget(OP_100)
    budget_95 = loss_budget(OP)
    p_dev_100 = per_device_sr_loss(float(budget_100["p_sr_w"]))
    p_dev_95 = per_device_sr_loss(float(budget_95["p_sr_w"]))
    rows = []
    for ambient in (25.0, 40.0, 60.0):
        for rth, label in ((RTH_JA_DATASHEET, "datasheet 50 K/W"), (RTH_JA_NO_COPPER, "estimate 80 K/W")):
            rows.append({
                "ambient_c": ambient,
                "rth_ja_k_per_w": rth,
                "rth_source": label,
                "tj_c_at_100a": junction_temp_c(p_dev_100, ambient, rth),
                "passes_tj_125": junction_temp_c(p_dev_100, ambient, rth) <= TJ_MAX_C,
            })
    return {
        "status": "design estimate, not hardware validated",
        "devices": DEVICES,
        "sr_loss_w_100a": float(budget_100["p_sr_w"]),
        "sr_loss_per_device_w_100a": p_dev_100,
        "sr_loss_per_device_w_95a": p_dev_95,
        "tj_max_c": TJ_MAX_C,
        "max_ambient_c_100a": {
            "rth_50_k_per_w": max_ambient_c(p_dev_100, RTH_JA_DATASHEET),
            "rth_80_k_per_w": max_ambient_c(p_dev_100, RTH_JA_NO_COPPER),
        },
        "matrix": rows,
        "notes": [
            "SR branch loss is the model estimate from the 100 A deck; the bench must confirm it.",
            "50 K/W is the datasheet maximum on 6 cm^2 copper; 80 K/W is an unverified estimate for a smaller pad.",
            "Magnetic and copper temperatures are not predicted here: ELP32 thermal resistance is not in the datasheet.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/stage_f/thermal_precheck.json"))
    args = ap.parse_args()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)


if __name__ == "__main__":
    main()
