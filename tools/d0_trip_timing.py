"""Measure the two D0 overcurrent channels' response on the 48 V hot-fault raw.

P0-3 of issue #36 says the board must not claim the ``FAST_TRIP`` channel is
both faster *and* more sensitive than ``HARD_TRIP``.  The two are different
claims and the board part table decides which one holds:

* the hard trip compares the two-section ``OC`` node against 1.000 V,
* the fast trip compares the one-pole ``V(ocdf)`` node against 1.769 V.

Both thresholds are read from the part table (``divider_output``), and both
crossing times are measured on the same fault: the fault instant comes from the
deck's own PWL/threshold crossing, not from a hand-copied number.  ``V(oc)`` is
taken from the unprotected srprobe run because the prot-B run trips and the
current never reaches 1.000 V there; ``V(ocdf)`` only exists in the prot-B run.

**The two thresholds do not live on the same node, so they are not in the same
units until the divider gain is applied.**  ``slope_v_per_a_peak`` (from
``ct_design``) is burden-peak-current to ``OC``-pin volts, and ``OC`` sits behind
the ``Rf``/``Rd1``/``Rd2`` divider (gain 24/35).  ``V(ocdf)`` sits on the burden
itself (gain 1.0).  Comparing 1.769 V against 1.000 V directly would inflate the
fast channel's current equivalence by 1/gain = 1.46x.

The two runs share their trajectory up to the trip, which the tool checks by
comparing ``V(oc)`` sample by sample over the pre-trip segment.

What this is not: a hardware response time.  The deck's LM393/CD4xxx/driver
delays are ideal (0 s), the CT is ideal apart from its filter, and the fault is
a resistive short on the output, not a device failure.  The numbers are the
*front end's* contribution, which is the part the board can actually change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct_design as ct
import make_d0_protection_board as board
from ascii_raw_window import read_window
from transformer_flux import fault_instant

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design" / "v3" / "stage_f" / "d0_trip_timing.json"

# The 48 V/120 A hot-fault pair.  The base run has no protection at all, so
# V(oc) keeps rising past 1.000 V; the prot-B run adds the fast comparator and
# the extra 10 us node.
HARD_DECK = "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"
FAST_DECK = "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_fast10u_1p8v.cir"

# Filter constants, from the deck lines below rather than from a remembered
# "47 us".  The OC node is two cascaded sections, not one: stage 1 is Rf*Cf,
# but stage 2 sees Rd2 in parallel with (Rd1 + Rf) through Coc, so it is slower.
#   Rf ocd  oc1 1k      Cf  oc1  ocm 47n
#   Rd1 oc1 oc  10k     Rd2 oc   ocm 24k     Coc oc ocm 10n
#   Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k   Cocdf ocdf ocm 10n
#   Rocdf ocdf ocm 1G
RF_OHM, CF_F = 1e3, 47e-9
RD1_OHM, RD2_OHM, COC_F = 10e3, 24e3, 10e-9
Rdf_OHM, Cocdf_F = 1e3, 10e-9


def _first_crossing(t: np.ndarray, v: np.ndarray, threshold: float) -> float | None:
    hits = np.nonzero(v >= threshold)[0]
    return None if hits.size == 0 else float(t[hits[0]])


def _pre_fault(t: np.ndarray, v: np.ndarray, fault_s: float) -> dict[str, float]:
    """Mean and peak over the last full switching period before the fault."""
    window = (t >= fault_s - 5e-6) & (t < fault_s)
    a = v[window]
    return {"mean_v": float(a.mean()), "peak_v": float(a.max()),
            "min_v": float(a.min())}


def build(hard_raw: Path, fast_raw: Path) -> dict:
    hard_fault = fault_instant(ROOT / HARD_DECK)
    fast_fault = fault_instant(ROOT / FAST_DECK)
    if abs(hard_fault["saved_us"] - fast_fault["saved_us"]) > 1e-6:
        raise SystemExit("the two runs do not inject the fault at the same instant")

    hard_thr = board.divider_output("R2", "R3")
    fast_thr = board.divider_output("R4", "R5")
    gain = ct.divider_gain()
    slope, hard_a = board.burden_numbers()
    # slope is burden-peak-current -> OC pin, so the burden node itself moves
    # slope/gain per amp, and the fast threshold (on the burden) is at
    # fast_thr * gain / slope.
    burden_node_v_per_a = slope / gain
    fast_a = fast_thr / burden_node_v_per_a
    tau1_us = RF_OHM * CF_F * 1e6
    tau2_us = (RD2_OHM * (RD1_OHM + RF_OHM) / (RD1_OHM + RF_OHM + RD2_OHM)) * COC_F * 1e6
    tau_fast_us = Rdf_OHM * Cocdf_F * 1e6

    fault_s = hard_fault["saved_us"] * 1e-6
    # Only the neighbourhood of the fault is needed: 10 us before it for the
    # operating point, 80 us after for both crossings.
    t0, t1 = fault_s - 10e-6, fault_s + 80e-6

    t, hard = read_window(hard_raw, ["V(oc)"], t0, t1)
    hard_cross = _first_crossing(t, hard["V(oc)"], hard_thr)
    hard_pre = _pre_fault(t, hard["V(oc)"], fault_s)

    t_f, fast = read_window(fast_raw, ["V(oc)", "V(ocdf)"], t0, t1)
    fast_cross = _first_crossing(t_f, fast["V(ocdf)"], fast_thr)
    fast_pre = _pre_fault(t_f, fast["V(ocdf)"], fault_s)
    hard_on_fast_run_pre = _pre_fault(t_f, fast["V(oc)"], fault_s)

    # The prot-B B-source is a logic node and draws no tank current, so the two
    # runs must agree on V(oc) before the fast trip fires.  The added sources can
    # still change the solver's timestep, so the base trace is interpolated onto
    # the prot-B time base instead of assuming identical sample times.
    trip_s = fast_cross if fast_cross is not None else fault_s
    common = (t_f > fault_s) & (t_f <= trip_s)
    if common.any():
        base_on_fast_grid = np.interp(t_f[common], t, hard["V(oc)"])
        node_delta = float(np.max(np.abs(fast["V(oc)"][common] - base_on_fast_grid)))
    else:
        node_delta = float("nan")
    same_shape = bool(common.sum() >= 10)

    hard_delay = None if hard_cross is None else hard_cross * 1e6 - hard_fault["saved_us"]
    fast_delay = None if fast_cross is None else fast_cross * 1e6 - fast_fault["saved_us"]

    return {
        "kind": "D0_TRIP_TIMING",
        "measured_from": {
            "hard": str(hard_raw.resolve().relative_to(ROOT))
            if hard_raw.resolve().is_relative_to(ROOT) else str(hard_raw),
            "fast": str(fast_raw.resolve().relative_to(ROOT))
            if fast_raw.resolve().is_relative_to(ROOT) else str(fast_raw),
        },
        "fault": {"absolute_us": hard_fault["absolute_us"],
                  "saved_us": hard_fault["saved_us"],
                  "source": f"{HARD_DECK}:Vfltctl_hot"},
        "threshold": {
            "hard_v": hard_thr,
            "hard_node": "OC: Rf/Cf then Rd1/Rd2/Coc, two cascaded sections",
            "fast_v": fast_thr,
            "fast_node": "V(ocdf): one 1k/10n pole on the burden",
            "reference_divider": {"R2/R3": ["R2", "R3"], "R4/R5": ["R4", "R5"]},
            "divider_gain_oc": gain,
            "burden_node_v_per_a_peak": burden_node_v_per_a,
            "filter_poles_us": {"oc_stage_1": tau1_us, "oc_stage_2": tau2_us,
                                "fast": tau_fast_us},
        },
        "results": {
            "hard_delay_us": hard_delay,
            "fast_delay_us": fast_delay,
            "fast_is_earlier_us": (None if None in (hard_delay, fast_delay)
                                   else hard_delay - fast_delay),
            "hard_pre_fault_node_v": hard_pre,
            "fast_pre_fault_node_v": fast_pre,
            "hard_pre_fault_node_on_fast_run_v": hard_on_fast_run_pre,
            "hard_pre_fault_fraction_of_threshold": hard_pre["mean_v"] / hard_thr,
            "fast_pre_fault_fraction_of_threshold": fast_pre["mean_v"] / fast_thr,
            "hard_threshold_margin_x": hard_thr / hard_pre["mean_v"],
            "fast_threshold_margin_x": fast_thr / fast_pre["mean_v"],
            "hard_threshold_current_a": hard_a,
            "fast_threshold_current_a": fast_a,
            "fast_threshold_is_higher_by_a": fast_a - hard_a,
            "pre_trip_node_delta_v": node_delta,
            "note": ("fast_is_earlier_us is measured on two runs that share their "
                     "trajectory up to the fast trip; the fast channel is earlier at a "
                     "higher equivalent peak current, so 'faster' and 'less sensitive' "
                     "are both true and neither implies the other"),
        },
        "checks": {
            "both_raws_present": hard_raw.is_file() and fast_raw.is_file(),
            "fault_injected_at_the_same_instant": True,
            "hard_crossing_found": hard_cross is not None,
            "fast_crossing_found": fast_cross is not None,
            "pre_trip_samples_compared_on_both_runs": same_shape,
            "pre_trip_trajectories_agree_within_1e-3_v": bool(
                np.isfinite(node_delta) and node_delta < 1e-3),
        },
        "limitations": [
            "The deck models no comparator, logic or driver delay: these are front-end "
            "times, and the board's total response is larger by whatever those stages add.",
            "The fault is a resistive short on the output, applied by an ideal switch; it "
            "is not a device failure and it does not reproduce a 50 V or an inductive fault.",
            "The raw is the 4 mF frozen deck, not the 7.05 mF physical bank.",
            "A hardware response time requires the oscilloscope records listed as PENDING "
            "in issue #36; nothing here substitutes for them.",
            "The current equivalence of both thresholds uses ct_design's linear "
            "slope_v_per_a_peak, which is calibrated on the rated-current waveform "
            "(peak/mean = 1.660).  A fault current is peakier, so both amp figures are "
            "lower bounds on the peak that trips them, not equalities.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hard-raw", default=str(ROOT / (HARD_DECK[:-4] + ".raw")))
    parser.add_argument("--fast-raw", default=str(ROOT / (FAST_DECK[:-4] + ".raw")))
    parser.add_argument("--json", type=Path, default=OUT)
    args = parser.parse_args(argv)
    hard_raw, fast_raw = Path(args.hard_raw), Path(args.fast_raw)
    for raw in (hard_raw, fast_raw):
        if not raw.is_file():
            raise SystemExit(f"{raw} is not here; the timing record needs both runs")
    data = build(hard_raw, fast_raw)
    r = data["results"]
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(text, encoding="utf-8", newline="\n")
    print(f"hard {r['hard_delay_us']:.2f} us at {data['threshold']['hard_v']:.3f} V, "
          f"fast {r['fast_delay_us']:.2f} us at {data['threshold']['fast_v']:.3f} V "
          f"-> {r['fast_is_earlier_us']:.2f} us earlier")
    print(f"wrote {args.json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
