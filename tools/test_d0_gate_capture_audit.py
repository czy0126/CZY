"""Negative tests for real *capture* gating; generated traces are NOT hardware evidence."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

import d0_gate_capture_audit as m


def config():
    return {
        "schema_version": 1,
        "case_id": "SYNTHETIC_UNIT_TEST_NOT_A_BENCH_MEASUREMENT",
        "hardware_revision": "SYNTHETIC_TEST_ONLY",
        "instrument_id": "SYNTHETIC_TEST_ONLY",
        "limit_basis": "SYNTHETIC_TEST_ONLY",
        "limits_review_status": "ENGINEER_REVIEWED",
        "time_column": "time_s",
        "trip_column": "TRIP_STIMULUS",
        "gate_columns": list(m.GATES),
        "gate_off_max_v": 1.0,
        "gate_on_min_v": 4.0,
        "trip_low_max_v": 0.8,
        "trip_high_min_v": 2.5,
        "max_disable_latency_s": 2e-6,
        "max_sample_spacing_s": 0.2e-6,
        "min_pretrip_s": 2e-6,
        "min_post_trip_hold_s": 2e-6,
    }


def trace():
    t = [i * 0.1e-6 for i in range(301)]
    wave = {"TRIP_STIMULUS": [0 if i < 100 else 3.3 for i in range(len(t))]}
    for g, name in enumerate(m.GATES):
        wave[name] = [
            5.0 if ((80 + g <= i < 96) or (100 <= i <= 103 + g))
            else 0.0
            for i in range(len(t))
        ]
    return t, wave


def test_all_ten_synthetic_traces_pass_capture_only_not_hardware():
    cfg = config()
    t, wave = trace()
    report = m.evaluate(cfg, t, wave)
    assert report["status"] == "PASS_CAPTURE_ONLY"
    assert report["violations"] == []
    assert report["trip_time_s"] == pytest.approx(10e-6)
    assert set(report["channels"]) == set(m.GATES)
    assert all(v["pass_waveform"] for v in report["channels"].values())
    assert all(v["pretrip_excited"] for v in report["channels"].values())
    assert not report["hardware_protection_approved"]
    assert not report["power_stage_fabrication_approved"]
    assert not report["waveform_origin_authenticated"]


def test_each_of_ten_channels_is_independently_required():
    for gate in m.GATES:
        t, wave = trace()
        wave[gate] = [5.0] * len(t)
        report = m.evaluate(config(), t, wave)
        assert report["status"] == "REJECTED"
        assert not report["channels"][gate]["pass_waveform"]
        assert f"{gate}:NOT_OFF_BY_DEADLINE" in report["violations"]
        assert f"{gate}:POST_DEADLINE_REENABLE_OR_SPIKE" in report["violations"]


def test_single_late_reenable_pulse_fails_even_if_final_state_low():
    t, wave = trace()
    wave["SR4B"][140] = 5.0
    report = m.evaluate(config(), t, wave)
    assert report["status"] == "REJECTED"
    assert any("SR4B:POST_DEADLINE_REENABLE" in v for v in report["violations"])


def test_gate_that_never_toggled_cannot_fake_shutdown():
    t, wave = trace()
    wave["P_LO"] = [0.0] * len(t)
    report = m.evaluate(config(), t, wave)
    assert "P_LO:NOT_EXERCISED_BEFORE_TRIP" in report["violations"]
    assert report["status"] == "REJECTED"


def test_stuck_high_reset_or_trip_release_is_not_equivalent_to_latched_fault():
    t, wave = trace()
    wave["TRIP_STIMULUS"][180] = 0.0
    report = m.evaluate(config(), t, wave)
    assert "TRIP_NOT_HELD_AFTER_ASSERTION" in report["violations"]
    assert report["status"] == "REJECTED"


def test_missing_trip_and_initially_asserted_trip_are_rejected():
    t, wave = trace()
    wave["TRIP_STIMULUS"] = [0.0] * len(t)
    r = m.evaluate(config(), t, wave)
    assert r["status"] == "REJECTED"
    assert r["trip_time_s"] is None
    t, wave = trace()
    wave["TRIP_STIMULUS"] = [3.3] * len(t)
    r = m.evaluate(config(), t, wave)
    assert "TRIP_INITIAL_NOT_LOW" in r["violations"]


def test_bounce_or_second_fault_pulse_not_accepted():
    t, wave = trace()
    wave["TRIP_STIMULUS"][180:190] = [0.0] * 10
    r = m.evaluate(config(), t, wave)
    assert "TRIP_MUST_HAVE_EXACTLY_ONE_RISING_EDGE" in r["violations"]


def test_uncalibrated_limits_and_missing_instrument_provenance_block_pass():
    t, wave = trace()
    cfg = config()
    cfg["limits_review_status"] = "PENDING"
    cfg["instrument_id"] = "PENDING"
    result = m.evaluate(cfg, t, wave)
    assert result["status"] == "REJECTED"
    assert "LIMITS_NOT_ENGINEER_REVIEWED" in result["violations"]
    assert "MEASUREMENT_PROVENANCE_INCOMPLETE" in result["violations"]


def test_all_limits_are_explicit_finite_and_physically_ordered():
    for key, value in (
        ("max_disable_latency_s", 0),
        ("max_sample_spacing_s", float("nan")),
        ("gate_off_max_v", 6.0),
        ("trip_high_min_v", 0.1),
        ("max_sample_spacing_s", 1e-6),
        ("max_disable_latency_s", False),
    ):
        bad = config()
        bad[key] = value
        with pytest.raises(m.InvalidCapture):
            m.config_limits(bad)


def test_too_short_pretrip_posttrip_and_coarse_timestamps_rejected():
    t, wave = trace()
    short = config()
    short["min_post_trip_hold_s"] = 30e-6
    with pytest.raises(m.InvalidCapture, match="ends before"):
        m.evaluate(short, t, wave)
    short = config()
    short["min_pretrip_s"] = 20e-6
    with pytest.raises(m.InvalidCapture, match="pretrip"):
        m.evaluate(short, t, wave)
    badly_timed = t[:]
    badly_timed[60] = badly_timed[59]
    with pytest.raises(m.InvalidCapture, match="timestamp"):
        m.evaluate(config(), badly_timed, wave)


def test_unequal_or_missing_channels_rejected_without_partial_credit():
    t, wave = trace()
    del wave["SR4A"]
    with pytest.raises(m.InvalidCapture, match="channel set"):
        m.evaluate(config(), t, wave)
    t, wave = trace()
    wave["P_LO"].pop()
    with pytest.raises(m.InvalidCapture, match="sample lengths"):
        m.evaluate(config(), t, wave)


def write_fixture(path: Path, t, wave):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        names = ["time_s", "TRIP_STIMULUS", *m.GATES]
        writer.writerow(names)
        for i in range(len(t)):
            writer.writerow([t[i], *(wave[name][i] for name in names[1:])])


def test_csv_parser_rejects_duplicate_missing_nan_and_ragged(tmp_path):
    t, wave = trace()
    path = tmp_path / "capture.csv"
    write_fixture(path, t, wave)
    raw = path.read_text()
    assert len(m.read_csv(path)[0]) == 301
    path.write_text(raw.replace("P_HO,P_LO", "P_HO,P_HO", 1))
    with pytest.raises(m.InvalidCapture, match="duplicate"):
        m.read_csv(path)
    path.write_text(raw.replace("P_LO", "BROKEN", 1))
    with pytest.raises(m.InvalidCapture, match="missing"):
        m.read_csv(path)
    path.write_text(raw.replace(",5.0,", ",nan,", 1))
    with pytest.raises(m.InvalidCapture, match="nonfinite"):
        m.read_csv(path)
    path.write_text(raw + "1,2\n")
    with pytest.raises(m.InvalidCapture, match="ragged"):
        m.read_csv(path)


def test_cli_preflight_report_includes_exact_artifact_hashes(tmp_path):
    t, wave = trace()
    csv_path = tmp_path / "capture.csv"
    cfg_path = tmp_path / "config.json"
    write_fixture(csv_path, t, wave)
    cfg_path.write_text(json.dumps(config()), encoding="utf-8")
    out = m.run(csv_path, cfg_path)
    assert out["status"] == "PASS_CAPTURE_ONLY"
    assert out["source"]["csv_sha256"] == m.sha256(csv_path)
    assert out["source"]["config_sha256"] == m.sha256(cfg_path)
    assert not out["power_stage_fabrication_approved"]


def test_published_template_is_unreviewed_and_cannot_pass(tmp_path):
    template = m.Path(__file__).resolve().parents[1] / (
        "docs/D1_EXECUTION_KIT/templates/d0_ten_gate_capture_config_TEMPLATE.json")
    cfg = json.loads(template.read_text(encoding="utf-8"))
    assert cfg["limits_review_status"] == "PENDING"
    assert cfg["hardware_revision"] == "PENDING"
    assert cfg["instrument_id"] == "PENDING"
    t, wave = trace()
    with pytest.raises(m.InvalidCapture):
        m.evaluate(cfg, t, wave)
