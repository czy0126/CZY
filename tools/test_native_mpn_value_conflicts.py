"""Regression: native part number physical value is not its edited display."""
import json
import native_mpn_value_conflicts as audit


def test_39_differences_include_37_claimed_value_conforming():
    d = audit.report()
    assert d["known_rows"] == 51
    assert d["mismatch_count"] == 39
    assert d["previously_falsely_value_conforming"] == 37
    assert d["known_exact_match_count"] == 12
    refs = {r["ref"] for r in d["rows"]}
    assert {"C7", "C8", "C9", "C10", "R28", "R35"}.issubset(refs)


def test_reg_and_kelvin_candidates_are_not_native_fixes():
    d = audit.report()
    c = next(r for r in d["rows"] if r["ref"] == "C7")
    r = next(r for r in d["rows"] if r["ref"] == "R28")
    assert (c["native_physical_value"],c["schematic_target"]) == ("100nF","2.2uF")
    assert (r["native_physical_value"],r["schematic_target"]) == ("10kΩ","0Ω")
    assert c["candidate"] == "GRM188C71E225KE11D"
    assert r["candidate"] == "CRCW06030000Z0EA"
    assert not c["approval"] and not r["approval"]
    assert not d["native_eda_modified"] and not d["hardware_qualified"]
    assert not d["fabrication_approved"] and not d["physical_parts_ordered"]


def test_committed_full_per_ref_report_matches_current_source():
    assert json.loads(audit.OUTPUT.read_text(encoding="utf-8")) == audit.report()
