"""Guard the golden-vs-native netlist diff.

The diff is what certifies the native schematic, so it is the one place where a
silent "everything matches" is unacceptable.  These tests synthesise the export
the editor *would* produce for a correct board and then break it one way at a
time; each break has to show up in the result.
"""

from __future__ import annotations

import json
from pathlib import Path

import check_main_board_netlist as cmn
import main_board_schematic as mbs

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = mbs.load_library()
GOLDEN = mbs.load_golden()


def expected_export(refs: list[str], with_peripherals: bool = True) -> dict[str, dict[str, str]]:
    """The export of a board wired exactly right, derived independently of
    compare() so the test cannot agree with a bug in compare()."""
    out: dict[str, dict[str, str]] = {}
    for ref in refs:
        part = mbs.device_of(ref)
        symbol_pins = {p["num"] for p in LIBRARY[part]["pins"]}
        pads: dict[str, str] = {}
        for pin, net in GOLDEN[ref].items():
            for pad in mbs.pads_for(part, pin, symbol_pins):
                pads[pad] = net
        pads.update(mbs.BONDED_PADS.get(part, {}))
        out[ref] = pads
    if with_peripherals:
        for ref, spec in mbs.PERIPHERALS.items():
            out[ref] = dict(spec["pads"])
    return out


ALL_REFS = list(GOLDEN)


def test_a_correct_board_passes():
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["ok"], res["missing_or_wrong"]
    assert res["unexpected_nets"] == []
    assert res["not_placed"] == []


def test_every_pad_of_every_golden_pin_is_counted():
    """The count is the claim 'N pads were checked'.  It has to be the number of
    pads the golden netlist expands to, not the number of parts.  Peripheral
    pads are counted separately so the headline number keeps its meaning."""
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    want = sum(len(v) for v in expected_export(ALL_REFS, with_peripherals=False).values())
    bonded = sum(len(v) for v in mbs.BONDED_PADS.values())
    assert res["pads_checked"] + len(res["pads_bonded_by_design"]) == want
    assert len(res["pads_bonded_by_design"]) == bonded
    assert res["peripheral_pads_checked"] == sum(len(s["pads"]) for s in mbs.PERIPHERALS.values())


def test_a_wrong_net_on_an_assigned_pad_fails():
    """The failure this tool exists for: part present, pad present, wrong net."""
    export = expected_export(ALL_REFS)
    first_pad = next(iter(export["U1"]))
    export["U1"][first_pad] = "WRONG_NET"
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "U1", "pad": first_pad, "want": GOLDEN["U1"][first_pad], "got": "WRONG_NET"} \
        in res["missing_or_wrong"]


def test_an_unwired_assigned_pad_fails_and_is_reported_as_empty():
    export = expected_export(ALL_REFS)
    pad = next(iter(export["SR1A"]))
    export["SR1A"][pad] = ""
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert any(m["got"] == "<empty>" for m in res["missing_or_wrong"])


def test_a_bonded_pad_left_floating_is_a_failure():
    """EP is not in the golden netlist, so forgetting it cannot show up as a
    missing golden pin -- only this test does."""
    export = expected_export(ALL_REFS)
    del export["U2"]["11"]
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "U2", "pad": "11", "want": "PGND", "got": "<empty>"} in res["missing_or_wrong"]


def test_a_net_appearing_on_a_deliberately_open_pad_fails():
    """BAT54's spare anode is unused by design; a net on it means someone wired
    something the review sheet does not know about."""
    export = expected_export(ALL_REFS)
    export["D_CT1"]["2"] = "SOMEWHERE"
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "D_CT1", "pad": "2", "net": "SOMEWHERE"} in res["unexpected_nets"]


def test_a_magnetic_is_diffed_pad_by_pad_not_exempted():
    """The exemption is gone: a reversed winding or a swapped secondary pair
    must show up as a wrong net, like any other wiring defect."""
    export = expected_export(ALL_REFS)
    export["T1"]["SEC_A"], export["T1"]["SEC_B"] = export["T1"]["SEC_B"], export["T1"]["SEC_A"]
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "T1", "pad": "SEC_A", "want": GOLDEN["T1"]["SEC_A"],
            "got": GOLDEN["T1"]["SEC_B"]} in res["missing_or_wrong"]


