"""Protect real 5A / 10A result provenance, do not claim nominal current."""
import hashlib
from types import SimpleNamespace
import pytest
import run_poc_low_current as p


def test_5a_label_is_not_measured_current():
    v = {x: 0.1 for x in p.REQUIRED}
    v["poc_vout_6_8_avg"] = 1.87
    r = p.measured_load_point("5a", v)
    assert r["model_iout_avg_a"] == pytest.approx(4.675)
    assert r["nominal_current_at_ideal_2v_a"] == 5
    assert r["pout_dc_equivalent_only_w"] == pytest.approx(1.87**2/.4)
    assert r["thermal_or_hardware_qualified"] is False


def test_10a_target_is_not_assumed_to_have_regulated_at_2v():
    v = {x: 0.1 for x in p.REQUIRED}
    v["poc_vout_6_8_avg"] = 1.8
    assert p.measured_load_point("10a", v)["model_iout_avg_a"] == pytest.approx(9.0)


def test_no_raw_even_with_fresh_valid_log_is_not_a_complete_run(monkeypatch, tmp_path):
    d = tmp_path / "poc_5a_sr_on.cir"
    d.write_text("generated\n")
    monkeypatch.setattr(p.poc, "ROOT", tmp_path)
    monkeypatch.setattr(p.poc, "path", lambda *_: d)
    monkeypatch.setattr(p.poc, "deck", lambda *_: "generated\n")
    monkeypatch.setattr(p.time, "time_ns", lambda: 1)
    def fake_run(*a, **kw):
        d.with_suffix(".log").write_text("valid log but missing .raw")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(p.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="raw"):
        p.run_selected("5a", "on", tmp_path / "LTspice.exe")


def test_sha_is_exact_even_for_binary_waveform(tmp_path):
    f = tmp_path / "wave.raw"
    f.write_bytes(bytes(range(256))*4096)
    assert p.digest_file(f) == hashlib.sha256(f.read_bytes()).hexdigest()
