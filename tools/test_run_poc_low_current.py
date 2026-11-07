"""Offline regression for genuine-LTspice-output parser; no claimed simulation."""
from __future__ import annotations

import json

import pytest

import run_poc_low_current as runner


def fixture_log(**updates) -> str:
    fake = {key: 0.1 for key in runner.REQUIRED}
    fake.update(updates)
    return "\n".join(
        f"{key}: AVG(V(out))= {v:.8g} FROM 0.006 TO 0.008"
        for key, v in fake.items()
    )


def test_stat_ltspice_log_measurements_are_parsed_without_unit_guess():
    fake = fixture_log(
        poc_vout_6_8_avg=1.89, poc_vout_max=2.32, poc_primary_max=9.44)
    observed = runner.measurements(fake)
    assert observed["poc_vout_6_8_avg"] == pytest.approx(1.89)
    assert observed["poc_primary_max"] == pytest.approx(9.44)
    assert len(observed) == len(runner.REQUIRED)


def test_absent_or_duplicate_measurements_are_not_claimed_as_results():
    example = fixture_log()
    with pytest.raises(ValueError, match="missing"):
        runner.measurements(example.replace("poc_primary_max", "disabled"))
    with pytest.raises(ValueError, match="duplicate"):
        runner.measurements(example + "\n" + example.splitlines()[0])


def test_simulation_comparison_is_only_a_diagnostic_not_a_hardware_gate():
    measure = runner.measurements(fixture_log(
        poc_vout_6_8_avg=1.9, poc_vout_max=2.3, poc_primary_max=8))
    shadow = dict(measure, poc_vout_6_8_avg=1.4, poc_vout_max=2.8)
    report = runner.simulated_comparison({"on": measure, "off": shadow})
    assert report["status"] == "SIMULATION_ONLY_NO_HARDWARE_RELEASE"
    assert report["comparison_available"] is True
    assert report["sr_gain_delta_v"] == pytest.approx(0.5)
    assert report["fabrication_approved"] is False
    assert report["performance_verified"] is False
    assert any("overvoltage" in x for x in report["diagnostic_flags"])
    assert runner.simulated_comparison({"on": measure})["comparison_available"] is False


def test_no_ltspice_found_never_fabricates_results(monkeypatch, tmp_path):
    monkeypatch.delenv("LTSPICE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.setattr("sys.argv",
                        ["run_poc_low_current.py", "--case", "5a",
                         "--mode", "both", "--run"])
    assert runner.main() == 2
    assert runner.find_ltspice(str(tmp_path / "missing.exe")) is None


def test_source_only_mode_is_explicitly_not_a_simulation(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_poc_low_current.py", "--check"])
    assert runner.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "SOURCE_ONLY"
    assert data["fabrication_approved"] is False
    assert all(v["deck_fresh"] is True for v in data["cases"].values())
    assert all(v["LTspice_run_performed_here"] is False
               for v in data["cases"].values())
