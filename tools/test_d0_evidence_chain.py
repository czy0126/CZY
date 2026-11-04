"""Tests for the D0 capture evidence-chain binder.

Every waveform here is synthesized. These tests prove the chain *arithmetic and
fail-closed checks*, not bench behaviour; no test may be cited as hardware
evidence.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


import d0_evidence_chain as chain
import d0_gate_capture_audit as audit
import d0_scope_sync_align as align

PRE_S = 300e-6
POST_S = 150e-6
DT_S = 1e-6
SHIFT_B_S = 3e-6
CASE_ID = "SYNTHETIC_CHAIN_TEST_NOT_A_BENCH_MEASUREMENT"


def gate_slots() -> dict[str, tuple[float, float]]:
    names = ("P_HO", "P_LO", "SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B")
    return {name: (-90e-6 + 6e-6 * i, -86e-6 + 6e-6 * i) for i, name in enumerate(names)}


def physical_signal(name: str, p: float) -> float:
    if name == "TRIP_STIMULUS":
        return 5.0 if p >= 0 else 0.0
    start, stop = gate_slots()[name]
    return 5.0 if start <= p < stop else 0.0


def write_instrument(path: Path, shift: float, sources: tuple[str, ...],
                     trigger_column: str) -> None:
    physical = {name: name for name in sources}
    header = ["time_s", *sources]
    if trigger_column not in sources:
        header.append(trigger_column)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for step in range(-int(round(PRE_S / DT_S)), int(round(POST_S / DT_S)) + 1):
            tau = step * DT_S
            p = tau - shift
            row = [tau, *(physical_signal(physical[name], p) for name in sources)]
            if trigger_column not in sources:
                row.append(physical_signal("TRIP_STIMULUS", p))
            writer.writerow(row)


def make_manifest(tmp_path: Path, basis: str = "ENGINEER_REVIEWED") -> Path:
    a = tmp_path / "scope_a.csv"
    b = tmp_path / "scope_b.csv"
    write_instrument(a, 0.0, ("TRIP_STIMULUS", "P_HO", "P_LO"), "TRIP_STIMULUS")
    write_instrument(b, SHIFT_B_S,
                     ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
                     "SYNC")
    cfg = {
        "schema_version": 1,
        "case_id": CASE_ID,
        "sync": {
            "alignment_basis": "SYNTHETIC_TEST_ONLY",
            "basis_review_status": basis,
            "max_remaining_skew_s": 2e-6,
        },
        "grid": {"pre_s": 200e-6, "post_s": 50e-6, "dt_s": DT_S},
        "instruments": [
            {
                "id": "A", "csv": str(a), "time_column": "time_s",
                "trigger": {
                    "column": "TRIP_STIMULUS", "edge": "rising", "threshold_v": 2.5,
                    "search_start_s": -100e-6, "search_end_s": 100e-6,
                },
                "channels": {"TRIP_STIMULUS": "TRIP_STIMULUS",
                             "P_HO": "P_HO", "P_LO": "P_LO"},
                "instrument_id": "SYNTH_A", "probe_model": "SYNTHETIC_TEST_ONLY",
                "probe_bandwidth_hz": 100e6, "sample_rate_hz": 1.0 / DT_S,
            },
            {
                "id": "B", "csv": str(b), "time_column": "time_s",
                "trigger": {
                    "column": "SYNC", "edge": "rising", "threshold_v": 2.5,
                    "search_start_s": SHIFT_B_S - 100e-6,
                    "search_end_s": SHIFT_B_S + 100e-6,
                },
                "channels": {name: name for name in
                             ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B")},
                "instrument_id": "SYNTH_B", "probe_model": "SYNTHETIC_TEST_ONLY",
                "probe_bandwidth_hz": 100e6, "sample_rate_hz": 1.0 / DT_S,
            },
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def capture_config(**overrides) -> dict:
    cfg = {
        "schema_version": 1,
        "case_id": CASE_ID,
        "hardware_revision": "SYNTHETIC_TEST_ONLY",
        "instrument_id": "SYNTHETIC_TEST_ONLY",
        "limit_basis": "SYNTHETIC_TEST_ONLY",
        "limits_review_status": "ENGINEER_REVIEWED",
        "time_column": "time_s",
        "trip_column": "TRIP_STIMULUS",
        "gate_columns": list(audit.GATES),
        "gate_off_max_v": 1.0,
        "gate_on_min_v": 4.0,
        "gate_overlap_forbidden_above_v": 2.0,
        "trip_low_max_v": 0.8,
        "trip_high_min_v": 2.5,
        "max_disable_latency_s": 10e-6,
        "max_sample_spacing_s": 2e-6,
        "min_pretrip_s": 100e-6,
        "min_post_trip_hold_s": 20e-6,
    }
    cfg.update(overrides)
    return cfg


class Case:
    def __init__(self, tmp_path: Path, basis: str = "ENGINEER_REVIEWED",
                 config_overrides: dict | None = None):
        self.dir = tmp_path
        self.manifest = make_manifest(tmp_path, basis=basis)
        self.csv = tmp_path / "aligned.csv"
        self.alignment_path = tmp_path / "alignment.json"
        assert align.run(self.manifest, self.csv, self.alignment_path) in (0, 1)
        self.config = capture_config(**(config_overrides or {}))
        self.config_path = tmp_path / "limits.json"
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.audit_path = tmp_path / "audit.json"
        result = audit.run(self.csv, self.config_path)
        self.audit_path.write_text(json.dumps(result), encoding="utf-8")

    def run(self) -> dict:
        return chain.run(self.manifest, self.alignment_path, self.csv,
                         self.config_path, self.audit_path)

    def rewrite(self, path: Path, mutate) -> None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(json.dumps(doc), encoding="utf-8")


def test_a_reviewed_chain_ending_in_a_capture_pass_is_consistent(tmp_path):
    report = Case(tmp_path).run()
    assert report["status"] == "CHAIN_CONSISTENT_CAPTURE_ONLY"
    assert report["exit_code"] == 0
    assert report["errors"] == []
    assert report["checks"]["audit_report_is_reproducible_from_the_csv_and_config"] is True
    assert report["checks"]["alignment_report_is_reproducible_from_the_manifest"] is True
    assert report["reproduction"]["status"] == "MATCHED"
    assert report["checks"]["permanent_release_flags_remain_false"] is True


def test_the_chain_records_every_input_hash(tmp_path):
    report = Case(tmp_path).run()
    for key in ("manifest", "alignment", "csv", "config", "audit"):
        assert len(report["inputs"][key]["sha256"]) == 64
        assert report["inputs"][key]["path"]


def test_the_chain_never_approves_hardware(tmp_path):
    report = Case(tmp_path).run()
    for flag in chain.RELEASE_FLAGS:
        assert report[flag] is False
    assert report["requires_independent_hardware_review"] is True


def test_the_twelve_column_contract_matches_both_tools(tmp_path):
    assert chain.expected_columns() == align.OUTPUT_COLUMNS
    assert set(chain.expected_columns()) == {"time_s", "TRIP_STIMULUS", *audit.GATES}


def test_a_different_csv_than_the_aligned_one_breaks_the_chain(tmp_path):
    case = Case(tmp_path)
    rows = list(csv.reader(case.csv.open(encoding="utf-8")))
    rows[-1][-1] = "0.25"
    with case.csv.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["exit_code"] == 2
    assert report["checks"]["csv_hash_matches_alignment_report"] is False
    assert report["checks"]["csv_hash_matches_capture_audit"] is False


def test_editing_the_audit_report_after_the_fact_is_detected(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.audit_path, lambda doc: doc.update(trip_time_s=1e-9))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["audit_report_is_reproducible_from_the_csv_and_config"] is False


def test_a_hand_edited_alignment_field_is_detected_by_the_rerun(tmp_path):
    # No other check reads this field, so only re-running the aligner can catch it.
    case = Case(tmp_path)
    case.rewrite(case.alignment_path,
                 lambda doc: doc["sync"].update(declared_max_remaining_skew_s=1e-9))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["alignment_report_is_reproducible_from_the_manifest"] is False
    assert report["reproduction"]["status"] == "MISMATCHED"


def test_a_forged_alignment_manifest_hash_is_detected_by_the_rerun(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.alignment_path,
                 lambda doc: doc["source"].update(manifest_sha256="0" * 64))
    report = case.run()
    assert report["checks"]["manifest_hash_matches_alignment_report"] is False
    assert report["checks"]["alignment_report_is_reproducible_from_the_manifest"] is False


def test_a_missing_instrument_record_downgrades_the_chain_but_never_greens_it(tmp_path):
    case = Case(tmp_path)
    (tmp_path / "scope_b.csv").unlink()
    report = case.run()
    assert report["status"] == "CHAIN_CONSISTENT_PROVENANCE_INCOMPLETE"
    assert report["exit_code"] == 1
    assert report["errors"] == []
    assert report["checks"]["alignment_report_is_reproducible_from_the_manifest"] is False
    assert report["reproduction"]["status"] == "UNAVAILABLE"


def test_a_config_hash_mismatch_is_detected(tmp_path):
    case = Case(tmp_path)
    case.config["min_pretrip_s"] = 150e-6
    case.config_path.write_text(json.dumps(case.config), encoding="utf-8")
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["config_hash_matches_capture_audit"] is False
    assert report["checks"]["audit_limits_equal_config_limits"] is False


def test_a_manifest_hash_mismatch_is_detected(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.manifest, lambda doc: doc["sync"].update(max_remaining_skew_s=1e-6))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["manifest_hash_matches_alignment_report"] is False


def test_a_report_claiming_a_release_flag_is_inconsistent(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.audit_path, lambda doc: doc.update(hardware_protection_approved=True))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["permanent_release_flags_remain_false"] is False


def test_a_non_uniform_aligned_grid_is_rejected(tmp_path):
    case = Case(tmp_path)
    rows = list(csv.reader(case.csv.open(encoding="utf-8")))
    rows[-1][0] = repr(float(rows[-1][0]) + 5e-6)
    with case.csv.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["aligned_grid_is_uniform_at_declared_dt"] is False


def test_a_declared_grid_that_differs_from_the_csv_span_is_rejected(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.alignment_path, lambda doc: doc["output"]["grid"].update(post_s=40e-6))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["aligned_csv_span_matches_declared_grid"] is False


def test_provenance_incomplete_alignment_still_binds_but_exits_one(tmp_path):
    report = Case(tmp_path, basis="PENDING").run()
    assert report["status"] == "CHAIN_CONSISTENT_PROVENANCE_INCOMPLETE"
    assert report["exit_code"] == 1
    assert report["errors"] == []


def test_a_rejected_capture_audit_is_a_chain_not_an_inconsistency(tmp_path):
    report = Case(tmp_path, config_overrides={"gate_on_min_v": 6.0}).run()
    assert report["status"] == "CHAIN_CONSISTENT_AUDIT_REJECTED"
    assert report["exit_code"] == 1
    assert report["checks"]["audit_report_is_reproducible_from_the_csv_and_config"] is True


def test_case_id_mismatch_is_rejected(tmp_path):
    case = Case(tmp_path)
    case.config["case_id"] = "SOME_OTHER_CAPTURE"
    case.config_path.write_text(json.dumps(case.config), encoding="utf-8")
    result = audit.run(case.csv, case.config_path)
    case.audit_path.write_text(json.dumps(result), encoding="utf-8")
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["case_ids_agree"] is False


def test_grid_problems_reject_a_dt_finer_than_the_auditor_limit():
    alignment = {"output": {"grid": {"dt_s": 3e-6, "pre_s": 100e-6, "post_s": 30e-6}}}
    config = capture_config()
    problems = chain.grid_problems(alignment, config)
    assert len(problems) == 1 and "dt_s" in problems[0]


def test_grid_problems_require_full_pre_and_post_coverage():
    alignment = {"output": {"grid": {"dt_s": 1e-6, "pre_s": 90e-6, "post_s": 25e-6}}}
    problems = chain.grid_problems(alignment, capture_config())
    assert len(problems) == 2
    assert any("min_pretrip_s" in text for text in problems)
    assert any("min_post_trip_hold_s" in text for text in problems)


def test_grid_problems_accept_a_marginally_sufficient_grid():
    alignment = {"output": {"grid": {"dt_s": 2e-6, "pre_s": 100e-6, "post_s": 30e-6}}}
    assert chain.grid_problems(alignment, capture_config()) == []


def test_the_trigger_threshold_inside_the_hysteresis_band_is_ambiguous():
    problems = chain.trigger_problems(2.5, capture_config(trip_low_max_v=2.0,
                                                          trip_high_min_v=3.0), 2.5)
    assert any("hysteresis" in text for text in problems)


def test_an_origin_sample_inside_the_band_is_ambiguous_even_with_a_safe_threshold():
    problems = chain.trigger_problems(2.5, capture_config(trip_low_max_v=2.0,
                                                          trip_high_min_v=3.0), 2.4)
    assert any("origin" in text for text in problems)


def test_threshold_equal_to_the_high_limit_is_not_ambiguous():
    assert chain.trigger_problems(2.5, capture_config(), 2.5) == []


def test_a_missing_audit_hash_key_is_a_clear_chain_error(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.audit_path, lambda doc: doc["source"].pop("csv_sha256"))
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert report["checks"]["csv_hash_matches_capture_audit"] is False


def test_main_returns_two_and_still_writes_a_report(tmp_path):
    case = Case(tmp_path)
    case.rewrite(case.audit_path, lambda doc: doc.update(trip_time_s=1e-9))
    out = tmp_path / "chain.json"
    code = chain.main(["--manifest", str(case.manifest), "--alignment",
                       str(case.alignment_path), "--csv", str(case.csv),
                       "--config", str(case.config_path), "--audit",
                       str(case.audit_path), "--report", str(out)])
    assert code == 2
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["status"] == "CHAIN_INCONSISTENT"
    assert written["power_stage_fabrication_approved"] is False


def test_a_malformed_report_is_refused_without_a_traceback(tmp_path):
    case = Case(tmp_path)
    case.alignment_path.write_text("{not json", encoding="utf-8")
    out = tmp_path / "chain.json"
    code = chain.main(["--manifest", str(case.manifest), "--alignment",
                       str(case.alignment_path), "--csv", str(case.csv),
                       "--config", str(case.config_path), "--audit",
                       str(case.audit_path), "--report", str(out)])
    assert code == 2
    assert "not valid JSON" in out.read_text(encoding="utf-8")


def test_duplicate_json_keys_are_refused(tmp_path):
    case = Case(tmp_path)
    text = case.audit_path.read_text(encoding="utf-8")
    case.audit_path.write_text(text.replace('"status": "PASS_CAPTURE_ONLY"',
                                           '"status": "REJECTED", "status": "PASS_CAPTURE_ONLY"'),
                               encoding="utf-8")
    report = case.run()
    assert report["status"] == "CHAIN_INCONSISTENT"
    assert any("duplicate JSON key" in error for error in report["errors"])
