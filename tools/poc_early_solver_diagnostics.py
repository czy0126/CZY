"""Isolate early LTspice numerical failure WITHOUT changing the golden D1 model.

0.62ms comparison is intentionally earlier than REG enable (1.2ms).
Case snapshots are generated in sim/v3; no .raw or simulation result is made
up, and these model changes can NEVER be used to claim power-stage performance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
import poc_low_current_decks as poc
from poc_raw_evidence import inspect_raw, RawEvidenceError

ROOT = poc.ROOT
MODEL = ROOT / "models/sr_device_v3.lib"
MODELS = {"on_original": ("on", "original"),
          "on_tt0": ("on", "tt0"),
          "on_weak_shunt": ("on", "weak_shunt"),
          "off_original": ("off", "original")}


def build(scenario: str) -> tuple[Path, str, Path | None, str | None]:
    if scenario not in MODELS:
        raise ValueError("unknown diagnostic scenario " + scenario)
    mode, variation = MODELS[scenario]
    body = poc.deck("5a", mode)
    if body.count(".tran 0 8m 0 10n uic") != 1:
        raise ValueError("golden transient has drifted")
    body = body.replace(".tran 0 8m 0 10n uic", ".tran 0 620u 0 10n uic")
    body = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().lower().startswith(".meas ")) + "\n"
    if not body.endswith(".end\n"):
        raise ValueError("unexpected .end topology")
    body = body[:-5] + (
        ".meas tran DIAG_VOUT_AT_600U FIND V(out) AT=600u\n"
        ".meas tran DIAG_RESONANT_PK MAX abs(I(Lr)) FROM=400u TO=620u\n.end\n")
    source_path = None
    source_text = None
    if variation != "original":
        source_path = poc.OUT / f"_diag_{scenario}_sr_device.lib"
        source_text = MODEL.read_text(encoding="utf-8")
        source_marker = ".model DB D(IS=5e-11 N=1.05 TT=27n CJO=0 RS=1m)"
        if source_text.count(source_marker) != 2:
            raise ValueError("both manufacturer-calibrated diode source entries drifted")
        if variation == "tt0":
            source_text = source_text.replace(source_marker,
                                              source_marker.replace("TT=27n", "TT=0"))
        elif variation == "weak_shunt":
            source_text = source_text.replace("Dbd si di DB\n",
                                              "Dbd si di DB\nRdiagleak si di 100Meg\n")
        include = ".include ../../models/sr_device_v3.lib"
        if body.count(include) != 1:
            raise ValueError("baseline SR_DEVICE include drifted")
        body = body.replace(include, f".include {source_path.name}")
    name = f"_diag_5a_{scenario}.cir"
    return poc.OUT / name, body, source_path, source_text


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def diagnostic_measurements(log: Path) -> dict[str, float]:
    """A RAW end-time is insufficient: demand both actual finite .meas values."""
    from run_poc_low_current import read_ltspice_log

    raw_log = read_ltspice_log(log)
    targets = ("diag_vout_at_600u", "diag_resonant_pk")
    result = {}
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    for key in targets:
        values = re.findall(
            rf"(?im)^\s*{re.escape(key)}\s*:\s*[^=\r\n]*=\s*({number})",
            raw_log,
        )
        if len(values) != 1:
            raise ValueError(f"diagnostic LTspice log lacks a unique valid {key}")
        value = float(values[0])
        if not __import__("math").isfinite(value) or abs(value) >= 1e100:
            raise ValueError(f"nonfinite/sentinel diagnostic {key}")
        result[key] = value
    return result


def run(scenario: str, exe: Path, timeout_s: int = 840) -> int:
    if not exe.is_file():
        raise FileNotFoundError("genuine LTspice exe unavailable")
    if not 5 <= timeout_s <= 3600:
        raise ValueError("diagnostic timeout must be 5-3600 seconds")
    path, deck, model_path, model_text = build(scenario)
    if model_path:
        model_path.write_text(model_text, encoding="utf-8", newline="\n")
    path.write_text(deck, encoding="utf-8", newline="\n")
    log, raw = path.with_suffix(".log"), path.with_suffix(".raw")
    # Prior outputs may be stale; remove ONLY generated diagnostic outputs.
    for item in (log, raw):
        item.unlink(missing_ok=True)

    returncode = None
    stderr_tail = ""
    stdout_tail = ""
    failure = None
    try:
        result = subprocess.run(
            [str(exe), "-b", str(path.resolve())], cwd=path.parent,
            capture_output=True, timeout=timeout_s, text=True,
            errors="replace", check=False,
        )
        returncode = result.returncode
        stdout_tail = result.stdout[-800:]
        stderr_tail = result.stderr[-800:]
        if returncode != 0:
            failure = f"LTspice returned nonzero exit code {returncode}"
    except subprocess.TimeoutExpired as exc:
        # A 14-minute timeout is an execution failure, not a simulated
        # 0.62-ms numerical trajectory. Never lose the diagnostic JSON here.
        failure = f"LTspice exceeded {timeout_s}s wall clock without completing"
        stdout_tail = (exc.stdout or b"")[-800:]
        stderr_tail = (exc.stderr or b"")[-800:]
        if isinstance(stdout_tail, bytes):
            stdout_tail = stdout_tail.decode(errors="replace")
        if isinstance(stderr_tail, bytes):
            stderr_tail = stderr_tail.decode(errors="replace")
    except OSError as exc:
        failure = f"failed to launch LTspice: {exc}"

    if raw.exists():
        try:
            raw_validation = inspect_raw(raw, stop_time_s=.00062)
        except (RawEvidenceError, ValueError, OSError) as exc:
            raw_validation = {"status": "INVALID_RAW", "reason": str(exc)}
    else:
        raw_validation = {"status": "MISSING_RAW"}

    measurements = None
    if log.is_file() and log.stat().st_size > 0:
        try:
            measurements = diagnostic_measurements(log)
        except (ValueError, OSError, UnicodeError) as exc:
            if failure is None:
                failure = f"log .meas incomplete: {exc}"
    elif failure is None:
        failure = "genuine LTspice log missing"

    complete = (returncode == 0 and failure is None and
                raw_validation["status"] == "RAW_ALL_FINITE_AND_TIME_COMPLETE"
                and measurements is not None)
    metadata = {
        "status": "ISOLATED_EARLY_NUMERICAL_DIAGNOSTIC_NOT_FOR_HARDWARE",
        "diagnostic_run_validated": bool(complete),
        "failure_reason": failure if failure else (
            None if complete else raw_validation.get("reason", "RAW invalid")),
        "raw_validation": raw_validation,
        "scenario": scenario,
        "case": "nominal_5A_0p4ohm",
        "simulated_stop_s": .00062,
        "wall_clock_limit_s": timeout_s,
        "source_sha256": sha(poc.PARENT),
        "golden_mos_model_sha256": sha(MODEL),
        "input_sha256": sha(path),
        "diagnostic_model_sha256": sha(model_path) if model_path else None,
        "returncode": returncode,
        "log_sha256": sha(log) if log.exists() else None,
        "log_bytes": log.stat().st_size if log.exists() else 0,
        "raw_sha256": sha(raw) if raw.exists() else None,
        "raw_bytes": raw.stat().st_size if raw.exists() else 0,
        "diagnostic_measurements": measurements,
        "hardware_qualified": False,
        "fabrication_approved": False,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }
    output = poc.OUT / f"_diag_5a_{scenario}.json"
    output.write_text(json.dumps(metadata, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0 if complete else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=MODELS, required=True)
    parser.add_argument("--ltspice")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=840)
    args = parser.parse_args()
    if not args.run:
        name, deck, model, text = build(args.scenario)
        print(json.dumps({"deck": name.name, "sha256": hashlib.sha256(
            deck.encode()).hexdigest(), "diagnostic_model": model.name if model else None,
            "hardware_qualified": False}))
        return 0
    if not args.ltspice:
        parser.error("--ltspice is required for a genuine --run")
    return run(args.scenario, Path(args.ltspice), args.timeout_sec)


if __name__ == "__main__":
    raise SystemExit(main())
