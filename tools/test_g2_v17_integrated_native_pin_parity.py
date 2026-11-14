"""Regression on an actual KiCad 10 reconstruction and unreleased magnetics."""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
PCB=G/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
PARITY=G/"g2_v17_integrated_native_pin_parity_NOT_FOR_FAB.json"

def test_149_original_network_identities_are_preserved():
    j=json.loads(PARITY.read_text("utf8"))
    assert hashlib.sha256(PCB.read_bytes()).hexdigest()==j["native_V17_kicad_sha256"]
    assert j["preserved_source_component_refs"]==149
    assert j["all_148_unchanged_footprints_identical_pin_number_and_net_multiset"]
    assert j["original_archived_pad_count"]==419
    assert j["actual_KiCad_pad_count"]==425
    assert j["J_OUT_new_per_pole_pads"]==4
    assert j["kicad_real_copper_layer_count"]==12
    assert j["copper_zone_count"]==11

def test_correct_terminal_polarity_and_missing_magnetics_hard_stop():
    j=json.loads(PARITY.read_text("utf8"))
    assert j["J_OUT_contacts_xy_mm"]["VOUT"]==[[70,78],[70,87],[70,96],[70,105]]
    assert j["J_OUT_contacts_xy_mm"]["PGND"]==[[82,78],[82,87],[82,96],[82,105]]
    assert j["missing_real_physical_magnetics"]==["CT","T1","T2","T3","T4"]
    assert not j["real_full_P1_SCH_to_PCB_netlist_parity_verified"]
    assert not j["8_contact_current_rating_and_coldplate_mount_verified"]
    assert not j["thermal_EMI_3D_and_100A_verified"]
    assert j["board_release"] is False

def test_geometry_DRC_zero_does_not_mean_netlist_complete():
    j=json.loads(PARITY.read_text("utf8"))
    assert j["native_DRC_rule_violations"]==0
    assert j["native_unconnected_items"]==9
    assert not j["OEM_manufacturing_footprints_signed"]
