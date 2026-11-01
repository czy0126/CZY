"""Size the external resonant inductor (Lr) against the measured current peaks.

The BOM left Lr undecided because the fault peak (65-74 A) is 5x the steady
peak (13.9 A).  This tool turns that into a core/turn/gap proposal by applying
one rule: the peak flux at the worst current the inductor must pass stays at or
below ``SATURATION_MARGIN`` x Bsat.

Current peaks (all measured, not scaled):
    steady    13.88142 A  operating_point_100a.json
    startup   36.07 A     every cold start (v2 progress doc, section 14)
    fault     65.0 A      short circuit, OC delay 13 us (Coc = 1 nF)
    fault     73.68 A     short circuit, OC delay 51.3 us (Coc = 10 nF)

Usage:
    python tools/lr_design.py --json design/v3/bom/lr_design.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from magnetics_design import CORE, core_gap_m, dowell_fr, RHO_CU_100C

LR_TARGET_H = 1.0e-6        # magnetic package target, before leakage is measured
SATURATION_MARGIN = 0.9     # peak flux allowed, fraction of Bsat
PEAKS_A = {
    "steady": 13.88142,
    "startup": 36.07,
    "fault_fast_oc_13us": 65.0,
    "fault_slow_oc_51us": 73.68,
}
MEAN_TURN_M = 0.060        # same ELP32 mean turn as the transformers
FOIL_W_M = 0.018
FOIL_T_M = 0.1e-3
IRMS_A = 9.45014


def peak_flux_t(inductance_h: float, current_a: float, turns: int, ae_m2: float) -> float:
    """B in the centre leg: flux = L*I/N, so B = L*I/(N*Ae)."""
    return inductance_h * current_a / (turns * ae_m2)


def saturation_current_a(inductance_h: float, turns: int, ae_m2: float, bsat_t: float) -> float:
    """Current at which the centre-leg flux reaches bsat_t (first-order criterion)."""
    return bsat_t * turns * ae_m2 / inductance_h


def turns_required(inductance_h: float, current_a: float, ae_m2: float,
                   bsat_t: float, margin: float = SATURATION_MARGIN) -> int:
    """Smallest integer turns that keep B <= margin*Bsat at current_a."""
    import math
    need = inductance_h * current_a / (margin * bsat_t * ae_m2)
    return max(1, math.ceil(need - 1e-9))


def winding_loss(turns: int, frequency_hz: float, irms_a: float) -> dict[str, float]:
    """One foil of FOIL_T_M x FOIL_W_M, `turns` layers, DC x Dowell."""
    length = turns * MEAN_TURN_M
    r_dc = RHO_CU_100C * length / (FOIL_W_M * FOIL_T_M)
    fr = dowell_fr(FOIL_T_M, frequency_hz, turns)
    r_ac = r_dc * fr
    return {"r_dc_ohm": r_dc, "fr": fr, "r_ac_ohm": r_ac, "loss_w": irms_a * irms_a * r_ac}


def candidate(inductance_h: float, turns: int, frequency_hz: float = 200.622e3) -> dict[str, object]:
    ae = float(CORE["Ae_m2"])
    al_ungapped = float(CORE["AL_ungapped_nH"])
    bsat = float(CORE["Bsat_T"])
    gap = core_gap_m(inductance_h, turns, ae, al_ungapped)
    flux = {name: peak_flux_t(inductance_h, i, turns, ae) for name, i in PEAKS_A.items()}
    limit = SATURATION_MARGIN * bsat
    isat = saturation_current_a(inductance_h, turns, ae, bsat)
    wind = winding_loss(turns, frequency_hz, IRMS_A)
    return {
        "turns": turns,
        "gap_mm": gap * 1e3,
        "flux_t": flux,
        "worst_flux_t": max(flux.values()),
        "worst_flux_frac_bsat": max(flux.values()) / bsat,
        "isat_a": isat,
        "passes_fast_oc": flux["fault_fast_oc_13us"] <= limit,
        "passes_slow_oc": flux["fault_slow_oc_51us"] <= limit,
        **wind,
    }


def report(inductance_h: float = LR_TARGET_H) -> dict[str, object]:
    rows = [candidate(inductance_h, n) for n in range(1, 5)]
    fast = [r for r in rows if r["passes_fast_oc"]]
    slow = [r for r in rows if r["passes_slow_oc"]]
    return {
        "status": "design estimate, not hardware validated",
        "inductance_h": inductance_h,
        "core": "TDK ELP32 N97 (B66287G0000X197 + B66287K0000X197)",
        "rule": f"peak flux at the worst current <= {SATURATION_MARGIN} x Bsat",
        "peaks_a": PEAKS_A,
        "candidates": rows,
        "min_turns_fast_oc": None if not fast else fast[0]["turns"],
        "min_turns_slow_oc": None if not slow else slow[0]["turns"],
        "note": "Isat here is the current that reaches Bsat; ferrite loses permeability "
                "before that, so the 0.9 margin is the design point, not the limit",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/lr_design.json"))
    ap.add_argument("--inductance-uh", type=float, default=LR_TARGET_H * 1e6)
    args = ap.parse_args()
    data = report(args.inductance_uh * 1e-6)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)
    for row in data["candidates"]:
        print(f"N={row['turns']} gap={row['gap_mm']:.3f} mm  "
              f"B(65A)={row['flux_t']['fault_fast_oc_13us']:.3f} T  "
              f"B(74A)={row['flux_t']['fault_slow_oc_51us']:.3f} T  "
              f"Isat={row['isat_a']:.1f} A  loss={row['loss_w']:.3f} W  "
              f"13us={'PASS' if row['passes_fast_oc'] else 'fail'} "
              f"51us={'PASS' if row['passes_slow_oc'] else 'fail'}")


if __name__ == "__main__":
    main()
