"""Bind D0 alignment, capture-limits and audit reports into one evidence chain.

This proves only that the supplied artifacts describe the *same* capture: matching
SHA-256 hashes, one case id, a grid the reviewed limits can resolve, an
unambiguous trip origin, and alignment/audit reports reproducible from the
manifest, CSV and config. It cannot authenticate instrument origin, prove
physical simultaneity, or approve hardware, SOA, or fabrication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path

import d0_gate_capture_audit as audit
import d0_scope_sync_align as align

VERSION = 1
RELEASE_FLAGS = (
    "physical_simultaneity_proven",
    "waveform_origin_authenticated",
    "all_ten_real_hardware_gates_verified",
    "hardware_protection_approved",
    "power_stage_fabrication_approved",
)
KNOWN_ALIGNMENT = {"ALIGNED_FOR_CAPTURE_AUDIT", "ALIGNED_PROVENANCE_INCOMPLETE"}
KNOWN_AUDIT = {"PASS_CAPTURE_ONLY", "REJECTED"}
TIME_EPS = 1e-15


class ChainError(ValueError):
    pass


def expected_columns() -> tuple[str, ...]:
    return ("time_s", "TRIP_STIMULUS") + audit.GATES


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ChainError(f"duplicate JSON key {key!r}; silent collapse is not allowed")
        result[key] = value
    return result


def read_json(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ChainError(f"{path}: not valid JSON: {error}") from error
    if not isinstance(doc, dict):
        raise ChainError(f"{path}: top-level JSON value must be an object")
    return doc, data


def number(value, field: str) -> float:
    if isinstance(value, bool):
        raise ChainError(f"{field}: Boolean is not a numeric value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ChainError(f"{field}: expected a finite number") from error
    if not math.isfinite(result):
        raise ChainError(f"{field}: non-finite value")
    return result


def _check(state: dict, name: str, ok: bool, message: str) -> None:
    state["checks"][name] = bool(ok)
    if not ok:
        state["errors"].append(f"{name}: {message}")


def _text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def grid_problems(alignment: dict, config: dict) -> list[str]:
    """Grid-vs-limit violations; an empty list means the auditor can resolve it."""
    grid = ((alignment.get("output") or {}).get("grid") or {})
    dt = number(grid.get("dt_s"), "alignment.output.grid.dt_s")
    pre = number(grid.get("pre_s"), "alignment.output.grid.pre_s")
    post = number(grid.get("post_s"), "alignment.output.grid.post_s")
    spacing = number(config.get("max_sample_spacing_s"), "config.max_sample_spacing_s")
    pretrip = number(config.get("min_pretrip_s"), "config.min_pretrip_s")
    latency = number(config.get("max_disable_latency_s"), "config.max_disable_latency_s")
    hold = number(config.get("min_post_trip_hold_s"), "config.min_post_trip_hold_s")
    problems: list[str] = []
    if dt > spacing * (1 + 1e-9):
        problems.append(
            f"aligned dt_s={dt:.9g} s exceeds the reviewed max_sample_spacing_s="
            f"{spacing:.9g} s; the auditor will reject the grid")
    if pre + TIME_EPS < pretrip:
        problems.append(
            f"aligned pre_s={pre:.9g} s is shorter than min_pretrip_s={pretrip:.9g} s")
    if post + TIME_EPS < latency + hold:
        problems.append(
            f"aligned post_s={post:.9g} s is shorter than max_disable_latency_s + "
            f"min_post_trip_hold_s={latency + hold:.9g} s")
    return problems


def trigger_problems(threshold: float, config: dict, origin_value: float) -> list[str]:
    """Ambiguity checks for the sampled trip origin and the trigger threshold."""
    low = number(config.get("trip_low_max_v"), "config.trip_low_max_v")
    high = number(config.get("trip_high_min_v"), "config.trip_high_min_v")
    problems: list[str] = []
    if low < threshold < high:
        problems.append(
            f"trigger threshold {threshold:.9g} V lies inside the capture auditor's "
            f"hysteresis band ({low:.9g}, {high:.9g}) V; the origin sample is ambiguous")
    if low < origin_value < high:
        problems.append(
            f"aligned origin TRIP_STIMULUS sample {origin_value:.9g} V lies inside the "
            f"hysteresis band ({low:.9g}, {high:.9g}) V and is ambiguous")
    return problems


def trip_threshold(manifest: dict) -> float:
    found = [inst for inst in manifest.get("instruments") or []
             if "TRIP_STIMULUS" in ((inst.get("channels") or {}).values())]
    if len(found) != 1:
        raise ChainError("manifest must map TRIP_STIMULUS from exactly one instrument")
    trigger = found[0].get("trigger") or {}
    return number(trigger.get("threshold_v"), "manifest trigger.threshold_v")


def _load_state(manifest_path: Path, alignment_path: Path, csv_path: Path,
                config_path: Path, audit_path: Path) -> dict:
    manifest, manifest_bytes = read_json(manifest_path)
    alignment, alignment_bytes = read_json(alignment_path)
    config, config_bytes = read_json(config_path)
    submitted, audit_bytes = read_json(audit_path)
    state = {
        "manifest": manifest, "alignment": alignment, "config": config,
        "submitted": submitted, "checks": {}, "errors": [], "warnings": [],
        "inputs": {
            "manifest": {"path": str(manifest_path), "sha256": sha256_bytes(manifest_bytes)},
            "alignment": {"path": str(alignment_path), "sha256": sha256_bytes(alignment_bytes)},
            "csv": {"path": str(csv_path), "sha256": sha256_bytes(csv_path.read_bytes())},
            "config": {"path": str(config_path), "sha256": sha256_bytes(config_bytes)},
            "audit": {"path": str(audit_path), "sha256": sha256_bytes(audit_bytes)},
        },
    }
    return state


def _bind_identity(state: dict) -> None:
    alignment, submitted = state["alignment"], state["submitted"]
    expected = list(expected_columns())
    report_csv = (alignment.get("output") or {}).get("csv_sha256")
    _check(state, "csv_hash_matches_alignment_report",
           report_csv == state["inputs"]["csv"]["sha256"],
           "supplied CSV bytes differ from alignment output.csv_sha256")
    _check(state, "manifest_hash_matches_alignment_report",
           (alignment.get("source") or {}).get("manifest_sha256")
           == state["inputs"]["manifest"]["sha256"],
           "supplied manifest bytes differ from alignment source.manifest_sha256")
    source = submitted.get("source") or {}
    _check(state, "csv_hash_matches_capture_audit",
           source.get("csv_sha256") == state["inputs"]["csv"]["sha256"],
           "supplied CSV bytes differ from the capture audit source.csv_sha256")
    _check(state, "config_hash_matches_capture_audit",
           source.get("config_sha256") == state["inputs"]["config"]["sha256"],
           "supplied config bytes differ from the capture audit source.config_sha256")
    _check(state, "aligned_columns_are_the_twelve_column_contract",
           (alignment.get("output") or {}).get("columns") == expected,
           "alignment report does not declare the ordered twelve-column contract")
    ids = [_text(state["manifest"].get("case_id")), _text(alignment.get("case_id")),
           _text(state["config"].get("case_id")), _text(submitted.get("case_id"))]
    _check(state, "case_ids_agree", None not in ids and len(set(ids)) == 1,
           f"case ids disagree or are missing: {ids}")


def _bind_csv(state: dict, csv_path: Path) -> None:
    state["t"], state["traces"] = [], {}
    try:
        t, traces = audit.read_csv(csv_path)
    except audit.InvalidCapture as error:
        _check(state, "aligned_csv_satisfies_the_twelve_column_contract", False, str(error))
    else:
        state["t"], state["traces"] = t, traces
        _check(state, "aligned_csv_satisfies_the_twelve_column_contract", True, "")
    alignment = state["alignment"]
    _check(state, "aligned_row_count_matches_report",
           (alignment.get("output") or {}).get("row_count") == len(state["t"]),
           "alignment report row_count differs from the CSV's data rows")
    if not state["t"]:
        return
    try:
        grid = (alignment.get("output") or {}).get("grid") or {}
        dt = number(grid.get("dt_s"), "alignment.output.grid.dt_s")
        pre = number(grid.get("pre_s"), "alignment.output.grid.pre_s")
        post = number(grid.get("post_s"), "alignment.output.grid.post_s")
    except ChainError as error:
        for name in ("aligned_grid_is_uniform_at_declared_dt",
                     "aligned_csv_span_matches_declared_grid"):
            _check(state, name, False, str(error))
        return
    tolerance = max(dt * 1e-9, TIME_EPS)
    _check(state, "aligned_csv_span_matches_declared_grid",
           abs(state["t"][0] + pre) <= tolerance and abs(state["t"][-1] - post) <= tolerance,
           f"CSV spans [{state['t'][0]:.9g}, {state['t'][-1]:.9g}] s, report declares "
           f"[-{pre:.9g}, +{post:.9g}] s")
    spacings = [b - a for a, b in zip(state["t"], state["t"][1:])]
    uniform = all(abs(step - dt) <= dt * 1e-9 for step in spacings)
    _check(state, "aligned_grid_is_uniform_at_declared_dt", uniform,
           f"sample spacings are not a uniform {dt:.9g} s grid")
    _check(state, "observed_sample_spacing_matches_aligned_dt",
           state["submitted"].get("max_sample_spacing_observed_s") == max(spacings),
           "capture audit spacing does not match the supplied CSV")
    nearest = min(range(len(state["t"])), key=lambda i: abs(state["t"][i]))
    state["origin_value"] = state["traces"]["TRIP_STIMULUS"][nearest]
    _check(state, "aligned_grid_includes_the_trip_origin",
           abs(state["t"][nearest]) <= dt / 2 + TIME_EPS,
           f"no aligned sample within dt_s/2 of t=0 (nearest {state['t'][nearest]:.9g} s)")


def _check_alignment_status(state: dict) -> None:
    alignment = state["alignment"]
    status = alignment.get("status")
    _check(state, "alignment_status_is_known", status in KNOWN_ALIGNMENT,
           f"unsupported alignment status {status!r}")
    structural = {name: value for name, value in (alignment.get("checks") or {}).items()
                  if name != "provenance_complete"}
    _check(state, "alignment_structural_checks_all_pass",
           bool(structural) and all(value is True for value in structural.values()),
           "alignment report has failed or missing structural checks")


def _check_grid_against_limits(state: dict) -> None:
    names = ("grid_dt_meets_capture_auditor_limit", "grid_pre_covers_min_pretrip",
             "grid_post_covers_disable_plus_hold")
    try:
        problems = grid_problems(state["alignment"], state["config"])
    except ChainError as error:
        for name in names:
            _check(state, name, False, str(error))
        return
    for name, token in zip(names, ("dt_s", "min_pretrip_s", "min_post_trip_hold_s")):
        _check(state, name, not any(token in text for text in problems),
               next((text for text in problems if token in text), ""))


def _check_trigger(state: dict) -> None:
    if "origin_value" not in state:
        _check(state, "trip_trigger_threshold_outside_ambiguous_band", False,
               "no aligned origin sample available")
        _check(state, "origin_trip_sample_is_unambiguous", False,
               "no aligned origin sample available")
        return
    try:
        threshold = trip_threshold(state["manifest"])
        problems = trigger_problems(threshold, state["config"], state["origin_value"])
    except ChainError as error:
        _check(state, "trip_trigger_threshold_outside_ambiguous_band", False, str(error))
        _check(state, "origin_trip_sample_is_unambiguous", False, str(error))
        return
    _check(state, "trip_trigger_threshold_outside_ambiguous_band",
           not any("threshold" in text for text in problems), problems[0] if problems else "")
    _check(state, "origin_trip_sample_is_unambiguous",
           not any("origin" in text for text in problems),
           next((text for text in problems if "origin" in text), ""))
    high = number(state["config"].get("trip_high_min_v"), "config.trip_high_min_v")
    if threshold != high:
        state["warnings"].append(
            f"trigger threshold {threshold:.9g} V differs from trip_high_min_v={high:.9g} V; "
            "chapter 31 recommends equality so the origin sample is unambiguously high")


def _audit_projection(report: dict) -> dict:
    """Every field except ``source``: its paths are CLI input, its digests are
    already bound by the dedicated hash checks (and a fresh run names its own).
    """
    return {key: value for key, value in report.items() if key != "source"}


def _alignment_projection(report: dict) -> dict:
    """Every deterministic field; only the CLI-supplied paths are excluded.

    Taking the complement (drop the path-bearing fields) rather than listing
    fields keeps a new report field inside the check instead of silently
    escaping it.
    """
    projection = {key: value for key, value in report.items()
                  if key not in ("source", "instruments", "output")}
    source = dict(report.get("source") or {})
    source.pop("manifest_path", None)
    projection["source"] = source
    # run() decorates the written output with its own path and digest; build()
    # does not, and the digest is compared directly against the submitted CSV.
    output = dict(report.get("output") or {})
    output.pop("csv_path", None)
    output.pop("csv_sha256", None)
    projection["output"] = output
    projection["instruments"] = [
        {key: value for key, value in item.items() if key != "csv_path"}
        for item in report.get("instruments") or []
    ]
    return projection


def _instrument_paths(manifest: dict, base: Path) -> list[Path]:
    paths = []
    for instrument in manifest.get("instruments") or []:
        raw = instrument.get("csv")
        if not isinstance(raw, str) or not raw.strip():
            raise ChainError(f"instrument {instrument.get('id')!r}: missing csv path")
        path = Path(raw)
        paths.append(path if path.is_absolute() else base / path)
    return paths


def _judge_unavailable(state: dict, reason: str) -> None:
    state["checks"]["alignment_report_is_reproducible_from_the_manifest"] = False
    state["reproduction"] = {"status": "UNAVAILABLE", "reason": reason}
    state["reproduction_unavailable"] = True
    state["warnings"].append(
        "cannot re-run the aligner because an instrument record is unavailable; "
        f"the chain is bound but not independently reproducible: {reason}")


def _check_alignment_reproduction(state: dict, manifest_path: Path) -> None:
    """Re-run chapter 31; the alignment report itself is bound by no hash."""
    try:
        paths = _instrument_paths(state["manifest"], manifest_path.parent)
    except ChainError as error:
        _check(state, "alignment_report_is_reproducible_from_the_manifest", False, str(error))
        state["reproduction"] = {"status": "MISMATCHED", "reason": str(error)}
        return
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        _judge_unavailable(state, "missing instrument record(s): " + ", ".join(missing))
        return
    try:
        regenerated, rows = align.build(manifest_path)
    except OSError as error:
        _judge_unavailable(state, str(error))
        return
    except (align.InvalidAlignment, ValueError, TypeError, KeyError) as error:
        _check(state, "alignment_report_is_reproducible_from_the_manifest", False,
               f"the aligner rejects the supplied manifest: {error}")
        state["reproduction"] = {"status": "MISMATCHED", "reason": str(error)}
        return
    with tempfile.TemporaryDirectory() as directory:
        digest = align.write_aligned_csv(Path(directory) / "aligned.csv", rows)
    same = (_alignment_projection(state["alignment"]) == _alignment_projection(regenerated)
            and digest == state["inputs"]["csv"]["sha256"])
    _check(state, "alignment_report_is_reproducible_from_the_manifest", same,
           "submitted alignment fields differ from a fresh alignment of the same manifest")
    state["reproduction"] = {
        "status": "MATCHED" if same else "MISMATCHED",
        "reason": "" if same else "regenerated report or CSV bytes differ",
    }


def _check_audit_reproduction(state: dict, csv_path: Path, config_path: Path) -> None:
    submitted = state["submitted"]
    status = submitted.get("status")
    _check(state, "capture_audit_status_is_known", status in KNOWN_AUDIT,
           f"unsupported capture audit status {status!r}")
    try:
        expected_limits = audit.config_limits(state["config"])
    except (audit.InvalidCapture, TypeError, KeyError) as error:
        _check(state, "audit_limits_equal_config_limits", False, str(error))
    else:
        _check(state, "audit_limits_equal_config_limits", submitted.get("limits") == expected_limits,
               "capture audit limits differ from the supplied config")
    try:
        recomputed = audit.run(csv_path, config_path)
    except (audit.InvalidCapture, OSError, ValueError, TypeError, KeyError) as error:
        _check(state, "audit_report_is_reproducible_from_the_csv_and_config", False,
               f"cannot reproduce the capture audit: {error}")
        return
    same = _audit_projection(submitted) == _audit_projection(recomputed)
    _check(state, "audit_report_is_reproducible_from_the_csv_and_config", same,
           "submitted audit fields differ from a fresh audit of the same CSV and config")


def _check_release_flags(state: dict) -> None:
    # The alignment report owns all five flags; the capture audit does not model
    # physical simultaneity, so that flag is optional there but must be false if
    # present. Any flag that IS present must be exactly false.
    required = {
        "alignment": RELEASE_FLAGS,
        "capture audit": tuple(flag for flag in RELEASE_FLAGS
                               if flag != "physical_simultaneity_proven"),
    }
    bad: list[str] = []
    for label, doc in (("alignment", state["alignment"]), ("capture audit", state["submitted"])):
        for flag in RELEASE_FLAGS:
            if flag not in doc:
                if flag in required[label]:
                    bad.append(f"{label}.{flag} is missing")
            elif doc[flag] is not False:
                bad.append(f"{label}.{flag}={doc[flag]!r}")
        if doc.get("requires_independent_hardware_review") is not True:
            bad.append(f"{label}.requires_independent_hardware_review is not true")
    _check(state, "permanent_release_flags_remain_false", not bad,
           "an artifact claims a release state: " + ", ".join(bad))


def _status(state: dict) -> tuple[str, int]:
    if state["errors"]:
        return "CHAIN_INCONSISTENT", 2
    if state["submitted"].get("status") != "PASS_CAPTURE_ONLY":
        state["warnings"].append("the capture audit rejected this waveform; the chain is "
                                 "consistent but the evidence does not pass")
        return "CHAIN_CONSISTENT_AUDIT_REJECTED", 1
    if state.get("reproduction_unavailable"):
        return "CHAIN_CONSISTENT_PROVENANCE_INCOMPLETE", 1
    if state["alignment"].get("status") != "ALIGNED_FOR_CAPTURE_AUDIT":
        return "CHAIN_CONSISTENT_PROVENANCE_INCOMPLETE", 1
    return "CHAIN_CONSISTENT_CAPTURE_ONLY", 0


def _report(state: dict) -> dict:
    status, code = _status(state)
    return {
        "kind": "D0_CAPTURE_EVIDENCE_CHAIN",
        "schema_version": VERSION,
        "status": status,
        "exit_code": code,
        "case_id": state["manifest"].get("case_id"),
        "inputs": state["inputs"],
        "checks": state["checks"],
        "errors": state["errors"],
        "warnings": state["warnings"],
        "reproduction": state.get("reproduction", {"status": "NOT_RUN", "reason": ""}),
        "origin_classification": "CHAIN_BINDS_ARTIFACTS_ONLY_ORIGIN_UNVERIFIED",
        "physical_simultaneity_proven": False,
        "waveform_origin_authenticated": False,
        "all_ten_real_hardware_gates_verified": False,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "requires_independent_hardware_review": True,
        "limitations": [
            "the chain proves the artifacts describe the same capture, not that the capture is real",
            "resampled values are linear interpolations between original samples",
            "declared skew budgets are checked elsewhere; this tool does not re-measure them",
            "no hardware protection, SOA, or fabrication approval is implied",
        ],
    }


def _invalid_report(error: Exception) -> dict:
    return {
        "kind": "D0_CAPTURE_EVIDENCE_CHAIN",
        "schema_version": VERSION,
        "status": "CHAIN_INCONSISTENT",
        "exit_code": 2,
        "checks": {},
        "errors": [str(error)],
        "warnings": [],
        "reproduction": {"status": "NOT_RUN", "reason": str(error)},
        "physical_simultaneity_proven": False,
        "waveform_origin_authenticated": False,
        "all_ten_real_hardware_gates_verified": False,
        "hardware_protection_approved": False,
        "power_stage_fabrication_approved": False,
        "requires_independent_hardware_review": True,
    }


def run(manifest_path: Path, alignment_path: Path, csv_path: Path,
        config_path: Path, audit_path: Path) -> dict:
    try:
        state = _load_state(manifest_path, alignment_path, csv_path, config_path, audit_path)
    except (ChainError, OSError) as error:
        return _invalid_report(error)
    _bind_identity(state)
    _bind_csv(state, csv_path)
    _check_alignment_status(state)
    _check_grid_against_limits(state)
    _check_trigger(state)
    _check_alignment_reproduction(state, manifest_path)
    _check_audit_reproduction(state, csv_path, config_path)
    _check_release_flags(state)
    return _report(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="chapter 31 sync manifest")
    parser.add_argument("--alignment", type=Path, required=True, help="chapter 31 report JSON")
    parser.add_argument("--csv", type=Path, required=True, help="aligned 12-column CSV")
    parser.add_argument("--config", type=Path, required=True, help="chapter 29 reviewed limits")
    parser.add_argument("--audit", type=Path, required=True, help="chapter 29 audit report JSON")
    parser.add_argument("--report", type=Path, help="write machine-readable chain JSON")
    args = parser.parse_args(argv)
    report = run(args.manifest, args.alignment, args.csv, args.config, args.audit)
    body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(body, encoding="utf-8", newline="\n")
    print(body)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
