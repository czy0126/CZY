"""Pre-fab supplier registers are reproducible and cannot certify unknown pads."""
from __future__ import annotations
import json
import copy
import d1_sourcing_register as reg


def test_more_parallel_parts_cannot_certify_unknown_hot_esr():
    dossier = json.loads(reg.COUT_DOSSIER.read_text(encoding="utf-8"))
    enlarged = copy.deepcopy(dossier)
    enlarged["main_energy_storage"]["preliminary_parallel_bank"]["quantity"] = 100
    result = reg._verified_cout(enlarged)
    assert result["nominal_100khz_25c_esr_screen_met"] is True
    assert result["supplier_rfq_low_esr_target_met"] is False
    assert result["operating_condition_esr_evidence_status"] == "NOT_VERIFIED"
    assert result["supplier_rfq_high_voltage_target_met"] is False


def test_61_real_placeholder_references_are_covered():
    parts, _ = reg.build()
    assert parts["total_placeholder_refs"] == 61
    assert len({x["ref"] for x in parts["items"]}) == 61
    # A verified OEM identity is allowed only where the generator derives it,
    # and it never releases the footprint or the item: Cout is the only one,
    # it comes from the G2 dossier, and it stays PENDING.
    verified = [x["ref"] for x in parts["items"] if x["verified_mpn"] is not None]
    assert verified == ["Cout"]
    assert all(not x["eda_footprint_verified"] for x in parts["items"])
    assert all(x["status"].startswith("PENDING_") for x in parts["items"])


def test_every_magnetic_pin_has_vendor_fillable_physical_pad_and_dot():
    _, query = reg.build()
    assert {x["ref"] for x in query["devices"]} == {"CT","T1","T2","T3","T4"}
    assert sum(len(x["pins"]) for x in query["devices"]) == 24
    for item in query["devices"]:
        assert not item["accepted_by_engineer"]
        for term in item["pins"]:
            assert term["vendor_physical_terminal_id"] is None
            assert term["required_circuit_net"] and term["dot_convention_expected"]


def test_checked_in_supplier_requests_are_current():
    parts, query = reg.build()
    assert json.loads(reg.REG.read_text(encoding="utf-8")) == parts
    assert json.loads(reg.VENDOR.read_text(encoding="utf-8")) == query


def test_the_cout_issue_list_carries_the_endurance_limit_from_the_dossier():
    """The register must not paraphrase the OEM limit; it reads it from the
    dossier so that one change moves both."""
    parts, _ = reg.build()
    cout = next(x for x in parts["items"] if x["ref"] == "Cout")
    dossier = json.loads(reg.COUT_DOSSIER.read_text(encoding="utf-8"))
    multiple = dossier["main_energy_storage"]["series_datasheet_esr_limits"][
        "endurance_105c_rated_voltage_2000h_esr_max_multiple_of_initial"]
    issues = " ".join(cout["issues"])
    assert f"rise to {multiple:g}x initial" in issues
    assert "200 kHz" in issues and "DC-bias" in issues
