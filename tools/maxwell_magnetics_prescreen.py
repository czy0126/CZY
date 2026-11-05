"""Fail-closed analytic pre-screen for CZY's ELP38 Maxwell 3D work.

A magnetostatic FE model with a measured nonlinear N97 B-H curve is needed
to establish high-current differential L(I). These numbers are a *linear*
L*I/(N*Amin) screen, NOT Maxwell output or hardware qualification.

Usage:
    python tools/maxwell_magnetics_prescreen.py --out design/v3/maxwell/prescreen.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design/v3/bom/lr_design.json"
RFQ_CURRENT_A = 121.515
TARGET_B_T = 0.248
MU0 = 4 * math.pi * 1e-7


def candidate_rows(data: dict) -> list[dict]:
    core = next(
        c for c in data["catalogue_cores"]["cores"]
        if c["id"] == "ELP38_I38"
    )
    ae = core["ae_mm2"] * 1e-6
    amin = core["amin_mm2"] * 1e-6
    al_h = core["al_ungapped_nh"] * 1e-9
    rows = []
    for turns in (2, 3):
        for inductance_uh in (0.92, 1.0):
            l_h = inductance_uh * 1e-6
            # Simple reluctance estimate of total effective gap, not the
            # physical grind offset or a fringing-calibrated manufacturer AL.
            gap_m = MU0 * turns**2 * ae * (
                1 / l_h - 1 / (al_h * turns**2)
            )
            b_t = l_h * RFQ_CURRENT_A / (turns * amin)
            i_limit = TARGET_B_T * turns * amin / l_h
            rows.append({
                "core_id": core["id"],
                "turns": turns,
                "target_l_uh": inductance_uh,
                "gap_analytic_mm": round(gap_m * 1e3, 4),
                "b_at_rfq_current_t": round(b_t, 6),
                "rfq_current_a": RFQ_CURRENT_A,
                "screen_b_t": TARGET_B_T,
                "screen_current_at_fixed_l_a": round(i_limit, 3),
                "passes_flux_screen_at_fixed_l": b_t <= TARGET_B_T,
                "gap_inside_published_empirical_range":
                    0.1 < gap_m * 1e3 < 2.0,
                "source": "design/v3/bom/lr_design.json:catalogue_cores/ELP38_I38",
                "status": "ANALYTIC_PRESCREEN_ONLY_NOT_MAXWELL_OR_HARDWARE",
            })
    return rows


def report() -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = candidate_rows(source)
    assert len(rows) == 4
    core = next(c for c in source["catalogue_cores"]["cores"]
                if c["id"] == "ELP38_I38")
    assert core["amin_mm2"] == 192 and core["ae_mm2"] == 194
    assert core["al_ungapped_nh"] == 8400
    return {
        "source_of_truth": SOURCE.relative_to(ROOT).as_posix(),
        "model": "concentrated_reluctance_and_flux_screen",
        "frequency_khz": source["tank"]["clock_khz"],
        "operating_total_lr_target_uh": source["tank"]["total_target_h"] * 1e6,
        "operating_external_lr_target_uh":
            source["tank"]["external_target_h"] * 1e6,
        "rfq_current_a": RFQ_CURRENT_A,
        "screen_b_t": TARGET_B_T,
        "cases": rows,
        "decisions": {
            "2turn": "NO_FREEZE: 121.515A request exceeds 0.248T line at 0.92/1.0uH",
            "3turn": "REQUIRES_CUSTOM_GAP: calculated gap exceeds 2mm manufacturer example range",
            "stop_rule": "Do not claim L(I), leakage, core loss or fab readiness "
                         "from this algebra; nonlinear FE and hardware samples remain required",
        },
        "maxwell_executed": False,
        "fab_release": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="Optional JSON report path")
    ns = parser.parse_args()
    result = report()
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if ns.out:
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(data, encoding="utf-8")
    else:
        print(data, end="")


if __name__ == "__main__":
    main()
