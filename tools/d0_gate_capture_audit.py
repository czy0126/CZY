"""Fail-closed D0 ten-gate oscilloscope CSV auditor.

This measures *recorded* outputs, not a Boolean model or an ERC result.
No result here approves a power-stage PCB, SOA, or a hardware prototype.

CSV data must be one synchronous 11-channel capture (time + external trip +
two primary gate-to-source voltages + eight SR gate-to-source voltages).
Limits must be chosen by a reviewer based on actual hardware/SOA; this
program intentionally has no universal default trip-time or Vgs thresholds.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

PRIMARY = ("P_HO", "P_LO")
SR = tuple(f"SR{i}{side}" for i in range(1, 5) for side in ("A", "B"))
GATES = PRIMARY + SR
VERSION = 1
LIMIT_FIELDS = (
    "gate_off_max_v", "gate_on_min_v", "gate_overlap_forbidden_above_v", "trip_low_max_v",
    "trip_high_min_v", "max_disable_latency_s", "max_sample_spacing_s",
    "min_pretrip_s", "min_post_trip_hold_s",
)


class InvalidCapture(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_finite(value, field: str) -> float:
    if isinstance(value, bool):
        raise InvalidCapture(f"{field}: Boolean is not a numeric limit")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as e:
        raise InvalidCapture(f"{field}: expected finite number") from e
    if not math.isfinite(number):
        raise InvalidCapture(f"{field}: nonfinite value")
    return number


def config_limits(cfg: dict) -> dict[str, float]:
    if cfg.get("schema_version") != VERSION:
        raise InvalidCapture("unsupported schema_version")
    if not isinstance(cfg.get("case_id"), str) or not cfg["case_id"].strip():
        raise InvalidCapture("case_id is required")
    if cfg.get("time_column") != "time_s" or cfg.get("trip_column") != "TRIP_STIMULUS":
        raise InvalidCapture("time/trip column contract changed")
    if cfg.get("gate_columns") != list(GATES):
        raise InvalidCapture("all ten ordered, independent GATE columns required")
    limits = {k: require_finite(cfg.get(k), k) for k in LIMIT_FIELDS}
    if (limits["gate_off_max_v"] < 0 or
        limits["gate_on_min_v"] <= limits["gate_off_max_v"] or
        not (0 < limits["gate_overlap_forbidden_above_v"] <= limits["gate_on_min_v"]) or
        limits["trip_low_max_v"] >= limits["trip_high_min_v"]):
        raise InvalidCapture("invalid input/gate voltage hysteresis limits")
    if any(limits[k] <= 0 for k in (
        "max_disable_latency_s", "max_sample_spacing_s", "min_pretrip_s",
        "min_post_trip_hold_s"
    )):
        raise InvalidCapture("timing limits must all be positive")
    if limits["max_sample_spacing_s"] > limits["max_disable_latency_s"] / 5:
        raise InvalidCapture("capture must resolve trip latency with >=5 sampling intervals")
    return limits


def read_csv(path: Path) -> tuple[list[float], dict[str, list[float]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as e:
            raise InvalidCapture("empty CSV") from e
        if len(header) != len(set(header)):
            raise InvalidCapture("duplicate CSV header names")
        expected = {"time_s", "TRIP_STIMULUS", *GATES}
        if not expected.issubset(header):
            raise InvalidCapture("missing synchronous channels: " +
                                 ",".join(sorted(expected - set(header))))
        # These are voltage waveforms (VGS per local source). Disallow
        # extra columns to avoid accidentally substituting inferred EN values.
        if set(header) != expected:
            raise InvalidCapture("unexpected columns: " +
                                 ",".join(sorted(set(header) - expected)))
        values = {key: [] for key in header}
        for row_number, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise InvalidCapture(f"CSV row {row_number}: ragged row")
            for key, raw in zip(header, row):
                values[key].append(require_finite(raw, f"{key} row {row_number}"))
    t = values.pop("time_s")
    if len(t) < 15:
        raise InvalidCapture("capture has fewer than 15 samples")
    if any(right <= left for left, right in zip(t, t[1:])):
        raise InvalidCapture("timestamps must be strictly increasing")
    return t, values


def evaluate(cfg: dict, t: list[float], samples: dict[str, list[float]]) -> dict:
    l = config_limits(cfg)
    if set(samples) != {"TRIP_STIMULUS", *GATES}:
        raise InvalidCapture("CSV channel set not exactly ten Vgs + external stimulus")
    if any(len(v) != len(t) for v in samples.values()):
        raise InvalidCapture("mismatched channel sample lengths")
    if not t or any(not math.isfinite(x) for x in t) or any(
        b <= a for a, b in zip(t, t[1:])
    ):
        raise InvalidCapture("invalid timestamp array")
    spacing = max(b - a for a, b in zip(t, t[1:]))
    if spacing > l["max_sample_spacing_s"] * (1 + 1e-9):
        raise InvalidCapture("sample gap exceeds reviewed maximum")
    stimulus = samples["TRIP_STIMULUS"]
    if any(l["trip_low_max_v"] < v < l["trip_high_min_v"] for v in stimulus):
        raise InvalidCapture("ambiguous TRIP_STIMULUS logic level")
    rising = [i for i in range(1, len(t))
              if stimulus[i-1] <= l["trip_low_max_v"] and
              stimulus[i] >= l["trip_high_min_v"]]
    violations: list[str] = []
    # A set of gates that *eventually* shuts down is still unsafe if
    # complementary devices were ever simultaneously driven above the
    # reviewed overlap threshold. This checks primary HO/LO and each
    # center-tapped SR pair in the SAME synchronized acquisition.
    pair_overlap_events = {}
    pairs = [("P_HO", "P_LO", "PRIMARY")] + [
        (f"SR{i}A", f"SR{i}B", f"SR{i}") for i in range(1, 5)
    ]
    for a, b, label in pairs:
        bad = [i for i in range(len(t))
               if samples[a][i] >= l["gate_overlap_forbidden_above_v"]
               and samples[b][i] >= l["gate_overlap_forbidden_above_v"]]
        if bad:
            violations.append(f"{label}:GATE_OVERLAP")
            pair_overlap_events[label] = {
                "first_s": t[bad[0]], "last_s": t[bad[-1]],
                "sample_count": len(bad),
            }
    if stimulus[0] > l["trip_low_max_v"]:
        violations.append("TRIP_INITIAL_NOT_LOW")
    if len(rising) != 1:
        violations.append("TRIP_MUST_HAVE_EXACTLY_ONE_RISING_EDGE")
    if not rising:
        return _report(cfg, t, l, spacing, violations, {}, None, pair_overlap_events)
    k = rising[0]
    trip_time = t[k]
    # A latched trip must remain asserted throughout observation, not bounce.
    if any(v <= l["trip_low_max_v"] for v in stimulus[k:]):
        violations.append("TRIP_NOT_HELD_AFTER_ASSERTION")
    if trip_time - t[0] < l["min_pretrip_s"]:
        raise InvalidCapture("pretrip observation window too short")
    deadline = trip_time + l["max_disable_latency_s"]
    required_end = deadline + l["min_post_trip_hold_s"]
    if t[-1] < required_end:
        raise InvalidCapture("capture ends before full post-trip holding window")
    pre = [i for i in range(k) if t[i] >= trip_time - l["min_pretrip_s"]]
    if len(pre) < 2:
        raise InvalidCapture("insufficient samples in pretrip exercise window")
    channels = {}
    for gate in GATES:
        wave = samples[gate]
        was_excited = any(wave[i] >= l["gate_on_min_v"] for i in pre)
        if not was_excited:
            violations.append(f"{gate}:NOT_EXERCISED_BEFORE_TRIP")
        # Use the first sampled instant *after the last unsafe sample*,
        # conservatively counting sample quantization in disable latency.
        unsafe = [i for i in range(k, len(t)) if wave[i] > l["gate_off_max_v"]]
        last_unsafe = unsafe[-1] if unsafe else None
        safe_index = k if last_unsafe is None else last_unsafe + 1
        safe_time = t[safe_index] if safe_index < len(t) else None
        settled = safe_time is not None and safe_time <= deadline + 1e-12
        if not settled:
            violations.append(f"{gate}:NOT_OFF_BY_DEADLINE")
        if any(wave[i] > l["gate_off_max_v"] for i in range(k, len(t))
               if t[i] >= deadline):
            violations.append(f"{gate}:POST_DEADLINE_REENABLE_OR_SPIKE")
        channels[gate] = {
            "pretrip_excited": was_excited,
            "last_unsafe_sample_s": t[last_unsafe] if last_unsafe is not None else None,
            "permanently_safe_from_s": safe_time,
            "measured_disable_upper_bound_s": (
                safe_time - trip_time if safe_time is not None else None),
            "deadline_s": deadline,
            "pass_waveform": was_excited and settled and not any(
                wave[i] > l["gate_off_max_v"] for i in range(k, len(t))
                if t[i] >= deadline),
        }
    return _report(cfg, t, l, spacing, violations, channels, trip_time,
                   pair_overlap_events)


def _report(cfg, t, limits, spacing, violations, channels, trip_time,
            pair_overlap_events):
    # Even a capture-only PASS can NEVER clear hardware design or release.
    reviewed = cfg.get("limits_review_status") == "ENGINEER_REVIEWED"
    provenance = all(
        isinstance(cfg.get(k), str) and cfg[k].strip() and cfg[k] != "PENDING"
        for k in ("hardware_revision", "instrument_id", "limit_basis")
    )
    if not reviewed:
        violations.append("LIMITS_NOT_ENGINEER_REVIEWED")
    if not provenance:
        violations.append("MEASUREMENT_PROVENANCE_INCOMPLETE")
    return {
        "kind": "D0_TEN_GATE_SCOPE_CAPTURE_AUDIT",
        "schema_version": VERSION,
        "status": "PASS_CAPTURE_ONLY" if not violations else "REJECTED",
        "case_id": cfg.get("case_id"),
        "capture_provenance": {
            key: cfg.get(key) for key in
            ("hardware_revision", "instrument_id", "limit_basis", "limits_review_status")
        },
        "trip_time_s": trip_time,
        "duration_s": t[-1] - t[0],
        "max_sample_spacing_observed_s": spacing,
        "limits": limits,
        "channels": channels,
        "pair_overlap_events": pair_overlap_events,
        "violations": violations,
        "origin_classification": "UNVERIFIED_CSV_MAY_BE_SYNTHETIC",
        "waveform_origin_authenticated": False,
        "all_ten_real_hardware_gates_verified": False,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "requires_independent_hardware_review": True,
    }


def run(csv_file: Path, config_file: Path) -> dict:
    cfg = json.loads(config_file.read_text(encoding="utf-8"))
    t, traces = read_csv(csv_file)
    result = evaluate(cfg, t, traces)
    result["source"] = {
        "csv_path": str(csv_file),
        "csv_sha256": sha256(csv_file),
        "config_path": str(config_file),
        "config_sha256": sha256(config_file),
    }
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, required=True, help="single synchronized scope CSV")
    p.add_argument("--config", type=Path, required=True, help="reviewed threshold JSON")
    p.add_argument("--output", type=Path, help="write machine-readable audit JSON")
    args = p.parse_args()
    try:
        result = run(args.csv, args.config)
        code = 0 if result["status"] == "PASS_CAPTURE_ONLY" else 1
    except (InvalidCapture, OSError, ValueError, TypeError, KeyError) as error:
        code = 2
        result = {
            "kind": "D0_TEN_GATE_SCOPE_CAPTURE_AUDIT",
            "status": "INVALID_EVIDENCE",
            "errors": [str(error)],
            "hardware_protection_approved": False,
            "power_stage_fabrication_approved": False,
        }
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8", newline="\n")
    print(body)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
