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
    # A missing R8 now takes the rename path first, which is strictly stricter:
    # it needs the registered library device AND both DNP flags to accept it.
    with pytest.raises(ValueError, match="missing native R8"):
        mod.audit()


G1_CAPTURE = mod.ROOT / "hardware/dcx_main/g1/g1_native_inventory_raw.json"
G1_REPORT = mod.ROOT / "hardware/dcx_main/g1/g1_native_inventory_bom_gate.json"


def test_default_snapshot_still_identifies_r8_by_designator():
    d = mod.audit()
    assert d["r8_identified_by"] == "designator"
    assert d["r8_capture_designator"] == "R8"
    assert d["original_r8_in_bom"] is True and d["original_r8_in_pcb"] is True


def test_g1_capture_resolves_the_renamed_r8_to_its_double_dnp_row():
    """The applied ECO renumbers the excluded part; that must still audit."""
    d = mod.audit(G1_CAPTURE)
    assert d["native_components"] == 83
    assert d["r8_identified_by"] == "double-dnp-designator-fallback"
    assert d["r8_capture_designator"] == "R6"
    assert d["original_r8_in_bom"] is False
    assert d["original_r8_in_pcb"] is False
    assert d["snapshot_source"] == "hardware/dcx_main/g1/g1_native_inventory_raw.json"
    assert d["manufacturing_approved"] is False


def test_g1_report_reproduces_from_the_committed_capture():
    """The committed G1 report must be derivable from the committed capture.

    The default candidate keeps auditing the Nov 6 snapshot, so without this
    the G1 report could silently drift into a hand-edited artifact.
    """
    assert json.loads(G1_REPORT.read_text(encoding="utf-8")) == mod.audit(G1_CAPTURE)
    assert mod.main(["--check", "--inventory", str(G1_CAPTURE),
                     "--out", str(G1_REPORT)]) == 0


def test_a_renamed_but_populated_pullup_cannot_pass_as_r8(tmp_path):
    """Renaming must not be usable to make a live enable look DNP'd."""
    fixture = json.loads(G1_CAPTURE.read_text(encoding="utf-8"))
    r6 = next(c for c in fixture["value"]["components"] if c["ref"] == "R6")
    r6["add_into_bom"] = True
    p = tmp_path / "renamed_but_populated.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="missing native R8"):
        mod.audit(p)


def _edited_capture(tmp_path, monkeypatch, ref, updates):
    original = json.loads(mod.INVENTORY.read_text(encoding="utf-8"))
    rows = [c for c in original["value"]["components"] if c["ref"] == ref]
    assert len(rows) == 1
    rows[0].update(updates)
    path = tmp_path / "captured_native_after_gui.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mod, "INVENTORY", path)
    return mod.audit()


def test_a_real_changed_manufacturer_mpn_remains_a_failing_audited_row(
        tmp_path, monkeypatch):
    # Actual GUI changes must not raise an opaque "captured MPN shifted"
    # exception, and must not make 39 original conflicts silently become 38.
    capture = json.loads(mod.INVENTORY.read_text(encoding="utf-8"))
    row = next(r for r in capture["value"]["components"] if r["ref"] == "C10")
    replacement = dict(manufacturer_id="GRM188C71E225KE11D",
                       supplier_id="C_VERIFY_INDEPENDENTLY",
                       component={**row["component"], "name": "GRM188C71E225KE11D"},
                       value="2.2uF")
    d = _edited_capture(tmp_path, monkeypatch, "C10", replacement)
    assert d["known_mpn_and_target_rows"] == 51
    assert d["native_components"] == 83
    assert d["manufacturer_target_conflicts"] == 39
    c10 = next(x for x in d["conflicts"] if x["ref"] == "C10")
    assert c10["change_classification"] == "UNVERIFIED_NATIVE_OEM_OR_LIBRARY_CHANGE"
    assert c10["manufacturer_nominal"] is None
    assert c10["manufacturer_vs_design_target"] is None
    assert c10["manufacturer_identity_or_value_verified"] is False
    assert d["manufacturing_approved"] is False
    assert d["native_cad_modified"] is False


def test_unchanged_native_mpn_with_unexpected_supplier_code_fails_closed(
        tmp_path, monkeypatch):
    d = _edited_capture(tmp_path, monkeypatch, "C102",
                        {"supplier_id": "C_FAKE"})
    assert d["known_mpn_and_target_rows"] == 51
    assert d["manufacturer_target_conflicts"] == 40
    entry = next(x for x in d["conflicts"] if x["ref"] == "C102")
    assert entry["change_classification"] == "UNVERIFIED_NATIVE_OEM_OR_LIBRARY_CHANGE"
    assert entry["manufacturer_identity_or_value_verified"] is False


def test_r8_true_bom_and_pcb_dnp_stops_ordering_the_wrong_pullup(
        tmp_path, monkeypatch):
    d = _edited_capture(tmp_path, monkeypatch, "R8",
                        {"add_into_bom": False, "add_into_pcb": False})
    assert d["original_r8_in_bom"] is False
    assert d["original_r8_in_pcb"] is False
    assert d["manufacturer_target_conflicts"] == 38
    assert not any(x["ref"] == "R8" for x in d["conflicts"])
    assert d["known_mpn_and_target_rows"] == 51
    assert d["manufacturing_approved"] is False
    assert "R8 DNP" in d["snapshot_age_note"]


@pytest.mark.parametrize("flags", [
    {"add_into_bom": False, "add_into_pcb": True},
    {"add_into_bom": True, "add_into_pcb": False},
])
def test_partial_r8_exclusion_is_not_dnp_or_release(
        tmp_path, monkeypatch, flags):
    d = _edited_capture(tmp_path, monkeypatch, "R8", flags)
    assert d["manufacturer_target_conflicts"] == 39
    assert any(x["ref"] == "R8" for x in d["conflicts"])
    assert d["manufacturing_approved"] is False


def test_new_unapproved_oem_identity_cannot_zero_all_conflicts(
        tmp_path, monkeypatch):
    original = json.loads(mod.INVENTORY.read_text(encoding="utf-8"))
    for c in original["value"]["components"]:
        if c["ref"] in {r["ref"] for r in
                        json.loads(mod.REGISTER.read_text(encoding="utf-8"))["rows"]}:
            if c.get("manufacturer_id") in mod.KNOWN:
                c["manufacturer_id"] = "UNVERIFIED_CANDIDATE"
                c["supplier_id"] = "UNVERIFIED_SUPPLIER"
                c["component"] = {"name": "UNVERIFIED_CANDIDATE"}
    path = tmp_path / "mass_change.json"
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mod, "INVENTORY", path)
    d = mod.audit()
    assert d["known_mpn_and_target_rows"] == 51
    assert d["manufacturer_target_conflicts"] == 51
    assert all(c.get("manufacturer_identity_or_value_verified") is False
               for c in d["conflicts"])
    assert not d["manufacturing_approved"]
