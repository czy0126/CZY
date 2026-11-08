"""Run selected 48V D1 low-current LTspice A/B models on a licensed Windows PC.

Requires installed Analog Devices LTspice (NOT in repo CI) and calls the
vendor's documented "-b deck.cir" batch interface. Only new, complete logs and fresh nonempty binary RAWs
are accepted. Results are marked SIMULATION_ONLY, never fabrication approval.
Run:
  python tools/run_poc_low_current.py --case 5a --mode both --run
  python tools/run_poc_low_current.py --case 10a --mode both --run
  python tools/run_poc_low_current.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import poc_low_current_decks as poc


REQUIRED = (
    "poc_vout_6_8_avg", "poc_vout_max", "poc_vout_min",
    "poc_input_min", "poc_input_max", "poc_primary_max",
    "poc_rectifier_current_max", "poc_gate_a1_max",
    "poc_gate_b1_max",
)
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def read_ltspice_log(path: Path) -> str:
    """LTspice 24 writes UTF-16 LE logs in some cases and ASCII in others.

    No errors='replace': a decoded file with embedded NULs is not a valid
    measurement source; the detected encoding is part of exact evidence.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\\xff\\xfe", b"\\xfe\\xff")):
        return raw.decode("utf-16")
    if b"\\x00" in raw[:128]:
        return raw.decode("utf-16-le")
    return raw.decode("utf-8")


def measurements(log_text: str) -> dict[str, float]:
    """LTspice STAT logs: name: MAX(...) = value FROM ... TO ..."""
    parsed: dict[str, float] = {}
    rx = re.compile(rf"^\s*(poc_[a-z0-9_]+)\s*:\s*.*?=\s*({NUMBER})\b",
                    flags=re.IGNORECASE)
    for line in log_text.splitlines():
        m = rx.match(line)
        if not m:
            continue
        key = m.group(1).lower()
        value = float(m.group(2))
        if key in parsed:
            raise ValueError(f"duplicate LTspice .meas {key}")
        # LTspice uses +-1e308 sentinels when a waveform was not measured
        # after a numerical blowup. Python considers 1e308 finite.
        if not math.isfinite(value) or abs(value) >= 1e100:
            raise ValueError(f"invalid/sentinel LTspice .meas {key}: {value}")
        parsed[key] = value
    absent = set(REQUIRED) - parsed.keys()
    if absent:
        raise ValueError(f"missing/failed LTspice .meas: {sorted(absent)}")
    return {key: parsed[key] for key in REQUIRED}


