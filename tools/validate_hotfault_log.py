"""Fail-closed LTspice *log* validator for 48/50V hot-start 120A fault candidates.

A solver producing a .log/.raw and a numeric peak does NOT establish that
an overcurrent event happened *after* a settled operating point. In
particular, the completed 48V cold fault was injected while V(ss)=3.78V.

This checks model-log consistency ONLY, not hardware, actual magnetic SOA,
true current sharing or 0.2W energy closure. The .raw still needs probing.

Usage:
  python tools/validate_hotfault_log.py --case 48v_120a --log PATH --raw PATH --json PATH
No report is emitted on invalid/unfinished data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
CASES = {
    "48v_120a": {
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir",
        "operating_point": PP / "operating_point_48v_120a.json",
    },
    "50v_120a": {
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a.cir",
        "operating_point": PP / "operating_point_50v_120a.json",
    },
}
# All times below are on the SAVED raw/log axis: t_raw = t_absolute-880us.
FAULT_AT_S = 175e-6
RECORDED_TO_S = 320e-6
REQUIRED = ("hot_ctrl_before", "hot_ctrl_after", "hot_iflt_after",
            "hot_oc_before", "hot_vout_before", "hot_ss_before",
            "hot_ipri_after", "hot_oc_after", "hot_vout_min", "hot_oc_trip")
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_log(log_text: str) -> tuple[dict[str, float], list[str]]:
    issues = []
    if not re.search(r"(?im)^\s*total elapsed time:\s*\d", log_text):
        issues.append("solver did not write Total elapsed time; interrupted/prefix run")
    if re.search(r"(?im)^\s*measurement\s+failed\b|^\s*hot_\w+:\s*fail", log_text):
        issues.append("LTspice indicates a failed measurement")
    lines = {}
    for line in log_text.splitlines():
        match = re.match(r"(?i)^\s*(hot_\w+)\s*:\s*(.*)$", line)
        if match:
            lines[match.group(1).lower()] = match.group(2)
    measured = {}
    for key in REQUIRED:
        body = lines.get(key)
        if body is None:
            issues.append(f"{key} is absent from LTspice .meas output")
            continue
        if key == "hot_oc_trip":
            match = re.search(r"\bAT\s+(" + NUMBER + r")\b", body, re.I)
        else:
            match = re.search(r"=\s*(" + NUMBER + r")", body, re.I)
        if not match:
            issues.append(f"{key} value/time unparseable")
            continue
        value = float(match.group(1))
        if not math.isfinite(value):
            issues.append(f"{key} non-finite")
            continue
        measured[key] = value
    return measured, issues


def build(case: str, log: Path, raw: Path) -> dict:
    if case not in CASES:
        raise ValueError(f"unsupported case: {case}")
    spec = CASES[case]
    deck = spec["deck"]
    op = json.loads(spec["operating_point"].read_text(encoding="utf-8"))
    baseline_vout = float(op["vout_avg_v"])
    log_text = log.read_text(encoding="utf-8", errors="replace")
    result, issues = parse_log(log_text)
    # Guard accidental reuse of a different deck or pre-existing run.
    circuit = re.search(r"(?im)^\s*circuit:\s*(.+)$", log_text)
    if circuit is None or deck.name.lower() not in circuit.group(1).lower().replace("\\", "/"):
        issues.append("log Circuit line does not identify the requested exact deck")
    if not raw.is_file() or raw.stat().st_size == 0:
        issues.append("non-empty raw file absent")
    else:
        # Scan only a small header, never read a multi-GB waveform in RAM.
        with raw.open("rb") as stream:
            header = stream.read(65536).decode("latin1", errors="replace")
        if ("Plotname: Transient Analysis" not in header
                or "Variables:" not in header
                or not any(mark in header for mark in ("Values:", "Binary:"))):
            issues.append("raw does not have a valid-looking LTspice transient header")
    if len(result) == len(REQUIRED):
        if abs(result["hot_ctrl_before"]) > 0.2:
            issues.append("fault control was not off before injection")
        if result["hot_ctrl_after"] < 4.5:
            issues.append("fault control did not reach switch-on voltage")
        if result["hot_iflt_after"] <= 1:
            issues.append("no verified injected fault-branch current")
        ss = result["hot_ss_before"]
        if not (4.8 <= ss <= 5.1):
            issues.append(f"V(ss) pre-fault not settled near 5V: {ss}")
        vout = result["hot_vout_before"]
        if abs(vout - baseline_vout) > max(0.02, 0.02 * baseline_vout):
            issues.append(f"pre-fault Vout {vout} not near matched steady-state {baseline_vout}")
        if not (0 <= result["hot_oc_before"] < 1):
            issues.append("pre-fault OC already at/above 1V or negative")
        if result["hot_oc_after"] < 1:
            issues.append("fault OC never reached the 1V comparator threshold")
        if not (FAULT_AT_S <= result["hot_oc_trip"] <= RECORDED_TO_S):
            issues.append("OC crossing not within post-fault saved-time window")
        if result["hot_ipri_after"] <= 0:
            issues.append("fault-current probe is zero/negative")
        if result["hot_vout_min"] > vout + 0.05:
            issues.append("fault Vout minimum inconsistent with pre-fault level")
    return {
        "status": "LOG_PRECHECK_PASS_REQUIRES_WAVEFORM_AND_DEVICE_REVIEW" if not issues
                  else "LOG_PRECHECK_FAIL",
        "case": case,
        "evidence_level": "LTSPICE_SIMULATION_ONLY_NOT_HARDWARE",
        "not_rated": True,
        "deck": deck.relative_to(ROOT).as_posix(),
        "deck_sha256": sha(deck),
        "log": log.as_posix(),
        "log_sha256": sha(log),
        "raw": raw.as_posix(),
        "raw_bytes": raw.stat().st_size if raw.is_file() else 0,
        "baseline_model_vout_v": baseline_vout,
        "fault_time_in_saved_axis_s": FAULT_AT_S,
        "probes": result,
        "blockers": issues,
        "limits": [
            "log checks prove only syntactic .meas consistency and pre/post operating state",
            "verify exact raw timing, peak stress, diode conduction, multi-event OC and actual SR gating",
            "no thermal, SOA, manufacturer magnetic or hardware release approval",
            "power/current/efficiency still model only; failure to finish run is fatal",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=sorted(CASES), required=True)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    result = build(args.case, args.log, args.raw)
    print(result["status"])
    for issue in result["blockers"]:
        print("BLOCKED", issue)
    if result["blockers"]:
        return 2
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
