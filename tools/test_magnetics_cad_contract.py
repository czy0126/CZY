"""Keep missing CAD magnetic symbols aligned with physical winding polarity and golden nets."""
from __future__ import annotations

import sys
import copy
import json

import pytest

import magnetics_cad_contract as mc


def test_contract_contains_all_five_devices_and_exact_logical_pins():
    s = mc.build()
    assert {x["ref"] for x in s["symbols"]} == {"T1","T2","T3","T4","CT"}
    assert sum(len(x["pins"]) for x in s["symbols"]) == 24
    assert s["physical_terminal_mapping_required"]


def test_native_symbol_presence_is_derived_from_the_recorded_devices():
    """Drawing a symbol is a lookup, not an assertion: the flag has to agree
    with project_symbols.json, the file the CLI writes when it creates the
    device.  A hand-edited 'true' is rejected as stale by main()."""
    native = mc.native_symbols()
    for sym in mc.build()["symbols"]:
        assert sym["native_symbol_present"] is (sym["ref"] in native), sym["ref"]
        if sym["native_symbol_present"]:
            assert sym["native_device_uuid"] == native[sym["ref"]]["native_device_uuid"]
            assert sym["native_symbol_uuid"] == native[sym["ref"]]["native_symbol_uuid"]
            assert sym["placeholder_footprint"], sym["ref"]
        else:
            assert "native_device_uuid" not in sym, sym["ref"]


def test_a_drawn_symbol_still_verifies_no_physical_pad():
    """The two flags are separate on purpose: the drawing exists, the vendor
    terminal drawing does not.  Drawing a symbol must never fill a pad."""
    for sym in mc.build()["symbols"]:
        assert sym["physical_pad_map_verified"] is False, sym["ref"]
        assert all(p["physical_pad"] is None for p in sym["pins"]), sym["ref"]


def test_without_the_native_record_the_claim_degrades(tmp_path, monkeypatch):
    """Deleting the record is the only way to lose the claim, and after that
    the contract must say so instead of keeping a stale 'true'."""
    monkeypatch.setattr(mc, "PROJECT_SYMBOLS", tmp_path / "absent.json")
    s = mc.build()
    assert all(not x["native_symbol_present"] for x in s["symbols"])
    assert s["status"] == "LOGICAL_CONTRACT_ONLY_NOT_NATIVE_CAD_OR_FAB"


def test_dot_relation_cannot_be_inverted_to_appear_done():
    for sym in mc.build()["symbols"]:
        pins = {p["logical_pin"]: p["polarity"] for p in sym["pins"]}
        if sym["ref"] == "CT":
            assert all(x == "UNVERIFIED_FROM_CT_VENDOR" for x in pins.values())
        else:
            assert pins["CTAP"] == "S_A_DOT_AND_S_B_NON_DOT"
            assert pins["SEC_A"] == "NON_DOT"
            assert pins["SEC_B"] == "DOT"
            assert pins["PRI_A"] == "DOT"
            assert pins["PRI_B"] == "NON_DOT"


def test_saved_contract_is_fresh_and_claims_no_physical_pads(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['magnetics_cad_contract'])
    mc.main()
    assert all(p["physical_pad"] is None for s in mc.build()["symbols"] for p in s["pins"])


def _frozen_refs():
    return {
        sym["ref"]: {pin["logical_pin"]: pin["golden_net"] for pin in sym["pins"]}
        for sym in mc.build()["symbols"]
    }


def test_source_of_truth_is_live_spice_not_only_cached_ok_true():
    pol = json.loads(mc.POLARITY.read_text(encoding="utf-8"))
    refs = _frozen_refs()
    mc.verify_spice_polarity(pol, refs)
    assert mc.spice_board.winding_layout()["ok"] is True


def test_mutating_the_saved_polarity_report_to_reverse_a_secondary_is_caught():
    pol = json.loads(mc.POLARITY.read_text(encoding="utf-8"))
    reversed_half = copy.deepcopy(pol)
    w = reversed_half["transformers"]["T2"]["secondary_b"]
    w["dot_pin"], w["non_dot_pin"] = w["non_dot_pin"], w["dot_pin"]
    # A cached ok=true cannot override actual inductance node order.
    reversed_half["ok"] = True
    with pytest.raises(ValueError, match="saved winding polarity is stale"):
        mc.verify_spice_polarity(reversed_half, _frozen_refs())


def test_a_cached_dot_report_cannot_hide_a_reversed_live_spice_inductor(monkeypatch):
    pol = json.loads(mc.POLARITY.read_text(encoding="utf-8"))
    original_live = mc.spice_board.winding_layout
    live = original_live()
    corrupted = copy.deepcopy(live)
    corrupted["ok"] = False
    corrupted["checks"][0]["ok"] = False
    monkeypatch.setattr(mc.spice_board, "winding_layout", lambda: corrupted)
    with pytest.raises(ValueError, match="live SPICE winding polarity invalid"):
        mc.verify_spice_polarity(pol, refs)


def test_wrong_sole_ctap_or_secondary_golden_net_is_rejected():
    pol = json.loads(mc.POLARITY.read_text(encoding="utf-8"))
    for name, wrong in (("CTAP", "OUT"), ("SEC_A", "SEC_B_ALIAS"),
                        ("PRI_A", "PRI_12")):
        refs = _frozen_refs()
        refs["T1"][name] = wrong
        with pytest.raises(ValueError, match="golden net"):
            mc.verify_spice_polarity(pol, refs)


def test_primary_or_secondary_dot_pin_pair_inverted_in_live_map_is_rejected(monkeypatch):
    pol = json.loads(mc.POLARITY.read_text(encoding="utf-8"))
    original = mc.spice_board.winding_layout
    for section in ("primary", "secondary_a", "secondary_b"):
        live = copy.deepcopy(original())
        wind = live["transformers"]["T3"][section]
        wind["dot_pin"], wind["non_dot_pin"] = wind["non_dot_pin"], wind["dot_pin"]
        monkeypatch.setattr(mc.spice_board, "winding_layout", lambda live=live: live)
        with pytest.raises(ValueError, match="saved winding polarity is stale"):
            mc.verify_spice_polarity(pol, _frozen_refs_from_saved_contract())


def _frozen_refs_from_saved_contract():
    document = json.loads(mc.OUT.read_text(encoding="utf-8"))
    return {
        sym["ref"]: {pin["logical_pin"]: pin["golden_net"] for pin in sym["pins"]}
        for sym in document["symbols"]
    }
