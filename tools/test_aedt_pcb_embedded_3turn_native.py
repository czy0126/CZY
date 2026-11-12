"""Bind REAL Ansys Maxwell3D to accepted R0.8 3turn/6layer KiCad copper.

The native AEDT file was actually created and read back on the Windows
workstation; these tests reject stale snapshots and fake material/fab claims.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
BASE="ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_GEOMETRY_NOT_FOR_FAB"
BASEPATH=ROOT/"hardware/dcx_main/maxwell"
AEDT=BASEPATH/(BASE+".aedt")
RECEIPT=BASEPATH/(BASE+".evidence.json")
REOPEN=BASEPATH/"ELP38_Lr_PCB_EMBEDDED_3TURN_6LAYER_4PTH_NATIVE_REOPEN_NOT_FOR_FAB.json"
CONFIG=ROOT/"design/v3/maxwell/pcb_embedded_lr_3turn_rounded_slots_4via_trial.json"
CORE=ROOT/"design/v3/maxwell/diy_magnetics_concept.json"
KICAD=ROOT/"hardware/dcx_main/pcb_winding/ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb"
SCRIPT=ROOT/"tools/aedt_pcb_embedded_3turn_native.py"

def sha(path,normalized=False):
    payload=path.read_bytes()
    if normalized:payload=payload.replace(b"\r\n",b"\n")
    return hashlib.sha256(payload).hexdigest()

def test_real_AEDT_reopened_native_3turn_model_and_sha_match():
    receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))
    reopened=json.loads(REOPEN.read_text(encoding="utf-8"))
    assert AEDT.stat().st_size>100000
    assert receipt["status"]=="REAL_6LAYER_PCB_WINDING_SOLIDS_SAVED_NOT_SOLVED_NOT_FOR_FAB"
    assert reopened["status"]=="REAL_NATIVE_3TURN_PCB_MAXWELL_CAD_REOPENED_GEOMETRY_ONLY_NOT_FOR_FAB"
    assert receipt["native_project_sha256"]==sha(AEDT)
    assert reopened["native_project_sha256_before"]==sha(AEDT)
    assert reopened["native_project_sha256_after"]==sha(AEDT)
    assert reopened["read_only_file_preserved"] is True
    assert reopened["native_3turn_one_copper_body_reopened"] is True
    assert set(reopened["native_reopened_solids"])=={
        "I38_GENERIC_FERRITE","E_BACK","PCB_LR_CU_000","Region"}
    assert reopened["single_multilayer_copper_solid_face_count"]>100

def test_geometry_reconstructed_from_real_kiCAD_layers_and_holes_not_rings():
    receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["actual_kicad_segments"]==46
    assert receipt["real_kicad_transition_PTH"]==8
    assert receipt["real_kicad_external_terminals"]==2
    assert receipt["kicad_layer_and_copper_boxes"]==46
    assert receipt["hollow_plated_pth_solid_count"]==10
    assert receipt["copper_before_unite"]==58
    assert receipt["three_series_turns_one_copper_solid"] is True
    assert receipt["source_kicad_lf_sha256"]==sha(KICAD,True)
    assert receipt["source_rounded_config_lf_sha256"]==sha(CONFIG,True)
    assert receipt["source_core_contract_lf_sha256"]==sha(CORE,True)
    assert receipt["source_script_lf_sha256"]==sha(SCRIPT,True)

def test_not_real_BH_or_100A_or_fabrication():
    receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))
    reopened=json.loads(REOPEN.read_text(encoding="utf-8"))
    for k in ("mesh_solved","bias_1a_solved","real_N97_100c_nonlinear_BH_applied",
              "real_100A_L_I_verified","200kHz_AC_loss_verified",
              "ferrite_core_mechanical_approved",
              "plated_through_hole_25um_manufacturer_verified",
              "16mm_assembly_qualified","fabrication_approved"):
        assert receipt[k] is False
    assert reopened["L_I_solved"] is False
    assert reopened["fabrication_approved"] is False
    assert any("rounded slot arcs are NOT yet modeled" in q for q in receipt["warnings"])
    assert "ferrite" in SCRIPT.read_text(encoding="utf-8")
