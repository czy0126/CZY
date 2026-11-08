"""Vendor-backed catalog candidate mapping still never releases BOM/hardware."""
import json
import pytest
import verified_catalog_candidates as c


def test_every_39_designator_has_a_catalog_match_or_explicit_dnp():
    d = c.report()
    assert d["source_ref_count"] == 39
    assert d["catalog_group_count"] == 13
    assert d["candidate_designators"] == 38
    assert d["must_dnp_designators"] == ["R8"]
    assert len({r["ref"] for r in d["faults"]}) == 39
    assert sum(d["catalog_group_counts"].values()) == 39


def test_no_native_bom_or_hardware_signoff_fabricated():
    d = c.report()
    assert not d["hardware_qualified"] and not d["can_fabricate"]
    assert not d["can_release_purchase_order"]
    for r in d["faults"]:
        assert not r["native_eda_modified"]
        assert not r["electrical_corner_qualified"]
        assert not r["actual_bom_reexport_verified"]
        assert not r["approved_for_procurement"]


def test_r8_default_off_is_not_a_purchase_candidate():
    r = next(x for x in c.report()["faults"] if x["ref"] == "R8")
    assert r["assembly_action"] == "MUST_DNP_REMOVE_FROM_BOM_AND_PCB"
    assert r["catalog_match_mpn"] is None


def test_reg_gate_and_kelvin_require_real_functional_check():
    rows = {r["ref"]:r for r in c.report()["faults"]}
    assert rows["C7"]["catalog_match_mpn"] == "GRM188C71E225KE11D"
    assert "DC-bias" in rows["C7"]["functional_review"]
    assert rows["R20"]["catalog_match_mpn"] == "CRCW06032R20FKEA"
    assert "pulse" in rows["R20"]["functional_review"]
    assert rows["R28"]["catalog_match_mpn"] == "CRCW06030000Z0EA"
    assert "Kelvin" in rows["R28"]["functional_review"]
    assert rows["C101"]["catalog_match_mpn"] == "C1608X7R1E105K080AB"


def test_committed_report_reproduces_source_and_enforces_total_coverage():
    assert json.loads(c.OUT.read_text(encoding="utf-8")) == c.report()
    assert c.main(["--check"]) == 0


def test_missing_target_mapping_fails_closed(monkeypatch):
    old = dict(c.CATALOG)
    old.pop("R:2.2Ω")
    monkeypatch.setattr(c, "CATALOG", old)
    with pytest.raises(ValueError, match="unmapped"):
        c.report()
