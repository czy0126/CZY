"""Align multiple oscilloscope records onto one shared D0 capture timebase.

This is the reviewed re-sampling step that chapter 29 deliberately left out:
the capture auditor consumes one CSV, but a bench setup may need two or more
instruments to record all ten gate-to-source voltages plus the trip stimulus.

What this program does:
  * locates one declared trigger edge in every instrument record,
  * shifts each record by that edge onto a common grid,
  * linearly resamples to a grid no finer than the coarsest original record,
  * writes the exact 12-column CSV that ``d0_gate_capture_audit.py`` reads,
  * reports the declared skew budget and the resolution that supports it.

What it CANNOT do:
  * prove physical simultaneity, probe skew, trigger jitter, or bandwidth match,
  * authenticate that any CSV came from a real instrument,
  * invent resolution between original samples,
  * approve hardware protection, SOA, or fabrication.

Exit codes: 0 aligned with reviewed provenance; 1 aligned but provenance
incomplete (CSV still written); 2 invalid alignment (no output CSV).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path

VERSION = 1
SR = tuple(f"SR{i}{side}" for i in range(1, 5) for side in ("A", "B"))
TARGET_CHANNELS = ("TRIP_STIMULUS", "P_HO", "P_LO") + SR
OUTPUT_COLUMNS = ("time_s",) + TARGET_CHANNELS
PENDING = {"", "PENDING", "UNKNOWN", "TBD", "N/A", "TO_SELECT", "UNVERIFIED"}
MIN_SAMPLES = 5
SAMPLE_RATE_TOLERANCE = 0.02
WHOLE_STEP_TOLERANCE = 1e-6
TIME_EPS = 1e-15


class InvalidAlignment(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def finite(value, field: str) -> float:
    if isinstance(value, bool):
        raise InvalidAlignment(f"{field}: Boolean is not a numeric value")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise InvalidAlignment(f"{field}: expected a finite number") from error
    if not math.isfinite(number):
        raise InvalidAlignment(f"{field}: nonfinite value")
    return number


def nonempty(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAlignment(f"{field}: non-empty string required")
    return value


def _whole_steps(span: float, dt: float, field: str) -> int:
    steps = span / dt
    nearest = round(steps)
    if nearest < 1 or abs(steps - nearest) > WHOLE_STEP_TOLERANCE:
        raise InvalidAlignment(
            f"{field} must be a whole multiple of grid.dt_s (got {steps:.9g} steps)")
    return int(nearest)


def _sync_and_grid(cfg: dict) -> tuple[dict, dict]:
    sync = cfg.get("sync")
    if not isinstance(sync, dict):
        raise InvalidAlignment("sync block required")
    basis = nonempty(sync.get("alignment_basis"), "sync.alignment_basis")
    review = nonempty(sync.get("basis_review_status"), "sync.basis_review_status")
    budget = finite(sync.get("max_remaining_skew_s"), "sync.max_remaining_skew_s")
    if budget <= 0:
        raise InvalidAlignment("sync.max_remaining_skew_s must be positive")
    grid = cfg.get("grid")
    if not isinstance(grid, dict):
        raise InvalidAlignment("grid block required")
    pre = finite(grid.get("pre_s"), "grid.pre_s")
    post = finite(grid.get("post_s"), "grid.post_s")
    dt = finite(grid.get("dt_s"), "grid.dt_s")
    if pre <= 0 or post <= 0 or dt <= 0:
        raise InvalidAlignment("grid pre_s, post_s and dt_s must all be positive")
    return (
        {"alignment_basis": basis, "basis_review_status": review,
         "max_remaining_skew_s": budget},
        {"pre_s": pre, "post_s": post, "dt_s": dt,
         "pre_steps": _whole_steps(pre, dt, "grid.pre_s"),
         "post_steps": _whole_steps(post, dt, "grid.post_s")},
    )


def _instrument(item: dict, index: int) -> dict:
    where = f"instruments[{index}]"
    if not isinstance(item, dict):
        raise InvalidAlignment(f"{where}: object required")
    ident = nonempty(item.get("id"), f"{where}.id")
    time_column = nonempty(item.get("time_column"), f"{where}.time_column")
    trigger = item.get("trigger")
    if not isinstance(trigger, dict):
        raise InvalidAlignment(f"{where}.trigger: object required")
    trigger_column = nonempty(trigger.get("column"), f"{where}.trigger.column")
    edge = trigger.get("edge")
    if edge not in ("rising", "falling"):
        raise InvalidAlignment(f"{where}.trigger.edge: rising or falling required")
    threshold = finite(trigger.get("threshold_v"), f"{where}.trigger.threshold_v")
    search_start = finite(trigger.get("search_start_s"), f"{where}.trigger.search_start_s")
    search_end = finite(trigger.get("search_end_s"), f"{where}.trigger.search_end_s")
    if not search_start < search_end:
        raise InvalidAlignment(f"{where}.trigger: search_start_s must be < search_end_s")
    channels = item.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise InvalidAlignment(f"{where}.channels: non-empty mapping required")
    for source, target in channels.items():
        nonempty(source, f"{where}.channels source")
        if target not in TARGET_CHANNELS:
            raise InvalidAlignment(f"{where}.channels: unknown target {target!r}")
        if source == time_column:
            raise InvalidAlignment(f"{where}.channels: time column cannot be a signal")
    if len(set(channels.values())) != len(channels):
        raise InvalidAlignment(
            f"{where}.channels: two source columns map to the same target channel")
    if trigger_column == time_column:
        raise InvalidAlignment(f"{where}.trigger.column cannot be the time column")
    rate = finite(item.get("sample_rate_hz"), f"{where}.sample_rate_hz")
    if rate <= 0:
        raise InvalidAlignment(f"{where}.sample_rate_hz must be positive")
    return {
        "id": ident,
        "csv": nonempty(item.get("csv"), f"{where}.csv"),
        "time_column": time_column,
        "trigger": {
            "column": trigger_column, "edge": edge, "threshold_v": threshold,
            "search_start_s": search_start, "search_end_s": search_end,
        },
        "channels": dict(channels),
        "instrument_id": item.get("instrument_id"),
        "probe_model": item.get("probe_model"),
        "probe_bandwidth_hz": item.get("probe_bandwidth_hz"),
        "sample_rate_hz": rate,
    }


def validate_manifest(cfg: dict) -> dict:
    """Check the manifest's shape; return normalized values."""
    if not isinstance(cfg, dict):
        raise InvalidAlignment("manifest must be a JSON object")
    if cfg.get("schema_version") != VERSION:
        raise InvalidAlignment("unsupported schema_version")
    case_id = nonempty(cfg.get("case_id"), "case_id")
    sync, grid = _sync_and_grid(cfg)
    items = cfg.get("instruments")
    if not isinstance(items, list) or not items:
        raise InvalidAlignment("at least one instrument is required")
    instruments = [_instrument(item, index) for index, item in enumerate(items)]
    ids = [inst["id"] for inst in instruments]
    if len(ids) != len(set(ids)):
        raise InvalidAlignment("instrument ids must be unique")
    producers: dict[str, str] = {}
    for inst in instruments:
        for target in inst["channels"].values():
            if target in producers:
                raise InvalidAlignment(
                    f"target channel {target!r} has more than one producer "
                    f"({producers[target]!r} and {inst['id']!r})")
            producers[target] = inst["id"]
    missing = [name for name in TARGET_CHANNELS if name not in producers]
    if missing:
        raise InvalidAlignment("no producer for target channel(s): " + ", ".join(missing))
    by_id = {inst["id"]: inst for inst in instruments}
    trip = by_id[producers["TRIP_STIMULUS"]]
    trip_sources = [src for src, dst in trip["channels"].items() if dst == "TRIP_STIMULUS"]
    if trip["trigger"]["column"] != trip_sources[0]:
        raise InvalidAlignment(
            "trigger column of the TRIP_STIMULUS producer must be the source "
            f"column mapped to TRIP_STIMULUS ({trip_sources[0]!r})")
    if trip["trigger"]["edge"] != "rising":
        raise InvalidAlignment("TRIP_STIMULUS trigger edge must be rising")
    return {"case_id": case_id, "sync": sync, "grid": grid,
            "instruments": instruments, "producers": producers}