def test_a_magnetic_with_the_wrong_pin_numbering_is_not_exempt():
    """The old exemption accepted any pad numbering.  A '1-5' symbol leaves
    every logical terminal unwired, which is a defect, not a pass."""
    export = expected_export(ALL_REFS)
    export["T1"] = {"1": GOLDEN["T1"]["PRI_A"], "2": GOLDEN["T1"]["PRI_B"],
                    "3": GOLDEN["T1"]["SEC_A"], "4": GOLDEN["T1"]["CTAP"],
                    "5": GOLDEN["T1"]["SEC_B"]}
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {m["pad"] for m in res["missing_or_wrong"]} == {"PRI_A", "PRI_B", "SEC_A", "CTAP", "SEC_B"}


def test_a_missing_non_magnetic_part_fails():
    export = expected_export(ALL_REFS)
    del export["QL"]
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert "QL" in res["not_placed"]
    assert {"ref": "QL", "pad": "*", "want": "part present", "got": "absent"} in res["missing_or_wrong"]


def test_partial_pass_never_means_manufacturing_ready():
    """Every golden ref is now placed and every net matches, and the board is
    still not manufacturable: the magnetics' physical terminals are unknown,
    placeholders remain, and there is no ERC or PCB."""
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["subset_ok"] is True
    assert res["not_placed"] == []
    assert res["readiness"] == "PARTIAL_PASS"
    assert res["manufacturing_ready"] is False
    assert sorted(res["unchecked_magnetics"]) == sorted(mbs.MAGNETIC_UNVERIFIED)
    assert res["manufacturing_blockers"]


def test_a_matching_magnetic_is_still_not_a_verified_magnetic():
    """Correct logical nets + unknown physical terminals = unchecked.  This is
    the whole reason the exemption was replaced rather than deleted."""
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["ok"]
    assert set(res["unchecked_magnetics"]) == set(mbs.MAGNETIC_UNVERIFIED)
    assert res["manufacturing_ready"] is False


def test_unexpected_extra_placed_component_is_detected():
    export = expected_export(ALL_REFS)
    export["GHOST"] = {"1": "VOUT"}
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["subset_ok"]
    assert res["unexpected_refs"] == ["GHOST"]


def test_a_missing_peripheral_fails():
    """The 17 BOM peripherals are exactly what the gate used to be unable to
    measure.  A native export that omits one must fail the diff."""
    export = expected_export(ALL_REFS)
    del export["R7"]
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "R7", "pad": "*", "want": "peripheral present", "got": "absent"} \
        in res["missing_or_wrong"]


def test_a_miswired_peripheral_fails():
    export = expected_export(ALL_REFS)
    export["C101"]["1"] = "PGND"
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert {"ref": "C101", "pad": "1", "want": "VCC12", "got": "PGND"} \
        in res["missing_or_wrong"]


def test_a_peripheral_is_not_an_unexpected_extra_reference():
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["unexpected_refs"] == []


def test_saved_native_evidence_is_labelled_as_partial_only():
    native = json.loads((ROOT / "hardware/dcx_main/netlist_compare.json").read_text(encoding="utf-8"))
    assert native["not_placed"] == []
    assert sorted(native["unchecked_magnetics"]) == sorted(mbs.MAGNETIC_UNVERIFIED)
    assert native["manufacturing_ready"] is False
    assert native["readiness"] == "PARTIAL_PASS"


def test_an_unknown_hardware_extra_still_fails_even_with_bom_only_refs():
    native = expected_export(ALL_REFS)
    native["R7"] = {"1": "RUN", "2": "PGND"}
    native["FAKE123"] = {"1": "VIN_P"}
    result = cmn.compare(GOLDEN, native, LIBRARY)
    assert result["unexpected_refs"] == ["FAKE123"]
    assert not result["subset_ok"]
