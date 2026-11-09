"""Source-preserving 0.62ms numerical sensitivity only."""
import hashlib
import pytest
import poc_early_solver_diagnostics as d
import poc_low_current_decks as poc


@pytest.mark.parametrize("variant", list(d.MODELS))
def test_early_deck_keeps_tank_ct_and_48v_start(variant):
    name, deck, model, text = d.build(variant)
    assert ".tran 0 620u 0 10n uic" in deck
    assert ".meas tran POC_VOUT_6_8_AVG" not in deck
    assert ".meas tran DIAG_VOUT_AT_600U" in deck
    assert ".param VIN=48 RL=0.4 LP=10u LR_TOTAL=1u CR_TOTAL=620n" in deck
    assert "Vbus vin0 0 PWL(0 0 400u 0 800u" in deck
    assert deck.endswith(".end\n")
    assert name.name.startswith("_diag_5a_")
    assert d.MODEL.is_file()
    if model is None:
        assert text is None
        assert ".include ../../models/sr_device_v3.lib" in deck
    else:
        assert model.name in deck
        assert "SR_DEVICE" in text


def test_tt0_only_changes_both_diode_transit_times():
    _, _, _, mod = d.build("on_tt0")
    old = d.MODEL.read_text(encoding="utf-8")
    assert "TT=27n" not in mod.replace(
        "* TT=27 ns: diode-only", "* no longer in active model")
    assert mod.count("TT=0 CJO=0 RS=1m") == 2
    assert old.count("TT=27n CJO=0 RS=1m") == 2


def test_weak_leak_does_not_change_golden_model():
    _, _, _, mod = d.build("on_weak_shunt")
    assert mod.count("Rdiagleak si di 100Meg") == 2
    assert "Rdiagleak si di 100Meg" not in d.MODEL.read_text()


def test_reject_unknown_model_variant():
    with pytest.raises(ValueError):
        d.build("not_a_real_variant")


def test_early_solver_wall_clock_expiry_emits_failure_evidence(monkeypatch, tmp_path):
    import json
    import subprocess
    exe = tmp_path / "LTspice.exe"
    exe.write_bytes(b"test-only stub")
    monkeypatch.setattr(poc, "OUT", tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 7, output=b"partial stdout")
    monkeypatch.setattr(d.subprocess, "run", timeout)
    assert d.run("off_original", exe, timeout_s=7) == 2
    evidence = json.loads((tmp_path / "_diag_5a_off_original.json").read_text())
    assert evidence["diagnostic_run_validated"] is False
    assert "exceeded 7s" in evidence["failure_reason"]
    assert evidence["returncode"] is None
    assert evidence["log_sha256"] is None
    assert evidence["raw_validation"]["status"] == "MISSING_RAW"
    assert evidence["stdout_tail"] == "partial stdout"
    assert evidence["hardware_qualified"] is False


def test_process_exit_zero_without_raw_and_measurements_is_not_valid(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    exe = tmp_path / "LTspice.exe"
    exe.write_bytes(b"test-only stub")
    monkeypatch.setattr(poc, "OUT", tmp_path)
    monkeypatch.setattr(d.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(
                            returncode=0, stdout="", stderr=""))
    assert d.run("on_original", exe, timeout_s=10) == 2
    result = json.loads((tmp_path / "_diag_5a_on_original.json").read_text())
    assert result["diagnostic_run_validated"] is False
    assert result["returncode"] == 0
    assert result["diagnostic_measurements"] is None


def test_early_diagnostic_meas_must_be_unique_finite(tmp_path):
    bad = tmp_path / "diag.log"
    bad.write_text("diag_vout_at_600u: V(out) = 1.0\n"
                   "diag_resonant_pk: MAX(abs(I(Lr))) = 1e308\n",
                   encoding="utf-8")
    with pytest.raises(ValueError, match="sentinel"):
        d.diagnostic_measurements(bad)
    bad.write_text("diag_vout_at_600u: V(out) = 1.7\n"
                   "diag_resonant_pk: MAX(abs(I(Lr))) = 2.3\n",
                   encoding="utf-8")
    x = d.diagnostic_measurements(bad)
    assert x["diag_vout_at_600u"] == pytest.approx(1.7)
    assert x["diag_resonant_pk"] == pytest.approx(2.3)


@pytest.mark.parametrize("variant", list(d.MODELS))
def test_10a_early_screen_is_truly_10a_not_relabelled_5a(variant):
    path, deck, model_path, model_text = d.build(variant, case="10a")
    assert path.name == f"_diag_10a_{variant}.cir"
    assert ".param VIN=48 RL=0.2 LP=10u LR_TOTAL=1u CR_TOTAL=620n" in deck
    assert ".param VIN=48 RL=0.4 LP=10u LR_TOTAL=1u CR_TOTAL=620n" not in deck
    assert ".tran 0 620u 0 10n uic" in deck
    assert ".meas tran DIAG_VOUT_AT_600U" in deck
    if model_path is not None:
        assert model_path.name.startswith("_diag_10a_")
        assert model_text is not None


def test_early_screen_rejects_unknown_resistive_load():
    with pytest.raises(ValueError, match="unknown diagnostic load case"):
        d.build("off_original", case="100a")