def read_instrument(path: Path, time_column: str,
                    columns: set[str]) -> tuple[list[float], dict[str, list[float]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as error:
            raise InvalidAlignment(f"{path}: empty CSV") from error
        if len(header) != len(set(header)):
            raise InvalidAlignment(f"{path}: duplicate CSV header names")
        required = {time_column, *columns}
        absent = required - set(header)
        if absent:
            raise InvalidAlignment(f"{path}: missing columns: " + ", ".join(sorted(absent)))
        position = {name: header.index(name) for name in required}
        values = {name: [] for name in required}
        for row_number, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise InvalidAlignment(f"{path}: row {row_number} is ragged")
            for name, index in position.items():
                try:
                    number = float(row[index])
                except (TypeError, ValueError) as error:
                    raise InvalidAlignment(
                        f"{path}: {name} row {row_number}: expected finite number") from error
                if not math.isfinite(number):
                    raise InvalidAlignment(f"{path}: {name} row {row_number}: nonfinite value")
                values[name].append(number)
    t = values.pop(time_column)
    if len(t) < MIN_SAMPLES:
        raise InvalidAlignment(f"{path}: fewer than {MIN_SAMPLES} samples")
    if any(right <= left for left, right in zip(t, t[1:])):
        raise InvalidAlignment(f"{path}: timestamps must be strictly increasing")
    return t, values


def find_edge(t: list[float], values: list[float], threshold: float,
              edge: str, start: float, end: float) -> dict:
    """Locate exactly one threshold crossing inside [start, end]."""
    if start < t[0] - TIME_EPS or end > t[-1] + TIME_EPS:
        raise InvalidAlignment(
            f"trigger search window [{start:.9g}, {end:.9g}] exceeds the record "
            f"[{t[0]:.9g}, {t[-1]:.9g}]")
    crossings: list[tuple[int, float]] = []
    for i in range(1, len(t)):
        left, right = values[i - 1], values[i]
        crossed = ((left < threshold <= right) if edge == "rising"
                   else (left > threshold >= right))
        if not crossed or right == left:
            continue
        width = t[i] - t[i - 1]
        when = t[i - 1] + (threshold - left) / (right - left) * width
        if start <= when <= end:
            crossings.append((i, when))
    if not crossings:
        raise InvalidAlignment(
            f"no trigger edge found in [{start:.9g}, {end:.9g}] for threshold {threshold}")
    if len(crossings) > 1:
        raise InvalidAlignment(
            "ambiguous trigger: exactly one edge is required in the search window; "
            f"found {len(crossings)}")
    i, when = crossings[0]
    width = t[i] - t[i - 1]
    return {"time_s": when, "bracketing_interval_s": width,
            "uncertainty_s": width / 2.0}


def sample_at(t: list[float], values: list[float], when: float) -> float:
    """Linear interpolation; the caller has already proven coverage."""
    if when <= t[0]:
        return values[0]
    if when >= t[-1]:
        return values[-1]
    i = bisect.bisect_left(t, when)
    if t[i] == when:
        return values[i]
    span = t[i] - t[i - 1]
    fraction = (when - t[i - 1]) / span
    return values[i - 1] + fraction * (values[i] - values[i - 1])


def metadata_complete(inst: dict) -> bool:
    for field in ("instrument_id", "probe_model"):
        value = inst.get(field)
        if not isinstance(value, str) or value.strip().upper() in PENDING:
            return False
    bandwidth = inst.get("probe_bandwidth_hz")
    if isinstance(bandwidth, bool):
        return False
    try:
        return math.isfinite(float(bandwidth)) and float(bandwidth) > 0
    except (TypeError, ValueError):
        return False


def _load_state(spec: dict, base: Path) -> list[dict]:
    state = []
    for inst in spec["instruments"]:
        path = Path(inst["csv"])
        if not path.is_absolute():
            path = base / path
        if not path.is_file():
            raise InvalidAlignment(f"instrument {inst['id']!r}: CSV not found: {path}")
        raw = path.read_bytes()
        columns = set(inst["channels"]) | {inst["trigger"]["column"]}
        t, data = read_instrument(path, inst["time_column"], columns)
        trigger = inst["trigger"]
        fired = find_edge(t, data[trigger["column"]], trigger["threshold_v"],
                          trigger["edge"], trigger["search_start_s"],
                          trigger["search_end_s"])
        duration = t[-1] - t[0]
        measured_rate = (len(t) - 1) / duration if duration > 0 else math.inf
        if abs(measured_rate - inst["sample_rate_hz"]) > SAMPLE_RATE_TOLERANCE * inst["sample_rate_hz"]:
            raise InvalidAlignment(
                f"instrument {inst['id']!r}: declared sample rate "
                f"{inst['sample_rate_hz']:.9g} Hz does not match record "
                f"{measured_rate:.9g} Hz")
        state.append({
            **inst, "path": path, "bytes": raw, "t": t, "data": data,
            "edge": fired, "measured_rate": measured_rate,
            "max_spacing": max(right - left for left, right in zip(t, t[1:])),
        })
    return state


def _check_grid(spec: dict, state: list[dict]) -> dict:
    budget = spec["sync"]["max_remaining_skew_s"]
    max_edge = max(item["edge"]["uncertainty_s"] for item in state)
    coarsest = max(item["max_spacing"] for item in state)
    resampling = coarsest / 2.0
    if max(max_edge, resampling) > budget * (1 + 1e-9):
        raise InvalidAlignment(
            f"declared skew budget {budget:.9g} s is not supported by sample "
            f"resolution: edge uncertainty {max_edge:.9g} s, "
            f"resampling uncertainty {resampling:.9g} s")
    grid = spec["grid"]
    dt = grid["dt_s"]
    if dt < coarsest * (1 - 1e-9):
        raise InvalidAlignment(
            f"output dt_s={dt:.9g} s is finer than the coarsest record spacing "
            f"{coarsest:.9g} s; resampling would fabricate resolution")
    pre_used = grid["pre_steps"] * dt
    post_used = grid["post_steps"] * dt
    for item in state:
        item["required_start_s"] = item["edge"]["time_s"] - pre_used
        item["required_end_s"] = item["edge"]["time_s"] + post_used
        if (item["required_start_s"] < item["t"][0] - TIME_EPS
                or item["required_end_s"] > item["t"][-1] + TIME_EPS):
            raise InvalidAlignment(
                f"instrument {item['id']!r} does not cover the aligned grid: "
                f"needs [{item['required_start_s']:.9g}, {item['required_end_s']:.9g}] s, "
                f"record covers [{item['t'][0]:.9g}, {item['t'][-1]:.9g}] s")
    return {"max_edge_uncertainty_s": max_edge, "resampling_uncertainty_s": resampling,
            "pre_s": pre_used, "post_s": post_used, "dt_s": dt}


def _resample(spec: dict, state: list[dict], grid: dict) -> tuple[list[float], list[list[float]]]:
    by_id = {item["id"]: item for item in state}
    sources = {
        item["id"]: {target: source for source, target in item["channels"].items()}
        for item in state
    }
    times: list[float] = []
    rows: list[list[float]] = []
    for step in range(-spec["grid"]["pre_steps"], spec["grid"]["post_steps"] + 1):
        u = step * grid["dt_s"]
        row = [u]
        for target in TARGET_CHANNELS:
            item = by_id[spec["producers"][target]]
            when = item["edge"]["time_s"] + u
            row.append(sample_at(item["t"], item["data"][sources[item["id"]][target]], when))
        times.append(u)
        rows.append(row)
    return times, rows


def _aligned_trip(times: list[float], rows: list[list[float]], spec: dict,
                  state: list[dict]) -> dict:
    threshold = next(item["trigger"]["threshold_v"] for item in state
                     if item["id"] == spec["producers"]["TRIP_STIMULUS"])
    index = OUTPUT_COLUMNS.index("TRIP_STIMULUS")
    try:
        return find_edge(times, [row[index] for row in rows], threshold,
                         "rising", times[0], times[-1])
    except InvalidAlignment as error:
        raise InvalidAlignment(f"aligned output trip edge check failed: {error}") from error


def _instrument_report(item: dict) -> dict:
    return {
        "id": item["id"],
        "instrument_id": item["instrument_id"],
        "probe_model": item["probe_model"],
        "probe_bandwidth_hz": item["probe_bandwidth_hz"],
        "csv_path": str(item["path"]),
        "csv_sha256": sha256_bytes(item["bytes"]),
        "time_column": item["time_column"],
        "sample_count": len(item["t"]),
        "sample_rate_hz_declared": item["sample_rate_hz"],
        "sample_rate_hz_measured": item["measured_rate"],
        "max_sample_spacing_s": item["max_spacing"],
        "record_start_s": item["t"][0],
        "record_end_s": item["t"][-1],
        "trigger": item["trigger"],
        "trigger_time_s": item["edge"]["time_s"],
        "trigger_interpolation_uncertainty_s": item["edge"]["uncertainty_s"],
        "required_start_s": item["required_start_s"],
        "required_end_s": item["required_end_s"],
        "channels": item["channels"],
    }


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise InvalidAlignment(f"duplicate JSON key {key!r}; silent collapse is not allowed")
        result[key] = value
    return result


def _read_manifest(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    try:
        cfg = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidAlignment(f"manifest is not valid JSON: {error}") from error
    return cfg, data


def build(manifest_path: Path) -> tuple[dict, list[list[float]]]:
    cfg, manifest_bytes = _read_manifest(manifest_path)
    spec = validate_manifest(cfg)
    state = _load_state(spec, manifest_path.parent)
    grid = _check_grid(spec, state)
    times, rows = _resample(spec, state, grid)
    aligned_trip = _aligned_trip(times, rows, spec, state)
    if abs(aligned_trip["time_s"]) > grid["dt_s"] + grid["max_edge_uncertainty_s"] + TIME_EPS:
        raise InvalidAlignment(
            "aligned output trip edge is not at the shared grid origin: "
            f"{aligned_trip['time_s']:.9g} s")
    provenance = (spec["sync"]["basis_review_status"] == "ENGINEER_REVIEWED"
                  and all(metadata_complete(item) for item in state))
    report = {
        "kind": "D0_MULTI_INSTRUMENT_SYNC_ALIGNMENT",
        "schema_version": VERSION,
        "status": "ALIGNED_FOR_CAPTURE_AUDIT" if provenance else "ALIGNED_PROVENANCE_INCOMPLETE",
        "case_id": spec["case_id"],
        "source": {"manifest_path": str(manifest_path),
                   "manifest_sha256": sha256_bytes(manifest_bytes)},
        "output": {
            "columns": list(OUTPUT_COLUMNS),
            "row_count": len(rows),
            "grid": {"pre_s": grid["pre_s"], "post_s": grid["post_s"], "dt_s": grid["dt_s"],
                     "aligned_trip_edge_s": aligned_trip["time_s"]},
        },
        "sync": {
            "declared_max_remaining_skew_s": spec["sync"]["max_remaining_skew_s"],
            "edge_interpolation_uncertainty_s": grid["max_edge_uncertainty_s"],
            "resampling_interpolation_uncertainty_s": grid["resampling_uncertainty_s"],
            "budget_is_supported_by_sample_resolution": True,
            "physical_simultaneity_proven": False,
            "alignment_basis": spec["sync"]["alignment_basis"],
            "basis_review_status": spec["sync"]["basis_review_status"],
        },
        "instruments": [_instrument_report(item) for item in state],
        "channel_producers": {name: spec["producers"][name] for name in TARGET_CHANNELS},
        "checks": {
            "all_target_channels_have_exactly_one_producer": True,
            "reference_trigger_is_the_trip_stimulus_record": True,
            "declared_sample_rates_match_records": True,
            "edge_uncertainty_within_declared_budget": True,
            "output_grid_does_not_fabricate_resolution": True,
            "all_instruments_cover_the_full_grid": True,
            "aligned_output_has_exactly_one_rising_trip_edge": True,
            "provenance_complete": provenance,
        },
        "errors": [],
        "warnings": [
            "alignment is linear resampling only; probe skew, trigger jitter and "
            "bandwidth differences are not measured",
            f"aligned trip edge interpolates to {aligned_trip['time_s']:.9g} s on the "
            "shared grid; the D0 auditor uses the first sample above threshold",
        ],
        "limitations": [
            "physical simultaneity of the instruments is not proven",
            "waveform origin is not authenticated; a CSV may be synthetic",
            "linear interpolation does not recover content between samples",
            "the declared skew budget is checked against sample resolution only",
            "the trigger threshold must match the capture auditor's trip_high_min_v, "
            "otherwise the origin sample may be an ambiguous logic level",
            "no hardware protection, SOA, or fabrication approval is implied",
        ],
        "origin_classification": "UNVERIFIED_RESAMPLED_CSV_MAY_BE_SYNTHETIC",
        "physical_simultaneity_proven": False,
        "waveform_origin_authenticated": False,
        "all_ten_real_hardware_gates_verified": False,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "requires_independent_hardware_review": True,
    }
    return report, rows


def write_aligned_csv(dest: Path, rows: list[list[float]]) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(OUTPUT_COLUMNS)
        for row in rows:
            writer.writerow([repr(float(value)) for value in row])
    return sha256_file(dest)


def _invalid_report(error: Exception) -> dict:
    return {
        "kind": "D0_MULTI_INSTRUMENT_SYNC_ALIGNMENT",
        "schema_version": VERSION,
        "status": "INVALID_ALIGNMENT",
        "errors": [str(error)],
        "checks": {name: False for name in (
            "all_target_channels_have_exactly_one_producer",
            "reference_trigger_is_the_trip_stimulus_record",
            "declared_sample_rates_match_records",
            "edge_uncertainty_within_declared_budget",
            "output_grid_does_not_fabricate_resolution",
            "all_instruments_cover_the_full_grid",
            "aligned_output_has_exactly_one_rising_trip_edge",
            "provenance_complete",
        )},
        "physical_simultaneity_proven": False,
        "waveform_origin_authenticated": False,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
    }


def run(manifest_path: Path, csv_path: Path, report_path: Path) -> int:
    try:
        report, rows = build(manifest_path)
    except (InvalidAlignment, OSError, ValueError, TypeError, KeyError) as error:
        payload = _invalid_report(error)
        _write_json(report_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    digest = write_aligned_csv(csv_path, rows)
    report["output"].update({"csv_path": str(csv_path), "csv_sha256": digest})
    _write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ALIGNED_FOR_CAPTURE_AUDIT" else 1


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True, help="aligned 12-column output")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    return run(args.manifest, args.csv, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
