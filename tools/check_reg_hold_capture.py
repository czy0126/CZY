"""Check H1 scope evidence, without certifying power-stage commutation or thermal safety."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

COLUMNS = ("t_s", "fault_v", "vdd_v", "reg_v", "vgs1_v", "vgs2_v",
           "vd1_v", "vd2_v", "bias_a", "psu_cc")


def evaluate(rows, *, hold_s=100e-6, deadline_s=25e-6, max_step_s=.1e-6):
    if not 0 < deadline_s < hold_s or max_step_s <= 0:
        raise ValueError("invalid engineering check window")
    reasons = []
    result = {"status": "REJECTED", "reasons": reasons, "hardware_qualified": False,
              "thermal_qualified": False, "commutation_qualified": False,
              "criteria": {"hold_s": hold_s, "deadline_s": deadline_s,
                           "max_step_s": max_step_s,
                           "basis": "engineering waveform criteria, not guaranteed device timing"}}
    if len(rows) < 3 or any(any(k not in r or not math.isfinite(r[k]) for k in COLUMNS) for r in rows):
        reasons.append("MISSING_OR_NONFINITE_SAMPLES")
        return result
    dt = [b["t_s"]-a["t_s"] for a,b in zip(rows, rows[1:])]
    if min(dt) <= 0 or max(dt) > max_step_s*(1+1e-6):
        reasons.append("NONMONOTONIC_OR_UNDERSAMPLED_TRACE")
        return result
    highs = [i for i,r in enumerate(rows) if r["fault_v"] >= 2]
    if not highs or highs[0] == 0:
        reasons.append("NO_CAPTURED_FAULT_EDGE")
        return result
    i0 = highs[0]
    t0 = rows[i0]["t_s"]
    if rows[0]["t_s"] > t0-10e-6+1e-12 or rows[-1]["t_s"] < t0+hold_s-1e-12:
        reasons.append("INCOMPLETE_PRETRIGGER_OR_HOLD_WINDOW")
        return result
    pre = [r for r in rows if t0-10e-6-1e-12 <= r["t_s"] < t0]
    hold = [r for r in rows if t0 <= r["t_s"] < t0+hold_s-1e-12]
    off = [r for r in hold if r["t_s"] >= t0+deadline_s-1e-12]
    if not pre or not off:
        reasons.append("EMPTY_CHECK_WINDOW")
        return result
    checks = {
        "fault_was_low": all(r["fault_v"] <= .8 for r in pre),
        "fault_held": all(r["fault_v"] >= 2 for r in hold),
        "regulated_vdd": all(14.25 <= r["vdd_v"] <= 15.75 for r in pre+hold),
        "no_current_limit": all(r["psu_cc"] == 0 for r in pre+hold),
        "reg_started": all(r["reg_v"] >= 9.9 for r in pre),
        "no_pretrigger_both_high": all(min(r["vgs1_v"], r["vgs2_v"]) < 4 for r in pre),
        "gate_active_at_fault": max(rows[i0-1]["vgs1_v"], rows[i0-1]["vgs2_v"]) >= 4,
        "reg_below_off_threshold": all(r["reg_v"] <= 3.63 for r in off),
        "both_gates_stay_low": all(max(r["vgs1_v"],r["vgs2_v"]) <= 1 for r in off),
    }
    for ch in (1,2):
        run_start = None
        longest = 0.0
        for row in pre:
            if row[f"vgs{ch}_v"] >= 4:
                if run_start is None:
                    run_start = row["t_s"]
                longest = max(longest, row["t_s"]-run_start)
            else:
                run_start = None
        checks[f"channel_{ch}_exercised_before_fault"] = longest >= .2e-6-1e-12
        # Continuing both polarities prevents cessation of VD stimulus from
        # being mistaken for successful inhibition by the fault circuit.
        windows = []
        start = deadline_s
        while start < hold_s-1e-12:
            segment = [r[f"vd{ch}_v"] for r in off
                       if t0+start-1e-12 <= r["t_s"] < t0+min(start+10e-6, hold_s)-1e-12]
            windows.append(bool(segment) and max(segment) > 1.7 and min(segment) < -.1)
            start += 10e-6
        checks[f"channel_{ch}_stimulus_continues"] = all(windows)
    result["checks"] = checks
    result["fault_time_s"] = t0
    result["sample_count"] = len(rows)
    reasons.extend(k for k, passed in checks.items() if not passed)
    if not reasons:
        result["status"] = "WAVEFORM_CRITERIA_PASS_ONLY"
    return result


def check_manifest(path):
    path = Path(path)
    meta = json.loads(path.read_text(encoding="utf-8-sig"))
    missing = [k for k in ("board_revision", "instrument", "scope_bandwidth_hz",
                          "probe_mapping", "bias_limit_a", "capture_csv") if not meta.get(k)]
    if meta.get("capture_kind") != "hardware" or missing:
        return {"status": "NOT_READY", "hardware_qualified": False,
                "reasons": ["hardware capture metadata missing or not declared", *missing]}
    if not isinstance(meta["probe_mapping"], dict) or any(not meta["probe_mapping"].get(k) for k in COLUMNS):
        return {"status": "NOT_READY", "hardware_qualified": False, "reasons": ["incomplete channel mapping"]}
    source = (path.parent/meta["capture_csv"]).resolve()
    if not source.is_file():
        return {"status": "NOT_READY", "hardware_qualified": False, "reasons": ["capture file absent"]}
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = [{k: float(row[k]) for k in COLUMNS} for row in csv.DictReader(stream)]
    result = evaluate(rows)
    result["source_csv_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["note"] = "Metadata provenance must be reviewed; a CSV cannot prove its own hardware origin."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check_manifest(args.manifest)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        result = {"status": "REJECTED", "hardware_qualified": False,
                  "reasons": [f"invalid capture: {type(exc).__name__}: {exc}"]}
    payload = json.dumps(result, ensure_ascii=False, indent=2)+"\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if result["status"] == "WAVEFORM_CRITERIA_PASS_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
