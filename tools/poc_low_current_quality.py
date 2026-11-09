"""Read-only quality screen for REAL low-current D1 LTspice result records.

The existing "complete RAW" check means all points finite through 8 ms.
It does NOT mean the 6-8 ms voltage/current is steady. In the real
2026-11-09 5A SR_ON run, mean Vout=1.84307V but min(6-8ms)=1.63829V.
A 0.491V SR_ON/OFF *start-up-window* difference must not be advertised
as steady-state regulation, thermal performance, efficiency or hardware.

This tool reads only tracked JSON record snapshots. The large RAW binaries are
not committed: their hashes in these records are references, NOT newly
recomputed proof. Never mutate the golden deck or the existing real report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "sim/v3"
CASES = {"5a": 0.4, "10a": 0.2}
WINDOW_VARIATION_ALERT = 0.05
KEYS = (
    "poc_vout_6_8_avg", "poc_vout_min", "poc_vout_max",
    "poc_input_min", "poc_input_max", "poc_primary_max",
    "poc_rectifier_current_max", "poc_gate_a1_max", "poc_gate_b1_max",
)
HEX64 = re.compile(r"^[a-f0-9]{64}$")


def finite_measure(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v) and abs(v) < 1e100


def evaluate_run(record: dict | None, resistor_ohm: float) -> dict:
    if record is None:
        return {
            "status": "NO_COMPLETED_SIMULATION_RECORD",
            "complete_8ms_claim": False,
            "steady_state_qualified": False,
            "hardware_qualified": False,
        }
    values = record.get("measures", {})
    raw = record.get("raw_evidence", {})
    verified_fields = (
        record.get("status") == "SIMULATION_ONLY"
        and record.get("LTspice_batch_executed") is True
        and raw.get("status") == "RAW_ALL_FINITE_AND_TIME_COMPLETE"
        and finite_measure(raw.get("last_time_s"))
        and raw["last_time_s"] >= 0.008 - 1e-7
        and re.fullmatch(r"LTspice (?:2[6-9]|[3-9]\d)\.\d+\.\d+",
                         record.get("engine_version", "")) is not None
        and all(finite_measure(values.get(key)) for key in KEYS)
        and all(HEX64.fullmatch(record.get(k, "")) is not None
                for k in ("deck_sha256", "log_sha256", "raw_sha256"))
        and record.get("hardware_qualified") is False
    )
    if not verified_fields:
        return {
            "status": "INCOMPLETE_OR_INCONSISTENT_RECORDED_EVIDENCE",
            "complete_8ms_claim": False,
            "steady_state_qualified": False,
            "hardware_qualified": False,
        }

    avg = values["poc_vout_6_8_avg"]
    minimum = values["poc_vout_min"]
    # Both refer to 6-8 ms. poc_vout_max is 0-8 ms: never subtract it
    # from minimum and relabel the result as a 6-8 ms ripple magnitude.
    if avg < minimum - 1e-8:
        return {
            "status": "INCONSISTENT_AVG_BELOW_MIN",
            "complete_8ms_claim": False,
            "steady_state_qualified": False,
            "hardware_qualified": False,
        }
    min_to_mean_fraction = max(avg - minimum, 0.0) / max(abs(avg), 1e-9)
    dynamic = min_to_mean_fraction > WINDOW_VARIATION_ALERT
    return {
        "status": ("DYNAMIC_6_TO_8MS_WINDOW_NOT_STEADY"
                   if dynamic else "MIN_GAP_SMALL_NOT_STEADY_PROOF"),
        "complete_8ms_claim": True,
        "steady_state_qualified": False,
        "hardware_qualified": False,
        "recorded_raw_hash_NOT_REHASHED": record["raw_sha256"],
        "recorded_log_hash_NOT_REHASHED": record["log_sha256"],
        "engine": record["engine_version"],
        "output_v_avg_6_to_8ms": avg,
        "output_v_min_6_to_8ms": minimum,
        "output_v_max_0_to_8ms_not_same_window": values["poc_vout_max"],
        "min_to_mean_variation_lower_bound_fraction": round(min_to_mean_fraction, 8),
        "variation_alert_threshold_fraction": WINDOW_VARIATION_ALERT,
        "estimated_mean_output_current_a": round(avg / resistor_ohm, 8),
        "output_current_is_model_resistor_derived": True,
        "model_primary_abs_peak_a_0_to_8ms": values["poc_primary_max"],
        "model_rectifier_abs_peak_a_0_to_8ms": values["poc_rectifier_current_max"],
        "model_input_peak_a_0_to_8ms": values["poc_input_max"],
        "startup_peaks_are_NOT_continuous_ratings": True,
        "raw_binary_physically_rehashed_here": False,
    }


def evaluate_case(case: str, doc: dict, doc_sha256: str) -> dict:
    if case not in CASES:
        raise ValueError("unsupported load")
    if doc.get("case") != case:
        raise ValueError("result document case does not match filename")
    if doc.get("fab_release") is not False or doc.get("status") not in (
        "MODEL_SIMULATION_ONLY_NOT_FOR_HARDWARE",
        "INCOMPLETE_OR_INVALID_SIMULATION",
    ):
        raise ValueError("model evidence is not appropriately disclaimed")
    runs = doc.get("runs", {})
    if not isinstance(runs, dict) or set(runs) - {"on", "off"}:
        raise ValueError("unexpected modes in evidence report")
    screened = {
        mode: evaluate_run(runs.get(mode), CASES[case])
        for mode in ("on", "off")
    }
    both_finished = all(x["complete_8ms_claim"] for x in screened.values())
    # Min-to-mean is only one lower bound on variation, so even if
    # neither crosses 5% we still have NO positive steady-state evidence.
    return {
        "case": case,
        "source_report_sha256": doc_sha256,
        "source": "COMMITTED_JSON_SNAPSHOT_NOT_RAW_REVALIDATION",
        "model_only": True,
        "hardware_fabrication_approved": False,
        "modes": screened,
        "paired_8ms_comparison_recorded": both_finished,
        "paired_steady_state_comparison_qualified": False,
        "efficiency_or_100a_qualification": False,
        "next_evidence": (
            "Acquire phase-aligned late-window Vout extrema and average, "
            "capacitance charge balance, model stress durations and full "
            "engine/source hashes before steady-state or thermal claims."
        ),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", choices=("5a", "10a", "both"), default="both")
    p.add_argument("--check", action="store_true",
                   help="validate source report consistency; do not require steady state")
    p.add_argument("--require-steady", action="store_true",
                   help="fail closed until true independent steady-state proof is available")
    args = p.parse_args(argv)
    cases = CASES if args.case == "both" else (args.case,)
    output = {"classification": "SIMULATION_RECORD_QUALITY_READONLY",
              "hardware_release": False, "cases": {}}
    try:
        for case in cases:
            path = DIR / f"poc_{case}_comparison_model_only.json"
            raw = path.read_bytes()
            output["cases"][case] = evaluate_case(
                case, json.loads(raw), hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "EVIDENCE_READ_OR_VALIDATION_FAILED",
                          "reason": str(exc), "hardware_release": False}, indent=2))
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.require_steady:
        return 0 if all(
            all(v["steady_state_qualified"] for v in row["modes"].values())
            for row in output["cases"].values()
        ) else 2
    # Check validates factual consistency only; NOT performance or safety.
    if args.check:
        return 0 if all(
            all(v["status"] not in (
                "INCOMPLETE_OR_INCONSISTENT_RECORDED_EVIDENCE",
                "INCONSISTENT_AVG_BELOW_MIN",
            ) for v in row["modes"].values())
            for row in output["cases"].values()
        ) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
