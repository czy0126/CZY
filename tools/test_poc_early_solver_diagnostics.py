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
