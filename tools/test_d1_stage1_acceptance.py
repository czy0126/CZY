"""Stage-one first-article proof gate: reject 1-A concept as 100-A hardware.

All inputs used here are checked-in CAD, original solver/DRC receipts, and the
active stage policy. Regression tests do not create hardware or waive a stop.
"""
from __future__ import annotations

import copy
import json

import pytest

import d1_stage1_acceptance as g


def test_current_stage1_stops_at_missing_physical_evidence():
    report=g.evaluate()
    assert report["schema"]=="D1_FIRST_ARTICLE_48V_100A_16MM_ACCEPTANCE_V1"
    assert report["target"]=={
        "vin_nominal_v":48,"ratio":24,"load_class_a":100,
        "assembled_height_limit_mm":16}
    assert report["status"]=="NOT_STAGE1_DELIVERED"
    assert report["physical_hardware_delivery_approved"] is False
    assert report["power_stage_fabrication_approved"] is False
    assert len(report["missing_acceptance"])==8
    assert all(value is False for value in report["acceptance_checks"].values())
    assert all(report["hard_stop_facts"].values())
    assert report["engineering_observations"]["native_G2_connections_remaining"]==175
    assert report["engineering_observations"]["native_G2_netlist_errors"]==1


def test_mag_two_turn_flux_screen_fails_even_though_one_ampere_mesh_converged():
    r=g.evaluate()
    x=r["engineering_observations"]
    assert x["two_turn_0p92uH_121p515A_flux_T"]>x["screen_flux_limit_T"]
    assert x["three_turn_0p92uH_121p515A_flux_T"]<x["screen_flux_limit_T"]
    assert x["maxwell_1A_energy_equivalent_uH_NOT_QUALIFIED"]>x["maxwell_1A_target_uH"]
    assert r["hard_stop_facts"]["converged_trial_is_unqualified_1A_stock_ferrite"]
    assert r["acceptance_checks"]["magnetics_100C_non_linear_L_I_and_five_physical_PIN_DOT"] is False


def test_signed_bytes_for_cad_and_fem_source_bound():
    r=g.evaluate()
    assert len(r["source_hashes"])==5
    assert len(set(x["path"] for x in r["source_hashes"]))==5
    for src in r["source_hashes"]:
        import hashlib
        assert hashlib.sha256((g.ROOT/src["path"]).read_bytes()).hexdigest()==src["sha256"]


def test_g2_native_DRC_wrong_revision_not_accepted(monkeypatch):
    expected=g._read
    def wrong_board(path):
        payload=copy.deepcopy(expected(path))
        if path==g.G2:
            payload["candidate_sha256"]="a"*64
        return payload
    monkeypatch.setattr(g,"_read",wrong_board)
    with pytest.raises(ValueError,match="different revisions"):
        g.evaluate()


def test_solver_archives_tampering_blocks_acceptance(monkeypatch):
    expected=g._hash
    def wrong_checksum(path):
        if path.name.endswith(".results.zip"):
            return "0"*64
        return expected(path)
    monkeypatch.setattr(g,"_hash",wrong_checksum)
    with pytest.raises(ValueError,match="Maxwell solver source/hash mismatched"):
        g.evaluate()


def test_unapproved_hardware_cannot_be_promoted_by_cache_flags(monkeypatch):
    expected=g._read
    def forged_report(path):
        data=copy.deepcopy(expected(path))
        if path==g.G2:
            data["oem_package_added_as_real_components"]=True
            data["100a_current_carrying_and_contacts_qualified"]=True
            data["manufacturer_height_thermal_and_hot_esr_qualified"]=True
        return data
    monkeypatch.setattr(g,"_read",forged_report)
    report=g.evaluate()
    assert report["physical_hardware_delivery_approved"] is False
    assert report["power_stage_fabrication_approved"] is False
    assert not report["acceptance_checks"]["same_revision_fabrication_safety_gate"]


def test_stage_one_json_is_up_to_date_and_not_permitted_for_fab():
    report=g.evaluate()
    expected=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    assert g.OUT.read_text(encoding="utf-8")==expected
    assert not report["physical_hardware_delivery_approved"]
    assert report["status"]=="NOT_STAGE1_DELIVERED"
