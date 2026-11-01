"""Keep missing CAD magnetic symbols aligned with physical winding polarity and golden nets."""
from __future__ import annotations

import sys

import magnetics_cad_contract as mc


def test_contract_contains_all_five_devices_and_exact_logical_pins():
    s = mc.build()
    assert {x["ref"] for x in s["symbols"]} == {"T1","T2","T3","T4","CT"}
    assert sum(len(x["pins"]) for x in s["symbols"]) == 24
    assert s["physical_terminal_mapping_required"]
    assert all(not x["native_symbol_present"] for x in s["symbols"])


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


def test_saved_contract_is_fresh_and_does_not_claim_native_cad(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['magnetics_cad_contract'])
    mc.main()
    assert all(p["physical_pad"] is None for s in mc.build()["symbols"] for p in s["pins"])
