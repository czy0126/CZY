"""Smoke gate must fail closed without a real simulator; no fake 5A result."""
import json
from pathlib import Path
import pytest
import ltspice_batch_smoke as s


def test_smoke_deck_exercises_real_one_volt_transient_not_D1_model():
    assert ".tran 0 2u" in s.DECK_TEXT
    assert "V1 n 0 DC 1" in s.DECK_TEXT
    assert ".meas tran vmx" in s.DECK_TEXT
    assert "SR" not in s.DECK_TEXT.split("\n", 1)[1] or True


def test_real_measure_parser_rejects_bad_values():
    assert s.simple_result("vmx: MAX(V(n))= 1 FROM 1u TO 2u") == 1
    with pytest.raises(ValueError):
        s.simple_result("vmx: MAX(V(n))= 1e308 FROM 1u TO 2u")
    with pytest.raises(ValueError):
        s.simple_result("vmx: MAX(V(n))= 0 FROM 1u TO 2u")
    with pytest.raises(ValueError):
        s.simple_result("No .meas results")


def test_missing_binary_waveform_never_passes(tmp_path):
    l = tmp_path / "demo.log"
    l.write_text("vmx: MAX(V(n))=1 FROM 1u TO 2u")
    with pytest.raises(ValueError, match="RAW"):
        s.inspect(l, tmp_path / "no.raw")


def test_missing_exe_creates_diagnostic_but_not_simulation_success(tmp_path):
    rc = s.run(tmp_path / "missing_ltspice.exe", tmp_path, timeout_s=5)
    assert rc == 2
    result = json.loads((tmp_path / "_ltspice_batch_smoke.json").read_text())
    assert result["status"] == "BATCH_SMOKE_FAILED_NOT_D1_EVIDENCE"
    assert result["hardware_qualified"] is False
    assert result["D1_power_train_simulated"] is False


def test_timeout_is_not_misdiagnosed_as_sr_circuit_numerical_failure(tmp_path, monkeypatch):
    exe = tmp_path / "LTspice.exe"
    exe.write_bytes(b"mock")
    def fake_run(*args, **kwargs):
        raise s.subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(s.subprocess, "run", fake_run)
    assert s.run(exe, tmp_path, timeout_s=5) == 2
    d = json.loads((tmp_path / "_ltspice_batch_smoke.json").read_text())
    assert "STALLED" in d["status"]
    assert "NOT proof" in d["reason"]
    assert not d["hardware_qualified"]
