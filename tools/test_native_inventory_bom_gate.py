"""Native BOM release stopline uses REAL captured manufacturer and supplier fields."""
import json
import pytest
import native_inventory_bom_gate as mod


def test_real_captured_manufacturer_codes_expose_39_physical_bom_errors():
    d = mod.audit()
    assert d["native_components"] == 83
    assert d["register_placeholder_rows"] == 61
    assert d["known_mpn_and_target_rows"] == 51
    assert d["manufacturer_target_conflicts"] == 39
    assert d["native_display_vs_manufacturer_conflicts"] == 37
    assert d["display_not_yet_at_design_target"] == 2
    assert {x["ref"] for x in d["conflicts"] if x["display_vs_design_target"]} == {"C5", "R3"}


def test_real_captured_r8_was_not_saved_as_native_dnp():
    d = mod.audit()
    assert d["original_r8_in_bom"] is True
    assert d["original_r8_in_pcb"] is True
    assert d["manufacturing_approved"] is False
    assert d["native_cad_modified"] is False


def test_gating_uses_verified_physical_mpn_and_lcsc_code():
    d = mod.audit()
    c10 = next(x for x in d["conflicts"] if x["ref"] == "C10")
    r20 = next(x for x in d["conflicts"] if x["ref"] == "R20")
    assert (c10["native_manufacturer_id"], c10["native_supplier_id"],
            c10["manufacturer_nominal"]) == ("CL10B104KB8NNNC","C1591","100nF")
    assert (r20["native_manufacturer_id"],r20["native_supplier_id"],
            r20["manufacturer_nominal"]) == ("0603WAF1002T5E","C25804","10kΩ")
    assert r20["actual_native_display"] == "2.2Ω"


def test_snapshot_is_reproducible_and_release_remains_blocked():
    assert json.loads(mod.OUTPUT.read_text(encoding="utf-8")) == mod.audit()
    assert mod.main(["--check"]) == 0
    assert mod.main(["--release-check"]) == 2


def test_missing_protected_native_ref_fails_closed(tmp_path, monkeypatch):
    fixture = json.loads(mod.INVENTORY.read_text(encoding="utf-8"))
    fixture["value"]["components"] = [x for x in fixture["value"]["components"]
                                       if x["ref"] != "R8"]
    fixture["value"]["primitive_count"] -= 1
    p = tmp_path / "native.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")
    monkeypatch.setattr(mod, "INVENTORY", p)
    with pytest.raises(ValueError, match="missing native refs"):
        mod.audit()
