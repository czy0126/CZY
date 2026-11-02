"""Keep missing CAD magnetic symbols aligned with physical winding polarity and golden nets."""
from __future__ import annotations

import sys

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