def find_ltspice(explicit: str | None) -> Path | None:
    options = [
        Path(x) for x in (explicit, os.environ.get("LTSPICE"))
        if x
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        options.append(
            Path(local) / "Programs/ADI/LTspice/LTspice.exe")
    prog = os.environ.get("PROGRAMFILES")
    if prog:
        options.append(
            Path(prog) / "ADI/LTspice/LTspice.exe")
    return next((p for p in options if p.is_file()), None)


def measured_load_point(case: str, vals: dict[str, float]) -> dict:
    """For an exact resistor, <Iout>=<Vout>/R, NOT ideal 2V/R.

    Mean voltage squared / R is ONLY DC equivalent output power, NOT the
    time-average of Vout(t)**2/R when ripple exists. No thermal signoff.
    """
    resistance = poc.CASES[(case, "on")]
    vout = vals["poc_vout_6_8_avg"]
    return {
        "resistance_ohm": resistance,
        "model_vout_avg_v": vout,
        "model_iout_avg_a": vout / resistance,
        "nominal_current_at_ideal_2v_a": 2 / resistance,
        "pout_dc_equivalent_only_w": vout * vout / resistance,
        "thermal_or_hardware_qualified": False,
    }


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def simulated_comparison(values: dict[str, dict[str, float]]) -> dict:
    out: dict = {"status": "SIMULATION_ONLY_NO_HARDWARE_RELEASE",
                 "fabrication_approved": False,
                 "performance_verified": False, "modes": values}
    if not all(k in values for k in ("on", "off")):
        out["comparison_available"] = False
        return out
    a = values["on"]["poc_vout_6_8_avg"]
    b = values["off"]["poc_vout_6_8_avg"]
    out["comparison_available"] = True
    out["sr_gain_delta_v"] = a - b
    out["sr_off_relative_drop_fraction"] = (a - b) / max(abs(a), 1e-6)
    out["diagnostic_flags"] = [
        f"{mode}: modelled >2.5V output excursion, review 2V rail and no-load overvoltage"
        for mode in ("on", "off")
        if values[mode]["poc_vout_max"] > 2.5
    ]
    if values["on"]["poc_primary_max"] > 104.17:
        out["diagnostic_flags"].append(
            "SR_ON modelled primary peak exceeds previous 104.17A fault model anchor")
    if values["off"]["poc_primary_max"] > 104.17:
        out["diagnostic_flags"].append(
            "SR_OFF modelled primary peak exceeds previous 104.17A fault model anchor")
    return out


def run_selected(case: str, mode: str, exe: Path) -> dict:
    if (case, mode) not in poc.CASES:
        raise ValueError("unsupported case or mode")
    deck = poc.path(case, mode)
    if deck.read_text(encoding="utf-8") != poc.deck(case, mode):
        raise ValueError("generated circuit stale; run poc_low_current_decks.py --write")
    log = deck.with_suffix(".log")
    raw = deck.with_suffix(".raw")
    start = time.time_ns()
    cmd = [str(exe), "-b", str(deck.resolve())]
    completed = subprocess.run(
        cmd, cwd=deck.parent, capture_output=True,
        text=True, errors="replace", check=False, timeout=900)
    if completed.returncode != 0:
        tail = read_ltspice_log(log)[-1600:] if log.is_file() else "(no log)"
        raise RuntimeError(
            f"LTspice {mode}/{case} failed exit={completed.returncode}; "
            f"real log tail: {tail}; stderr: {completed.stderr[-500:]}")

    if not log.is_file() or log.stat().st_mtime_ns < start or not log.stat().st_size:
        raise RuntimeError(f"no fresh LTspice log for {deck.name}")
    if not raw.is_file() or raw.stat().st_mtime_ns < start or not raw.stat().st_size:
        raise RuntimeError(f"no fresh, nonempty LTspice .raw for {deck.name}")
    m = measurements(read_ltspice_log(log))
    return {
        "status": "SIMULATION_ONLY",
        "deck": deck.relative_to(poc.ROOT).as_posix(),
        "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
        "log": log.relative_to(poc.ROOT).as_posix(),
        "log_sha256": digest_file(log),
        "raw": raw.relative_to(poc.ROOT).as_posix(),
        "raw_sha256": digest_file(raw),
        "raw_bytes": raw.stat().st_size,
        "spice_executable": str(exe),
        "LTspice_batch_executed": True,
        "hardware_qualified": False,
        "measures": m,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("5a", "10a"), default="5a")
    parser.add_argument("--mode", choices=("on", "off", "both"), default="both")
    parser.add_argument("--ltspice", help="absolute path to installed LTspice.exe")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--run", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        statuses = {
            f"{case}_{mode}": {
                "deck_present": poc.path(case, mode).is_file(),
                "deck_fresh": poc.path(case, mode).is_file()
                              and poc.path(case, mode).read_text(encoding="utf-8")
                              == poc.deck(case, mode),
                "LTspice_run_performed_here": False,
            }
            for (case, mode) in poc.CASES
        }
        print(json.dumps({"status": "SOURCE_ONLY",
                          "cases": statuses,
                          "fabrication_approved": False}, indent=2))
        return 0 if all(v["deck_fresh"] for v in statuses.values()) else 2

    exe = find_ltspice(args.ltspice)
    if exe is None:
        print("LTspice not installed/found; specify --ltspice path on Windows",
              file=sys.stderr)
        return 2
    mode_list = ("on", "off") if args.mode == "both" else (args.mode,)
    statuses = {}
    failures = {}
    for mode in mode_list:
        try:
            statuses[mode] = run_selected(args.case, mode, exe)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            failures[mode] = str(exc)
            print(f"LTspice {args.case}/{mode} invalid: {exc}", file=sys.stderr)
            # Crucial: SR_ON failure cannot prevent independent SR_OFF run.
            # Never fabricate the missing modes or override the failure status.

    compares = simulated_comparison(
        {mode: evidence["measures"] for mode, evidence in statuses.items()})
    report = {
        "source": poc.manifest(),
        "case": args.case,
        "status": ("MODEL_SIMULATION_ONLY_NOT_FOR_HARDWARE" if not failures
                   else "INCOMPLETE_OR_INVALID_SIMULATION"),
        "runs": statuses,
        "failed_modes": failures,
        "all_requested_modes_completed": not failures,
        "comparison": compares,
        "model_actual_load_points": {
            mode: measured_load_point(args.case, record["measures"])
            for mode, record in statuses.items()
        },
        "fab_release": False,
    }
    output = poc.OUT / f"poc_{args.case}_comparison_model_only.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"wrote {output}; not a hardware release")
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
