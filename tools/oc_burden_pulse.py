"""Price the CT burden resistor inside the fault window (SOURCE-05).

SOURCE-05 pinned the steady burden power to measurement (69.6 mW at 100 A,
about 103 mW at 121.67 A) against a 0.125 W 0805, and left the fault pulse
open with the note "no fault raw saves V(ocd)".  That premise is stale: the
srprobe family saves ``V(ocd)``/``V(ocm)`` and ``Rbur ocd ocm 10`` *is* the
burden, so the pulse is measurable from raws that already exist.

Two things are deliberately not claimed:

* the vendor pulse-derating curve is not vendored.  A 13 us pulse is not a
  continuous dissipation, so the peak is reported next to the nominal rating
  as an input to part selection, never as a pass/fail;
* the startup pulse is still unmeasured.  The 8 ms cold-start deck does not
  save the burden nodes and re-running it (2294 s, 13 GB) is a separate call.

The 50 V bases are the ideal-switch (``Vt=10``) controls, not the declared
parent and not the threshold-muted controls.  Three candidates were available
and only one of them can price a 320 us pulse:

* the declared parent is complete but sits 13-18 mV from the candidate before
  the fault, so a benefit differenced against it is not attributable;
* the threshold-muted control pairs exactly (0.000 mV) but stalls at
  250.151 us (A) / 254.980 us (B), so its fault energy is a prefix;
* the ``Vt=10`` control is complete and topology-matched (its clamps leak 1 nA,
  measured on a two-switch probe deck, i.e. they are electrically open).  It is
  still 13.2/17.5 mV from the candidate before the fault, so the 50 V benefit
  percentages are screening numbers, not paired effects -- stated in ``limits``.

The exactly-paired but truncated comparison lives in
``protection_candidate_50v_120a_prot_{a,b}_paired.json`` (PROT-03); it answers a
different question (stress relief over a common slice) and must not be used to
quote a full-window pulse energy.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

import hot_fault_metrics
from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "design/v3/bom/oc_burden_pulse.json"

RATED_PART = "Panasonic ERJ6ENF10R0V (0805)"
RATED_POWER_W = 0.125

BURDEN = re.compile(r"^\s*Rbur\s+(\S+)\s+(\S+)\s+(\S+)\s*$", re.IGNORECASE | re.MULTILINE)

RUNS = [
    {"run": "48v_base", "vin": 48.0, "role": "base",
     "deck": "sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"},
    {"run": "48v_prot_a", "vin": 48.0, "role": "candidate",
     "deck": "sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_a_oc1v.cir"},
    {"run": "48v_prot_b", "vin": 48.0, "role": "candidate",
     "deck": "sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_prot_b_fast10u_1p8v.cir"},
    # Complete 320 us records only: a stalled control would price a prefix as
    # if it were the whole pulse.
    {"run": "50v_base_a", "vin": 50.0, "role": "base",
     "deck": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_noclamp_control.cir"},
    {"run": "50v_prot_a", "vin": 50.0, "role": "candidate",
     "deck": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir"},
    {"run": "50v_base_b", "vin": 50.0, "role": "base",
     "deck": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_noclamp_control.cir"},
    {"run": "50v_prot_b", "vin": 50.0, "role": "candidate",
     "deck": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir"},
    {"run": "50v_parent_reference", "vin": 50.0, "role": "reference",
     "deck": "sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.cir"},
]

PAIRS = [
    ("48v_base", "48v_prot_a"),
    ("48v_base", "48v_prot_b"),
    ("50v_base_a", "50v_prot_a"),
    ("50v_base_b", "50v_prot_b"),
]


def burden_ohm(deck_text: str) -> float:
    match = BURDEN.search(deck_text)
    if match is None:
        raise ValueError("deck has no 'Rbur <a> <b> <ohm>' element")
    return float(match.group(3))


def pulse(t: np.ndarray, v: np.ndarray, r_ohm: float) -> dict[str, float]:
    """Pulse statistics of ``v`` across ``r_ohm`` over [(t[0], t[-1])]."""
    if t.size < 2:
        raise ValueError(f"a pulse needs two samples, got {t.size}")
    p = v * v / r_ohm
    energy = float(np.trapezoid(p, t))
    i_peak = int(np.argmax(p))
    duration = float(t[-1] - t[0])
    return {
        "v_peak_abs_v": float(np.max(np.abs(v))),
        "peak_w": float(p[i_peak]),
        "t_peak_us": float(t[i_peak]) * 1e6,
        "mean_w": energy / duration,
        "energy_j": energy,
        "equivalent_width_us": energy / float(p[i_peak]) * 1e6,
        "duration_us": duration * 1e6,
    }


def analyze(spec: dict) -> dict:
    deck = ROOT / "sim/v3" / spec["deck"]
    raw = deck.with_suffix(".raw")
    text = deck.read_text(encoding="utf-8")
    fault_window = hot_fault_metrics.saved_fault_window(text)
    engage = float(fault_window["engage_rebased_s"])
    # The PWL ramp opens part-way through the last saved period; the samples
    # between the ramp start and the switch threshold are neither a clean
    # pre-fault state nor the fault itself, so they are excluded rather than
    # being charged to the pre-fault mean.
    ramp_start = float(fault_window["ramp_start_abs_s"]) - float(fault_window["tstart_s"])
    stop = hot_fault_metrics.saved_stop_s(text)
    r_ohm = burden_ohm(text)

    # Read the whole record: the identity test is against the raw's own tail,
    # not against a window that stops short of it.
    t, data = read_window(raw, ["V(ocd)", "V(ocm)"], 0.0, None)
    v = data["V(ocd)"] - data["V(ocm)"]

    before = t < ramp_start
    after = t >= engage
    if before.sum() < 2 or after.sum() < 2:
        raise ValueError(f"{spec['run']}: fault at {engage:.6g} s splits the window apart")

    fault = pulse(t[after], v[after], r_ohm)
    t_pre, v_pre = t[before], v[before]
    pre_duration = float(t_pre[-1] - t_pre[0])
    mean_v = float(np.trapezoid(v_pre, t_pre)) / pre_duration
    rms_v = float(np.sqrt(np.trapezoid(v_pre * v_pre, t_pre) / pre_duration))
    return {
        "run": spec["run"],
        "vin_v": spec["vin"],
        "role": spec["role"],
        "deck": str(deck.relative_to(ROOT)).replace("\\", "/"),
        "burden_ohm": r_ohm,
        "window": {
            "ramp_start_us": round(ramp_start * 1e6, 4),
            "fault_start_us": round(engage * 1e6, 4),
            "saved_stop_us": round(stop * 1e6, 4),
            "last_sample_us": round(float(t[-1]) * 1e6, 4),
            "samples": int(t.size),
            "reached_saved_stop": bool(float(t[-1]) >= stop - 1e-9),
        },
        "pre_fault": {
            # Power is mean(V^2)/R.  SOURCE-05 quoted mean(V)^2/R, which for a
            # rectified waveform is the form factor squared too low.
            "mean_w": round(rms_v * rms_v / r_ohm, 6),
            "mean_voltage_squared_w": round(mean_v * mean_v / r_ohm, 6),
            "mean_voltage_v": round(mean_v, 5),
            "rms_voltage_v": round(rms_v, 5),
            "form_factor": round(rms_v / mean_v, 5),
            "samples": int(before.sum()),
        },
        "fault": {
            "v_peak_abs_v": round(fault["v_peak_abs_v"], 5),
            "peak_w": round(fault["peak_w"], 5),
            "t_peak_us": round(fault["t_peak_us"], 3),
            "mean_w": round(fault["mean_w"], 6),
            "energy_mj": round(fault["energy_j"] * 1e3, 6),
            "equivalent_width_us": round(fault["equivalent_width_us"], 3),
            "duration_us": round(fault["duration_us"], 3),
        },
        "rating": {
            "part": RATED_PART,
            "power_w": RATED_POWER_W,
            "peak_over_rated": round(fault["peak_w"] / RATED_POWER_W, 2),
            "energy_in_rated_watt_seconds": round(fault["energy_j"] / RATED_POWER_W * 1e6, 2),
        },
    }


def benefit(base: dict, candidate: dict) -> dict:
    b, c = base["fault"], candidate["fault"]
    return {
        "base_run": base["run"],
        "candidate_run": candidate["run"],
        "vin_v": base["vin_v"],
        "peak_reduction_pct": round((b["peak_w"] - c["peak_w"]) / b["peak_w"] * 100.0, 3),
        "energy_reduction_pct": round((b["energy_mj"] - c["energy_mj"]) / b["energy_mj"] * 100.0, 3),
        "candidate_peak_w": c["peak_w"],
        "candidate_energy_mj": c["energy_mj"],
    }


def build() -> dict:
    runs = [analyze(spec) for spec in RUNS]
    by_run = {run["run"]: run for run in runs}
    benefits = [benefit(by_run[b], by_run[c]) for b, c in PAIRS]
    return {
        "kind": "ct_burden_fault_pulse",
        "evidence_level": "SIMULATED_ONLY / NO_VENDOR_PULSE_CURVE",
        "results": {
            "rated_part": RATED_PART,
            "rated_power_w": RATED_POWER_W,
            "pulse_curve_available": False,
            "runs": runs,
            "benefits": benefits,
            "limits": [
                "the 0.125 W figure is a continuous rating from a search summary; the "
                "datasheet text and pulse-derating curve are not vendored, so the peak is "
                "an input to part selection, not a pass/fail",
                "a 13 us pulse is not continuous dissipation; comparing it with the nominal "
                "power is a screening ratio only",
                "the startup pulse is not measured: the 8 ms cold-start deck does not save "
                "V(ocd)/V(ocm)",
                "the CT model is ideal (Lct2 = 20 mH, Kct = 1), so core saturation and "
                "magnetising current are absent from this burden voltage",
                "50 V benefits use the complete Vt=10 controls, not the declared parent; the "
                "control clamps leak 1 nA (measured on a probe deck) but the run still sits "
                "13.2/17.5 mV from the candidate before the fault, so the 50 V percentages are "
                "screening numbers, not paired effects.  The exactly-paired threshold-muted "
                "control stalls at 250.151/254.980 us and cannot price a full pulse",
                "the parent rows are reference only and are not paired",
                "the rated power is the resistor's nominal value, not a temperature-derated "
                "value at the local ambient",
                "the steady burden power is mean(V^2)/R; the 69.6/103 mW figures in SOURCE-05 "
                "used mean(V)^2/R and are low by the form factor squared (about 1.21x)",
                "samples between the fault ramp start and the switch threshold belong to "
                "neither segment and are excluded from both",
            ],
        },
        "checks": {
            "every_run_reached_the_saved_stop": all(
                run["window"]["reached_saved_stop"] for run in runs),
            "the_burden_is_ten_ohms_everywhere": all(
                run["burden_ohm"] == 10.0 for run in runs),
            # The stored fields are rounded for readability, so the identity can
            # only be checked within the rounding noise (~2e-7 J here).
            "energy_and_mean_power_agree": all(
                abs(run["fault"]["energy_mj"] * 1e-3
                    - run["fault"]["mean_w"] * run["fault"]["duration_us"] * 1e-6) < 1e-6
                for run in runs),
            "the_peak_is_not_reported_as_a_continuous_rating": True,
            "the_pre_fault_power_is_not_the_mean_voltage_squared": all(
                run["pre_fault"]["mean_w"] >= run["pre_fault"]["mean_voltage_squared_w"]
                for run in runs),
            "the_pre_fault_window_stops_at_the_fault_ramp": all(
                run["window"]["ramp_start_us"] <= run["window"]["fault_start_us"] for run in runs),
            "benefits_are_computed_only_against_a_matching_base": all(
                by_run[base]["vin_v"] == by_run[cand]["vin_v"] and by_run[base]["role"] == "base"
                for base, cand in PAIRS),
            # A prefix would price a fraction of the pulse as if it were the
            # whole thing; the 50 V base must be the complete control.
            "the_50v_base_is_a_complete_topology_matched_control": all(
                by_run[base]["window"]["reached_saved_stop"]
                and by_run[base]["deck"].endswith("_noclamp_control.cir")
                for base, cand in PAIRS if by_run[base]["vin_v"] == 50.0),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=OUT)
    args = ap.parse_args(argv)
    payload = build()
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.json}")
    for run in payload["results"]["runs"]:
        f = run["fault"]
        print(f"  {run['run']:22s} {run['vin_v']:4.0f} V  peak {f['peak_w']:7.3f} W "
              f"@ {f['t_peak_us']:7.2f} us  E {f['energy_mj']:8.5f} mJ  "
              f"t_eq {f['equivalent_width_us']:6.2f} us")
    for b in payload["results"]["benefits"]:
        print(f"  {b['candidate_run']:22s} vs {b['base_run']:14s} "
              f"peak {b['peak_reduction_pct']:+7.2f} %  energy {b['energy_reduction_pct']:+7.2f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
