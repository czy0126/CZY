"""Real evidence quality screen regression. No synthesized LTspice observations."""
from __future__ import annotations

import json

import poc_low_current_quality as q


def test_latest_5a_sr_on_is_complete_but_not_steady():
    p = q.DIR / "poc_5a_comparison_model_only.json"
    source = json.loads(p.read_text(encoding="utf-8"))
    report = q.evaluate_case("5a", source, "sourcehash")
    on = report["modes"]["on"]
    off = report["modes"]["off"]
    assert report["paired_8ms_comparison_recorded"] is True
    assert report["paired_steady_state_comparison_qualified"] is False
    assert on["status"] == "DYNAMIC_6_TO_8MS_WINDOW_NOT_STEADY"
    assert on["complete_8ms_claim"] is True
    assert on["min_to_mean_variation_lower_bound_fraction"] > 0.11
    assert on["output_v_avg_6_to_8ms"] > 1.84
    assert on["output_v_min_6_to_8ms"] < 1.64
    assert on["output_v_max_0_to_8ms_not_same_window"] > 2.06
    assert off["status"] == "MIN_GAP_SMALL_NOT_STEADY_PROOF"
    assert off["steady_state_qualified"] is False
    assert on["raw_binary_physically_rehashed_here"] is False
    assert not report["hardware_fabrication_approved"]


def test_10a_has_only_real_off_no_paired_sr_on_conclusion():
    report = json.loads(
        (q.DIR / "poc_10a_comparison_model_only.json").read_text(encoding="utf-8"))
    row = q.evaluate_case("10a", report, "sourcehash")
    assert row["modes"]["off"]["complete_8ms_claim"] is True
    assert row["modes"]["on"]["status"] == "NO_COMPLETED_SIMULATION_RECORD"
    assert row["paired_8ms_comparison_recorded"] is False
    assert row["paired_steady_state_comparison_qualified"] is False
    assert row["modes"]["off"]["estimated_mean_output_current_a"] > 6.65


def test_invalid_or_missing_evidence_never_becomes_qualified():
    valid = json.loads(
        (q.DIR / "poc_5a_comparison_model_only.json").read_text(encoding="utf-8"))
    good = valid["runs"]["on"]
    edited = {**good, "measures": {**good["measures"],
              "poc_vout_6_8_avg": float("nan")}}
    assert q.evaluate_run(edited, 0.4)["complete_8ms_claim"] is False
    edited = {**good, "raw_evidence":
              {**good["raw_evidence"], "status": "INVALID_RAW"}}
    assert q.evaluate_run(edited, 0.4)["complete_8ms_claim"] is False
    edited = {**good, "log_sha256": ""}
    assert q.evaluate_run(edited, 0.4)["complete_8ms_claim"] is False
    edited = {**good, "measures": {**good["measures"],
              "poc_vout_6_8_avg": 1.0, "poc_vout_min": 1.6}}
    assert q.evaluate_run(edited, 0.4)["status"] == "INCONSISTENT_AVG_BELOW_MIN"
    assert q.evaluate_run(None, 0.4)["status"] == "NO_COMPLETED_SIMULATION_RECORD"


def test_cli_validates_snapshots_but_explicit_steady_gate_fails(capsys):
    assert q.main(["--check"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["hardware_release"] is False
    assert result["cases"]["5a"]["paired_steady_state_comparison_qualified"] is False
    assert q.main(["--require-steady"]) == 2
    assert q.main(["--case", "10a", "--require-steady"]) == 2


def test_report_rejects_trust_elevation_or_wrong_case():
    record = json.loads(
        (q.DIR / "poc_5a_comparison_model_only.json").read_text(encoding="utf-8"))
    try:
        q.evaluate_case("10a", record, "hash")
        assert False, "must reject case mismatch"
    except ValueError:
        pass
    try:
        q.evaluate_case("5a", {**record, "fab_release": True}, "hash")
        assert False, "must refuse unsupported hardware claims"
    except ValueError:
        pass
