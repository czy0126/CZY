"""Verify genuine LTspice batch execution BEFORE launching expensive D1 decks.

LTspice 26 installed on fresh Windows runners can start a GUI/first-run path
without creating .raw/.log. Four separate 0.62 ms D1 simulations timed out
after 840s with NO artifacts. A simple 1V/1k resistor must solve in seconds:
if it cannot, the blocker is the environment/batch process, not SR physics.

Fail-closed: never dismiss an unknown dialog or grant telemetry consent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from poc_raw_evidence import inspect_raw, RawEvidenceError

BASENAME = "_ltspice_batch_smoke"
DECK_TEXT = """* ADI LTspice one-volt diagnostic; NO hardware design evidence
V1 n 0 DC 1
R1 n 0 1k
.tran 0 2u 0 0.1u
.save V(n)
.meas tran vmx MAX V(n) FROM 1u TO 2u
.end
"""
EXPECTED_V = 1.0
TOLERANCE_V = 0.005


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if b"\x00" in raw[:128]:
        return raw.decode("utf-16-le")
    return raw.decode("utf-8")


def simple_result(log: str) -> float:
    m = re.search(
        r"(?im)^\s*vmx\s*:\s*max\s*\(\s*v\(n\)\s*\)\s*=\s*"
        r"([+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+\-]?\d+)?)",
        log,
    )
    if m is None:
        raise ValueError("the real 1V smoke log did not contain valid vmx .meas")
    voltage = float(m.group(1))
    if not math.isfinite(voltage) or abs(voltage) >= 1e100:
        raise ValueError("smoke .meas is nonfinite or LTspice sentinel")
    if abs(voltage - EXPECTED_V) > TOLERANCE_V:
        raise ValueError("smoke result is not the expected 1V supply")
    return voltage


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect(log_file: Path, raw_file: Path) -> dict:
    if not log_file.is_file() or not log_file.stat().st_size:
        raise ValueError("missing or empty real LTspice smoke log")
    if not raw_file.is_file() or not raw_file.stat().st_size:
        raise ValueError("missing or empty real LTspice smoke RAW")
    vmx = simple_result(read_text(log_file))
    raw_report = inspect_raw(raw_file, stop_time_s=2e-6)
    return {
        "model_only": True,
        "voltage_v_measured": vmx,
        "log_sha256": sha_file(log_file),
        "raw_sha256": sha_file(raw_file),
        "raw_evidence": raw_report,
    }


def run(ltspice: Path, out_dir: Path, timeout_s: int = 25) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    deck = out_dir / (BASENAME + ".cir")
    log = out_dir / (BASENAME + ".log")
    raw = out_dir / (BASENAME + ".raw")
    report_file = out_dir / (BASENAME + ".json")
    for file in (log, raw, report_file):
        file.unlink(missing_ok=True)
    deck.write_text(DECK_TEXT, encoding="ascii")
    report = {
        "status": "FAILED_OR_NOT_ATTEMPTED",
        "model": "1V_DC_1k_2us_NON_D1_SMOKE",
        "deck_sha256": sha_file(deck),
        "hardware_qualified": False,
        "D1_power_train_simulated": False,
        "simulator_exe": str(ltspice),
        "seconds_allowed": timeout_s,
    }
    try:
        if not ltspice.is_file():
            raise ValueError("missing official installed LTspice.exe")
        proc = subprocess.run(
            [str(ltspice), "-b", str(deck.resolve())],
            cwd=str(out_dir.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            check=False,
            timeout=timeout_s,
        )
        report["process_returncode"] = proc.returncode
        report["stdout_tail"] = proc.stdout[-1000:]
        report["stderr_tail"] = proc.stderr[-1000:]
        if proc.returncode != 0:
            raise ValueError(f"LTspice smoke returned exit={proc.returncode}")
        report["measurement"] = inspect(log, raw)
        report["status"] = "BATCH_SMOKE_PASSED_NOT_D1_EVIDENCE"
    except subprocess.TimeoutExpired as exc:
        report["status"] = "BATCH_SMOKE_STALLED_BEFORE_VALID_EVIDENCE"
        report["reason"] = (
            f"LTspice -b did not finish trivial 1V circuit in {timeout_s}s; "
            "potential first-run dialog or headless runner/UI issue. "
            "NOT proof of an SR circuit numerical failure."
        )
    except (OSError, ValueError, UnicodeError, RawEvidenceError) as exc:
        report["status"] = "BATCH_SMOKE_FAILED_NOT_D1_EVIDENCE"
        report["reason"] = str(exc)
    report_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "BATCH_SMOKE_PASSED_NOT_D1_EVIDENCE" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ltspice", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--timeout-sec", type=int, default=25)
    args = parser.parse_args(argv)
    if args.timeout_sec < 5 or args.timeout_sec > 120:
        parser.error("batch smoke deadline must be 5–120 seconds")
    return run(args.ltspice, args.out_dir, args.timeout_sec)


if __name__ == "__main__":
    raise SystemExit(main())
