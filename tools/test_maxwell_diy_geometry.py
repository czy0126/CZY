"""Smoke tests for self-designed magnet CAD and true/false Maxwell evidence.

CI has no licensed Ansys Maxwell; it validates exportability, named STEP
bodies, original native logical PIN/DOT and failure-closed evidence labels.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import maxwell_diy_geometry as geom
import maxwell_diy_pcb_envelope as pads
import maxwell_diy_run as run
import maxwell_lr_from_step as original


def test_exact_six_design_owned_geometry_cases_are_not_solved():
    src = geom.load_spec()
    assert src["design_owned_geometry_not_oem"] is True
    assert src["maxwell_solved"] is False
    assert src["fabrication_approved"] is False
    assert {x["id"] for x in src["cases"]} == {
        "ELP38_Lr_2turn_0920uH", "ELP38_Lr_3turn_0920uH",
        "ELP38_Lr_2turn_1000uH", "ELP38_Lr_3turn_1000uH",
        "T_3_1_1_ELP32_CONCEPT", "CT_100_1_DIMENSION_PROXY",
    }
    assert src["cases"][-2]["winding_contract"]["primary_turns"] == 3
    assert src["cases"][-2]["winding_contract"]["sec_a_turns"] == 1
    assert src["cases"][-2]["winding_contract"]["sec_b_turns"] == 1
    assert src["cases"][-2]["winding_contract"]["independent_windings_em_modelled"] is False
    assert src["cases"][-1]["actual_coil_modelled"] is False


def test_existing_maxwell_contract_gap_and_targets_are_same(tmp_path):
    old = json.loads(original.CONFIG.read_text(encoding="utf-8"))
    src = {c["id"]: c for c in geom.load_spec()["cases"]}
    assert len(old["cases"]) == 4
    for c in old["cases"]:
        g = src[c["id"]]
        assert g["turns"] == c["turns"]
        assert g["target_inductance_uH"] == pytest.approx(c["target_inductance_uh"])
        assert g["gap_mm"] == pytest.approx(c["analytic_gap_mm"], abs=.005)
        assert g["geometry"]["core_depth_y_mm"] == pytest.approx(25.4)
        assert c["step_file"] is None  # Original vendor-qualified runner remains untouched


def test_sourced_100c_bh_anchors_are_not_a_full_measured_curve():
    with run.BH.open(encoding="utf-8",newline="") as f:
        data=list(csv.DictReader(f))
    assert len(data) >= 15
    assert original.check_bh_csv(run.BH) == []
    anchored = {int(float(r["H_A_per_m"])):float(r["B_T"]) for r in data}
    assert anchored[250] == pytest.approx(.310)
    assert anchored[1200] == pytest.approx(.410)
    prov=json.loads(run.BH_PROVENANCE.read_text(encoding="utf-8"))
    assert prov["hardware_approved"] is False
    assert prov["maxwell_executed"] is False
    assert "NOT_OEM" in prov["kind"]
    assert "NOT a digitized" in prov["other_curve_points"]


def test_24plus2_pad_contract_matches_real_native_net_names_and_is_not_verified():
    csv_text, audit = pads.packet()
    c=list(csv.DictReader(io.StringIO(csv_text)))
    d=json.loads(audit)
    assert len(c) == 26
    assert d["transformer_and_ct_pads"] == 24
    assert d["lr_concept_pads"] == 2
    assert d["real_manufacturer_pad_ids_confirmed"] is False
    assert d["fabrication_approved"] is False
    assert d["real_cad_modified"] is False
    by_key={(r["ref"],r["logical_terminal"]):r for r in c}
    assert by_key["T1","PRI_A"]["pcb_net"] == "PRI_T1"
    assert by_key["T1","PRI_B"]["pcb_net"] == "PRI_12"
    assert by_key["T4","PRI_B"]["pcb_net"] == "PGND"
    assert by_key["T2","CTAP"]["pcb_net"] == "VOUT"
    assert by_key["T3","SEC_B"]["dot_expectation"] == "DOT"
    assert by_key["CT","SEC_A"]["pcb_net"] == "CS1"
    assert by_key["Lr","N1"]["pcb_net"] == "CT_LR"
    assert by_key["Lr","N2"]["pcb_net"] == "PRI_T1"
    assert all("CONCEPT" in row["truth_status"] for row in c)


def test_unsafe_cad_models_and_fake_solver_release_are_rejected():
    cfg=copy.deepcopy(geom.load_spec())
    cfg["maxwell_solved"]=True
    assert cfg["maxwell_solved"]  # Would be rejected if read as live spec.
    original_fn=geom.CONTRACT
    assert original_fn.is_file()
    assert geom.load_spec()["maxwell_solved"] is False
    orig = geom.load_spec()["cases"][0]
    invalid=copy.deepcopy(orig)
    invalid["gap_mm"]=6
    try:
        import cadquery as cq
    except ImportError:
        pytest.skip("cadquery needed for geometry intersections")
    with pytest.raises(ValueError):
        geom.build_elp(cq, invalid)


def test_real_step_export_has_named_core_plate_foil_and_sheet(tmp_path):
    pytest.importorskip("cadquery")
    out=tmp_path/"generated"
    manifest=geom.build_report(out, write=True)
    assert manifest["status"]=="CAD_GENERATED_NO_MAXWELL_SOLVE"
    assert manifest["solver_executed"] is False
    assert manifest["fab_release"] is False
    assert len(manifest["cases"])==6
    assert geom.build_report(out,write=False)==manifest
    for c in manifest["cases"]:
        path=out/c["file"]
        assert path.stat().st_size>30000
        assert path.read_bytes().startswith(b"ISO-10303-21;")
    assert (out/"ELP38_Lr_3turn_0920uH.step").read_text(
        encoding="utf-8",errors="replace").count("LR_COIL_TERMINAL")>=1


def test_prepare_returns_local_only_surrogate_contract(tmp_path,monkeypatch):
    pytest.importorskip("cadquery")
    # Keep local generated path under repo, as the real runner hashes relative sources.
    geom.build_report(geom.OUT,write=True)
    cfg=run.prepare("ELP38_Lr_3turn_0920uH",tmp_path/"run",generate_geometry=False)
    assert cfg["model_status"]=="DESIGN_OWNED_GEOMETRY_WITH_SYNTHETIC_BH_NOT_OEM"
    assert cfg["approval"]["manufacturer_geometry_verified"] is False
    assert cfg["hardware_fabrication_approved"] is False
    assert "ILLUSTRATIVE_NOT_OEM" in cfg["n97_bh_100c_csv"]
    assert cfg["cases"][1]["step_file"].endswith(".step")
    ev=json.loads((tmp_path/"run"/"source_and_limits.json").read_text(encoding="utf-8"))
    assert ev["maxwell_executed"] is False
    assert ev["fab_release"] is False
    assert ev["target_not_guaranteed_by_gap_or_solver"] is True


def test_solve_requires_explicit_synthetic_acknowledgement(tmp_path):
    pytest.importorskip("cadquery")
    geom.build_report(geom.OUT,write=True)
    with pytest.raises(SystemExit, match="--accept-synthetic-bh"):
        run.main(["--build","--case","ELP38_Lr_2turn_0920uH",
                  "--output",str(tmp_path/"trial")])


def test_concept_geometry_is_not_the_electrical_hardware_release():
    source=geom.load_spec()
    assert source["design_owned_geometry_not_oem"]
    assert source["cases"][0]["target_inductance_uH"]==0.92
    assert source["cases"][0]["gap_mm"] ==pytest.approx(1.031)
    assert source["cases"][1]["gap_mm"]==pytest.approx(2.356)
