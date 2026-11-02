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
LIBRARY = json.loads((ROOT / "hardware/dcx_main/library_pins.json").read_text(encoding="utf-8"))
GOLDEN = mbs.load_golden()


def expected_export(refs: list[str]) -> dict[str, dict[str, str]]:
    """The export of a board wired exactly right, derived independently of
    compare() so the test cannot agree with a bug in compare()."""
    out: dict[str, dict[str, str]] = {}
    for ref in refs:
        if ref in mbs.MAGNETIC_GAPS:
            continue
        part = mbs.device_of(ref)
        symbol_pins = {p["num"] for p in LIBRARY[part]["pins"]}
        pads: dict[str, str] = {}
        for pin, net in GOLDEN[ref].items():
            for pad in mbs.pads_for(part, pin, symbol_pins):
                pads[pad] = net
        pads.update(mbs.BONDED_PADS.get(part, {}))
        out[ref] = pads
    return out


ALL_REFS = list(GOLDEN)


def test_a_correct_board_passes():
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["ok"], res["missing_or_wrong"]
    assert res["unexpected_nets"] == []
    assert res["not_placed"] == sorted(mbs.MAGNETIC_GAPS)


def test_every_pad_of_every_golden_pin_is_counted():
    """The count is the claim 'N pads were checked'.  It has to be the number of
    pads the golden netlist expands to, not the number of parts."""
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    want = sum(len(v) for v in expected_export(ALL_REFS).values())
    bonded = sum(len(v) for v in mbs.BONDED_PADS.values())
    assert res["pads_checked"] + len(res["pads_bonded_by_design"]) == want
    assert len(res["pads_bonded_by_design"]) == bonded


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


def test_placing_a_magnetic_never_turns_the_check_red():
    """T1-T4 and CT are missing only because no symbol has the right pins.  If
    someone draws one, the board got better -- the check must not fail."""
    export = expected_export(ALL_REFS)
    export["T1"] = {"1": "PRI_A", "2": "PRI_B", "3": "SEC_A", "4": "CTAP", "5": "SEC_B"}
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert "T1" not in res["not_placed"]
    assert res["ok"]


def test_a_missing_non_magnetic_part_fails():
    export = expected_export(ALL_REFS)
    del export["QL"]
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["ok"]
    assert "QL" in res["not_placed"]
    assert {"ref": "QL", "pad": "*", "want": "part present", "got": "absent"} in res["missing_or_wrong"]


def test_partial_pass_never_means_manufacturing_ready():
    res = cmn.compare(GOLDEN, expected_export(ALL_REFS), LIBRARY)
    assert res["subset_ok"] is True
    assert res["readiness"] == "PARTIAL_PASS"
    assert res["manufacturing_ready"] is False
    assert "CT" in res["not_placed"]
    assert res["manufacturing_blockers"]


def test_placing_a_magnetic_without_pin_and_dot_evidence_is_not_a_complete_pass():
    export = expected_export(ALL_REFS)
    export["T1"] = {"1": "UNVERIFIED"}
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert res["subset_ok"]
    assert "T1" in res["unchecked_magnetics"]
    assert res["manufacturing_ready"] is False


def test_unexpected_extra_placed_component_is_detected():
    export = expected_export(ALL_REFS)
    export["GHOST"] = {"1": "VOUT"}
    res = cmn.compare(GOLDEN, export, LIBRARY)
    assert not res["subset_ok"]
    assert res["unexpected_refs"] == ["GHOST"]


def test_saved_native_evidence_is_labelled_as_partial_only():
    native = json.loads((ROOT / "hardware/dcx_main/netlist_compare.json").read_text(encoding="utf-8"))
    assert native["not_placed"] == sorted(mbs.MAGNETIC_GAPS)
    assert native["manufacturing_ready"] is False
    assert native["readiness"] == "PARTIAL_PASS"


def test_real_bom_only_additions_do_not_break_spice_subset_but_remain_unverified():
    """Adding C101/R7 to the CAD cannot be called a rogue part or a verified pad."""
    native = expected_export(ALL_REFS)
    native["R7"] = {"1": "EN", "2": "PGND"}
    native["C101"] = {"1": "VCC12", "2": "PGND"}
    result = cmn.compare(GOLDEN, native, LIBRARY)
    assert result["subset_ok"], result["unexpected_refs"]
    assert result["added_bom_only_refs"] == ["C101", "R7"]
    assert result["unverified_bom_only_refs"] == ["C101", "R7"]
    assert "C102" in result["bom_only_refs_pending_placement"]
    assert result["manufacturing_ready"] is False
    assert result["pads_checked"] == 221  # no invented checks for BOM-only parts


def test_an_unknown_hardware_extra_still_fails_even_with_bom_only_refs():
    native = expected_export(ALL_REFS)
    native["R7"] = {"1": "EN", "2": "PGND"}
    native["FAKE123"] = {"1": "VIN_P"}
    result = cmn.compare(GOLDEN, native, LIBRARY)
    assert result["unexpected_refs"] == ["FAKE123"]
    assert not result["subset_ok"]
