"""Vendor RFE may request engineering signoff, never assert fabrication readiness."""
from __future__ import annotations
import json,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_100a_vendor_copper_insert_rfe as R


def test_vendor_document_rebuilds_from_exact_saved_native_CAD():
    r=R.build()
    assert r==json.loads(R.OUT.read_text("utf8"))
    assert r["native_board_sha256"]==R.VIA.G.V9.sha(R.VIA.G.V9.V9)
    assert r["electrical_target"]["continuous_output_total_A"]==100
    assert r["mechanical_target"]["complete_assembly_height_limit_mm"]==16
    assert r["manufacturer_rfq_ready_to_send_for_engineering_review"]
    assert r["fabrication_files_ready_to_send"] is False
    assert r["design_and_fab_approved"] is False


def test_native_power_magnetic_terminal_coldplate_real_contacts_remain_unsigned():
    r=R.build()
    a=r["original_real_native_terminals"]
    assert len(a["CTAP"])==4
    assert len(a["SR_source_lands"])==16
    assert all(x["inside_legacy_bar"] for x in a["CTAP"])
    assert all(x["inside_legacy_bar"] for x in a["SR_source_lands"])
    assert not a["component_owned_magnetic_terminal_land"]
    assert r["native_cad_output_bar_contact_created"] is False
    assert r["vendor_signature_recorded"] is False
    assert r["actual_100a_cold_plate_test_passed"] is False
    assert r["hardware_safety_D0_10channel_shutdown_passed"] is False


def test_original_bar_violates_isolation_and_via_only_math():
    r=R.build()
    q=r["old_busbar_clearance_screen"]
    assert q["VOUT_opposite_net_vias_needing_isolation"]==1
    assert q["PGND_opposite_net_vias_needing_isolation"]==25
    v=r["why_ordinary_small_via_array_not_accepted"]
    assert v["limited_top_contact_candidate_count_VOUT"]==10
    assert v["limited_top_contact_candidate_count_PGND"]==39
    assert v["required_VOUT_at_100C_ideal_only"]==60
    assert v["required_PGND_at_100C_ideal_only"]==64


def test_missing_3d_or_thermals_cannot_be_accepted_as_fabrication(monkeypatch,tmp_path):
    fake=tmp_path/"not_a_board.eprj2"
    fake.write_text("not original CAD",encoding="utf8")
    monkeypatch.setattr(R.VIA.G.V9,"V9",fake)
    with pytest.raises(ValueError,match="V9 native source changed"):
        R.build()
