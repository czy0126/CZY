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
LR_TOTAL_H = 1.0e-6         # tank total (external Lr + transformer leakage) the tank is tuned to
LK_MODEL_H = 80e-9          # deck leakage: 4 x Lp*(1 - k^2), k=.999, Lp=10 uH
SATURATION_MARGIN = 0.9     # peak flux allowed, fraction of Bsat
PEAKS_A = {
    "steady": 13.88142,
    "startup": 36.07,
    "fault_fast_oc_13us": 65.0,
    "fault_slow_oc_51us": 73.68,
}
# Peaks measured on the *physical* decks: external Lr sized to the design target
# and the 15 x 470 uF bank, i.e. the configuration that will be built.  Each
# entry keeps the external inductance it was measured at.  The fault current is
# set by the volt-seconds the Lr absorbs, so a peak measured at one inductance
# must never be pasted onto another -- that is what `paired_flux` prevents.
PHYSICAL_PEAKS: dict[str, dict[str, object]] = {
    "startup_phys": {
        "current_a": 22.53, "external_lr_h": 1.0e-6,
        "deck": "sim/v3/sr_tank_dual_v33_cold_phys.cir",
        "source": "MAX(abs(I(Lr))) on the cold-start physical deck",
    },
    "fault_phys_ride_through": {
        "current_a": 84.02, "external_lr_h": 1.0e-6,
        "deck": "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
        "source": "MAX(abs(I(Lr))) from 0 to 8 ms; the OC trips at 5.5998 ms and the "
                  "run rides through to the trip instead of stopping at 13/51 us",
    },
    "fault_lrmin_ride_through": {
        "current_a": 104.17, "external_lr_h": 0.875e-6,
        "deck": "sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir",
        "source": "MAX(abs(I(Lr))) from 0 to 8 ms at the 0.125 uH-leakage trim end; "
                  "the OC trips at 5.5963 ms.  Scaling the 84.02 A peak by 1/L would "
                  "give 96.0 A, so 8.5 % of the peak is not volt-second scaling",
    },
}

CR_TOTAL_F = 620e-9        # deck CR_TOTAL
CLOCK_KHZ = 200.622        # measured switching frequency of the 100 A deck
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


def paired_flux(case: dict[str, object], turns: int, ae_m2: float | None = None) -> float:
    """Flux at the current the case was measured at, using that case's own L.

    ``candidate()`` holds the current fixed while it sweeps the inductance, which
    over-predicts B at larger L and is therefore conservative.  A *measured*
    peak is different: it already contains the L it ran at, so the two must stay
    paired or the flux is simply wrong.
    """
    ae = float(CORE["Ae_m2"]) if ae_m2 is None else ae_m2
    return peak_flux_t(float(case["external_lr_h"]), float(case["current_a"]), turns, ae)


def external_lr_h(leakage_h: float) -> float:
    """External Lr that makes the tank total equal ``LR_TOTAL_H``.

    The deck models `Lr` as the external part and the transformer leakage
    separately, so the part to build is the total minus the measured leakage.
    """
    return LR_TOTAL_H - leakage_h


def tank_total_h(external_h: float, leakage_h: float = LK_MODEL_H) -> float:
    """Total resonant inductance the tank sees: external Lr plus leakage."""
    return external_h + leakage_h


def resonant_khz(total_h: float, cr_f: float = CR_TOTAL_F) -> float:
    import math
    return 1.0 / (2.0 * math.pi * math.sqrt(total_h * cr_f)) / 1e3


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


def physical_peak_report(ae_m2: float | None = None) -> dict[str, object]:
    """Turn count implied by each measured physical peak, at its own inductance."""
    ae = float(CORE["Ae_m2"]) if ae_m2 is None else ae_m2
    bsat = float(CORE["Bsat_T"])
    cases = {}
    for name, case in PHYSICAL_PEAKS.items():
        cases[name] = {
            "current_a": case["current_a"],
            "external_lr_h": case["external_lr_h"],
            "deck": case["deck"],
            "source": case["source"],
            "flux_t_at_2": paired_flux(case, 2, ae),
            "flux_t_at_3": paired_flux(case, 3, ae),
            "frac_bsat_at_3": paired_flux(case, 3, ae) / bsat,
            "exceeds_bsat_at_2": paired_flux(case, 2, ae) > bsat,
            "min_turns": turns_required(float(case["external_lr_h"]), float(case["current_a"]), ae, bsat),
        }
    return {
        "cases": cases,
        "min_turns_all": max(c["min_turns"] for c in cases.values()),
        "rule": "B = L*I/(N*Ae) at the measured current, L paired with the deck it ran on",
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
        "physical_peaks": physical_peak_report(),
        "tank": {
            "total_target_h": LR_TOTAL_H,
            "leakage_model_h": LK_MODEL_H,
            "external_target_h": external_lr_h(LK_MODEL_H),
            "resonant_khz": resonant_khz(LR_TOTAL_H),
            "clock_khz": CLOCK_KHZ,
            "note": "the deck's LR_TOTAL is the external part; add the leakage to get the "
                    "tank total.  Trim the external part to LR_TOTAL_H - measured leakage "
                    "on the first article; the 1.0 uH sizing value above is the conservative "
                    "top of that window, not the value to wind.",
        },
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
    print(f"min turns from the measured physical peaks: {data['physical_peaks']['min_turns_all']}")
    for name, case in data["physical_peaks"]["cases"].items():
        print(f"  {name:26s} I={case['current_a']:6.2f} A @ {case['external_lr_h'] * 1e6:.3f} uH  "
              f"B(N=2)={case['flux_t_at_2']:.3f} T  B(N=3)={case['flux_t_at_3']:.3f} T  "
              f"needs N={case['min_turns']}")


if __name__ == "__main__":
    main()
