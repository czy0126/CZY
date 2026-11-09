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


def test_both_mode_runs_independent_off_first_and_keeps_failed_attempt(monkeypatch, tmp_path):
    """An expensive/unconverged ON run cannot erase the completed OFF baseline."""
    observed = []
    monkeypatch.setattr(runner, "find_ltspice", lambda _: tmp_path / "LTspice.exe")
    monkeypatch.setattr(runner.poc, "OUT", tmp_path)
    monkeypatch.setattr(runner.poc, "ROOT", tmp_path)
    monkeypatch.setattr(runner.poc, "path",
                        lambda case, mode: tmp_path / f"poc_{case}_sr_{mode}.cir")
    monkeypatch.setattr(runner.poc, "manifest", lambda: {"status": "SOURCE_ONLY"})
    monkeypatch.setattr(runner.sys, "argv",
                        ["run_poc_low_current.py", "--case", "5a",
                         "--mode", "both", "--run", "--timeout-sec", "123"])
    def solver(case, mode, exe, timeout_sec):
        observed.append((case, mode, timeout_sec))
        if mode == "on":
            (tmp_path / "poc_5a_sr_on.log").write_text(
                "real partial but invalid log", encoding="utf-8")
            raise RuntimeError("intentional ON solver divergence")
        return {"measures": {key: 1.0 for key in runner.REQUIRED},
                "status": "SIMULATION_ONLY", "hardware_qualified": False}
    monkeypatch.setattr(runner, "run_selected", solver)
    assert runner.main() == 2
    assert observed == [("5a", "off", 123), ("5a", "on", 123)]
    result = json.loads((tmp_path / "poc_5a_comparison_model_only.json")
                        .read_text(encoding="utf-8"))
    assert list(result["runs"]) == ["off"]
    assert result["all_requested_modes_completed"] is False
    assert result["partial_failed_mode_files_NOT_VALID_RESULTS"]["on"][".log"]["present"]
    assert result["partial_failed_mode_files_NOT_VALID_RESULTS"]["on"][".log"]["validated_complete"] is False
    assert result["partial_failed_mode_files_NOT_VALID_RESULTS"]["on"][".raw"]["present"] is False
    assert result["comparison"]["comparison_available"] is False
    assert result["fab_release"] is False


def test_partial_log_sha_cannot_be_mistaken_for_success(monkeypatch, tmp_path):
    d = tmp_path / "poc_10a_sr_on.cir"
    d.write_text("test source", encoding="utf-8")
    log = d.with_suffix(".log")
    raw = d.with_suffix(".raw")
    log.write_bytes(b"partial waveform error")
    raw.write_bytes(b"truncated binary raw")
    monkeypatch.setattr(runner.poc, "ROOT", tmp_path)
    monkeypatch.setattr(runner.poc, "path", lambda *_: d)
    part = runner.partial_artifacts("10a", "on")
    assert part[".log"]["sha256"] == __import__("hashlib").sha256(log.read_bytes()).hexdigest()
    assert part[".raw"]["size_bytes"] == len(raw.read_bytes())
    assert not part[".raw"]["validated_complete"]


def test_early_on_failure_avoids_full_on_but_retains_off_result(monkeypatch, tmp_path):
    import poc_early_solver_diagnostics as diagnostic
    calls = []
    monkeypatch.setattr(runner, "find_ltspice", lambda _: tmp_path / "LTspice.exe")
    monkeypatch.setattr(runner.poc, "OUT", tmp_path)
    monkeypatch.setattr(runner.poc, "ROOT", tmp_path)
    monkeypatch.setattr(runner.poc, "path",
                        lambda case, mode: tmp_path / f"poc_{case}_sr_{mode}.cir")
    monkeypatch.setattr(runner.poc, "manifest", lambda: {"status": "SOURCE_ONLY"})
    monkeypatch.setattr(runner.sys, "argv",
                        ["run_poc_low_current.py", "--case", "5a",
                         "--mode", "both", "--run", "--early-on-screen"])
    def mock_run(case, mode, exe, timeout_sec):
        calls.append(mode)
        return {"measures": {key: 1.0 for key in runner.REQUIRED},
                "status": "SIMULATION_ONLY"}
    def mock_diag(scenario, exe, timeout_s, case):
        assert scenario == "on_original"
        assert case == "5a"
        (tmp_path / "_diag_5a_on_original.json").write_text(json.dumps({
            "diagnostic_run_validated": False, "hardware_qualified": False}))
        return 2
    monkeypatch.setattr(runner, "run_selected", mock_run)
    monkeypatch.setattr(diagnostic, "run", mock_diag)
    assert runner.main() == 2
    assert calls == ["off"]
    report = json.loads((tmp_path / "poc_5a_comparison_model_only.json").read_text())
    assert report["early_on_screen"]["on"]["diagnostic_run_validated"] is False
    assert "on" in report["failed_modes"]
    assert report["partial_failed_mode_files_NOT_VALID_RESULTS"]["on"]["full_8ms_on"] == "NOT_ATTEMPTED"
    assert report["fab_release"] is False
