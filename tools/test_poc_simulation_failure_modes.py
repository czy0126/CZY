"""Real solver log failure diagnostics: UTF-16, overflow, continue on SR_ON fail."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import run_poc_low_current as runner


def sample_log(overflow=False):
    d = {name: 1.23 for name in runner.REQUIRED}
    if overflow:
        d["poc_primary_max"] = 1e308
    return "\n".join(f"{k}: MAX(V(out))= {v:g} FROM 0 TO 0.008" for k, v in d.items())


def test_utf16le_log_from_real_lspice24_parses_correctly(tmp_path):
    path = tmp_path / "out.log"
    path.write_bytes(sample_log().encode("utf-16-le"))
    assert runner.measurements(runner.read_ltspice_log(path))["poc_primary_max"] == 1.23
    path.write_bytes(sample_log().encode("utf-16"))
    assert runner.measurements(runner.read_ltspice_log(path))["poc_primary_max"] == 1.23
    path.write_bytes(sample_log().encode("utf-8"))
    assert runner.measurements(runner.read_ltspice_log(path))["poc_primary_max"] == 1.23


def test_ltspice_numeric_sentinel_never_counts_as_valid_measurement():
    with pytest.raises(ValueError, match="sentinel"):
        runner.measurements(sample_log(overflow=True))
    with pytest.raises(ValueError, match="missing"):
        runner.measurements("poc_gate_a1_max: MAX(V(ga1))=2")


def test_failed_on_mode_still_executes_off_and_writes_explicit_partial_report(monkeypatch, tmp_path):
    calls = []
    def fake_run(case, mode, exe):
        calls.append(mode)
        if mode == "on":
            raise RuntimeError("Singular matrix: d:sb4:bd#int1")
        return {"status": "SIMULATION_ONLY", "measures":
                {name: 1.2 for name in runner.REQUIRED}, "hardware_qualified": False}
    monkeypatch.setattr(runner, "run_selected", fake_run)
    monkeypatch.setattr(runner, "find_ltspice", lambda _: tmp_path / "LTspice.exe")
    monkeypatch.setattr(runner.poc, "OUT", tmp_path)
    monkeypatch.setattr(runner.poc, "manifest", lambda: {"status": "MODEL_ONLY"})
    monkeypatch.setattr(sys, "argv", ["run_poc_low_current", "--case", "5a", "--mode", "both", "--run"])
    assert runner.main() == 2
    assert calls == ["on", "off"]
    data = json.loads((tmp_path / "poc_5a_comparison_model_only.json").read_text())
    assert data["status"] == "INCOMPLETE_OR_INVALID_SIMULATION"
    assert data["all_requested_modes_completed"] is False
    assert "on" in data["failed_modes"]
    assert "off" in data["runs"]
    assert data["comparison"]["comparison_available"] is False
    assert data["fab_release"] is False


def test_old_24_0_12_is_rejected_even_when_some_measures_exist():
    with pytest.raises(ValueError, match="requires LTspice 26"):
        runner.validate_engine_version("LTspice 24.0.12 for Windows\n" + sample_log())
    assert runner.validate_engine_version("LTspice 26.1.1 for Windows\n") == "LTspice 26.1.1"
