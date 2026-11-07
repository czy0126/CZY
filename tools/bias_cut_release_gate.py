"""Fail-closed release assessment for the D1 SR bias-cut ECO.

Separates three distinct things:
  (1) valid logic / behavioural LTspice measurements,
  (2) a physically allowable always-on discharge path under reverse supply,
  (3) real MOSFET/SOA, OEM corner and oscilloscope evidence.

The 47-ohm R57 is switched ON whenever the bias is disabled. At a sustained
18 V external backfeed, it is a continuous load -- not an 11.1 uF one-shot.
An unguarded single 0.25 W resistor cannot simultaneously discharge 11.1 uF
from 15 to 3.63 V in 1 ms and dissipate <=0.25 W at 18 V.

Example:
  python tools/bias_cut_release_gate.py
  python tools/bias_cut_release_gate.py --require-release  # exits 2 while blocked

This tool does not fabricate a schematic correction, and cannot authorize a
power-stage build, power-up, or any hardware acceptance.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import make_bias_cut_eco as eco

ROOT = Path(__file__).resolve().parents[1]
SIM = eco.OUT / "sim_run.json"
MISMATCH = eco.OUT / "bias_cut_reverse_mismatch.json"
H1 = ROOT / "pcb/sr_fault_validation/h1_evidence_status.json"

# These are engineering comparison criteria, not OEM guaranteed limits.
DISCHARGE_DEADLINE_S = 1e-3
REG_UVLO_REPORT_V = 3.63


def positive_number(text: str, pattern: str, name: str) -> float:
    result = re.search(pattern, text, re.MULTILINE)
    if not result:
        raise ValueError(f"cannot trace {name} to the source deck")
    value = float(result.group(1))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def design_inputs() -> dict:
    """Read physical R57 and Q54 wiring and electrical stress from live sources."""
    parts = {part.ref: part for part in eco.parts() if not part.ref.startswith("#")}
    r57 = parts["R57"]
    q54 = parts["Q54"]
    c54 = parts["C54"]
    if r57.nets != {"1": "VDD_SR", "2": "VDD_DIS"}:
        raise ValueError("R57 wiring changed; reverse discharge must be re-audited")
    if q54.nets != {"1": "ENABLE_N", "2": "PGND", "3": "VDD_DIS"}:
        raise ValueError("Q54 no longer has the audited normally-on-during-fault path")

    resistance = positive_number(
        r57.value, r"^(\d+(?:\.\d+)?)R$", "R57 ohms")
    rating_m = re.search(r"(\d+)\s*/\s*(\d+)\s*W", r57.rating)
    if not rating_m:
        raise ValueError("R57 continuous power rating is not explicit")
    continuous_w = int(rating_m.group(1)) / int(rating_m.group(2))
    if not math.isfinite(continuous_w) or continuous_w <= 0:
        raise ValueError("invalid declared R57 rating")

    seq = eco.sequence_deck()
    rev = eco.reverse_deck()
    for desc, deck in [("sequence", seq), ("reverse", rev)]:
        source_r = positive_number(
            deck, r"^\s*R57\s+VDD_SR\s+VDD_DIS\s+(\d+(?:\.\d+)?)\s*$",
            f"{desc} deck R57")
        if not math.isclose(source_r, resistance, rel_tol=0, abs_tol=1e-9):
            raise ValueError("schematic and " + desc + " model use different R57")
        model_c = positive_number(
            deck, r"^\s*C54\s+VDD_SR\s+0\s+(\d+(?:\.\d+)?)u\s*$",
            f"{desc} deck C54") * 1e-6
        if not math.isclose(model_c, 11.1e-6, rel_tol=1e-5):
            raise ValueError("C54 in deck is not the reviewed 11.1uF equivalent bank")
        if not re.search(r"^\s*(?:S54|Q54)\s+VDD_DIS\s+0\s+ENABLE_N\s+0\s+", deck, re.M):
            raise ValueError("Q54 fault-enable model changed: refresh safety analysis")
    if c54.value.lower().replace(" ", "") != "11.1uf":
        raise ValueError("C54 schematic value differs from both deck models")

    nominal_v = positive_number(seq, r"^\.param\s+VDD=(\d+(?:\.\d+)?)\s*$",
                                "15V supply")
    reverse_v = positive_number(
        rev, r"^VREV\s+VREV_SRC\s+0\s+(\d+(?:\.\d+)?)\s*$",
        "reverse supply")
    return {
        "r57_ohm": resistance, "r57_continuous_rating_w": continuous_w,
        "c_bank_f": model_c, "normal_vdd_v": nominal_v,
        "reverse_source_v": reverse_v,
        "discharge_to_v": REG_UVLO_REPORT_V,
        "max_discharge_time_s": DISCHARGE_DEADLINE_S,
        "always_on_during_fault_and_reverse": True,
        "r57_mpn": r57.mpn if r57.mpn else "TO_SELECT",
        "pmos_mpn": {
            k: (parts[k].mpn if parts[k].mpn else "TO_SELECT")
            for k in ("Q50", "Q51", "Q55")
        },
    }


def envelope(*, resistance_ohm: float, capacitance_f: float, start_v: float,
             threshold_v: float, reverse_v: float,
             continuous_w: float, deadline_s: float) -> dict:
    """Ideal RC & V^2/R lower-envelope for an indefinitely energized output.

    Assumes a resistor remains connected to VDD_SR when VDD_SR is externally
    held high, and ignores MOSFET Ron so does not claim a verified thermal
    worst case. This is enough to falsify a naive resistor-only fix.
    """
    vals = (resistance_ohm, capacitance_f, start_v, threshold_v,
            reverse_v, continuous_w, deadline_s)
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError("envelope inputs must be positive and finite")
    if not threshold_v < start_v:
        raise ValueError("discharge threshold must be below initial voltage")
    log_ratio = math.log(start_v / threshold_v)
    r_fast_max = deadline_s / (capacitance_f * log_ratio)
    r_cool_min = reverse_v * reverse_v / continuous_w
    current_at_reverse_a = reverse_v / resistance_ohm
    return {
        "time_to_threshold_s": resistance_ohm * capacitance_f * log_ratio,
        "ideal_resistor_power_at_reverse_w": reverse_v * reverse_v / resistance_ohm,
        "ideal_reverse_current_a": current_at_reverse_a,
        "r_discharge_max_ohm": r_fast_max,
        "r_continuous_power_min_ohm": r_cool_min,
        "incompatible_single_resistor_goals": r_cool_min > r_fast_max,
        "thermal_overrating_factor_at_reverse":
            (reverse_v * reverse_v / resistance_ohm) / continuous_w,
        "fast_discharge_at_current_r": resistance_ohm <= r_fast_max,
        "within_continuous_rating_at_current_r": resistance_ohm >= r_cool_min,
        "basis": "ideal RC; steady external reverse source; NOT component qualification",
    }


def assess() -> dict:
    d = design_inputs()
    math_case = envelope(
        resistance_ohm=d["r57_ohm"], capacitance_f=d["c_bank_f"],
        start_v=d["normal_vdd_v"], threshold_v=d["discharge_to_v"],
        reverse_v=d["reverse_source_v"],
        continuous_w=d["r57_continuous_rating_w"],
        deadline_s=d["max_discharge_time_s"])
    blockers = []
    if math_case["incompatible_single_resistor_goals"]:
        blockers.append(
            "R57 resistor-only change cannot meet both <1ms discharge and "
            "0.25W sustained 18V reverse backfeed; use a controlled/isolated "
            "discharge path or explicitly revise requirements.")
    if not math_case["within_continuous_rating_at_current_r"]:
        blockers.append("R57 is over its declared continuous rating when external reverse drive persists")
    if any(v == "TO_SELECT" for v in d["pmos_mpn"].values()):
        blockers.append("Q50/Q51/Q55 OEM P-MOS selection and Vgs/SOA not closed")

    if not SIM.is_file():
        blockers.append("sequence/reverse simulation manifest missing")
        run = {}
    else:
        run = json.loads(SIM.read_text(encoding="utf-8"))
        if run.get("status") != "RUN":
            blockers.append("sequence/reverse simulation manifest is not an approved RUN")
        if not run.get("all_checks_pass"):
            blockers.append("logic/behavioural simulation checks are not passing")
        stress = run.get("stress_assessment", {})
        if stress.get("inrush_soa_qualified") is not True:
            blockers.append("power-up MOSFET inrush and SOA unqualified")
        # The measured simulated reverse power has a finite switch Ron; the
        # ideal constant-voltage ratio is not expected to be identical.
        p_meas = stress.get("reverse_r57_power_w")
        if not isinstance(p_meas, (float, int)) or not math.isfinite(p_meas) or p_meas < 0:
            blockers.append("reverse R57 simulation stress evidence missing")
        elif p_meas > d["r57_continuous_rating_w"]:
            blockers.append("LTspice also reports R57 above continuous rating")
        if run.get("design_ready") is True:
            blockers.append("inconsistent source: simulated design_ready=true despite uncleared stress")

    if not MISMATCH.is_file():
        blockers.append("hypothetical reverse threshold mismatch case not yet reviewed")
        reverse_case = {}
    else:
        reverse_case = json.loads(MISMATCH.read_text(encoding="utf-8"))
        if reverse_case.get("passes_100ua_screen") is not False:
            blockers.append("hypothetical reverse mismatch evidence absent or incorrectly marked pass")
        blockers.append("reverse blocking fails in the hypothetical 16V threshold-mismatch scenario; OEM corners needed")

    if not H1.is_file():
        blockers.append("H1 scope evidence missing")
        h1 = {}
    else:
        h1 = json.loads(H1.read_text(encoding="utf-8"))
        if h1.get("hardware_qualified") is not True:
            blockers.append("real H1/H5 oscilloscope and bias backfeed evidence not yet qualified")

    return {
        "status": "BLOCKED_NOT_FOR_FAB" if blockers else "SOURCE_REVIEW_REQUIRED",
        "fab_release": False,
        "hardware_qualified": False,
        "inputs": d,
        "envelope": math_case,
        "simulator_checks_pass": bool(run.get("all_checks_pass")),
        "reverse_mismatch_hypothetical_only": True,
        "blocks": blockers,
        "next_decision": (
            "Do not simply increase R57 or use its 0.25W pulse rating as a "
            "continuous rating. Redesign reverse-aware discharge isolation; "
            "choose OEM P-MOS and current-limited startup; rerun device-level "
            "reverse corners and hardware H1/H5 before release."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--require-release", action="store_true",
                    help="Return code 2 unless the release evidence is complete")
    args = ap.parse_args()
    try:
        report = assess()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report = {"status": "BLOCKED_INVALID_SOURCE",
                  "fab_release": False, "blocks": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_release and report["status"] != "SOURCE_REVIEW_REQUIRED":
        return 2
    return 0 if report["status"] != "BLOCKED_INVALID_SOURCE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
