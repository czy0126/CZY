"""Actual G1 native PCB copper must veto unsafe trial busbar drill holes."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_board_keepout as K
import g2_busbar_cad as B


def test_original_m3_violates_input_and_gate_device_keepouts():
    audit=K.report()
    assert audit["source_board"]=="dcx_main_board_g1_signal_stubs.eprj2"
    assert audit["pads_checked"]==299
    assert audit["existing_tracks_checked"]==107
    assert audit["existing_vias_checked"]==18
    old=audit["prior_unsafe_m3_trial_centres"]
    assert old["VOUT"]["nearest_known_conductor"]=={
        "kind":"pad","ref":"J_IN","net":"PGND","pin":"2"}
    assert old["VOUT"]["known_copper_gap_mm"] < 0
    assert old["PGND"]["known_copper_gap_mm"] < .75
    assert all(not x["passes_visible_native_copper_clearance_only"]
               for x in old.values())
    assert audit["m3_holes_cut_into_step_or_dxf"] is False
    assert audit["fabrication_approved"] is False


def test_relocated_candidates_are_visible_copper_only_not_holes():
    d=K.report()
    suggestions=d["alternate_positions_for_further_engineering_ONLY"]
    assert suggestions["VOUT"]["centre_mm"]==[118.5,52.2351]
    assert suggestions["PGND"]["centre_mm"]==[62.4,52.2351]
    assert all(x["passes_visible_native_copper_clearance_only"] for x in suggestions.values())
    assert all(x["known_copper_gap_mm"] >= .75 for x in suggestions.values())
    assert all(x["fab_drill_approved"] is False for x in suggestions.values())
    assert all(x["internal_layers_zones_footprints_and_insulation_qualified"] is False
               for x in suggestions.values())
    assert B.screen(1.2,20)["no_m3_holes_exported"] is True


def test_actual_native_pad_shapes_not_misread_as_zero_area_points():
    d=K.read_source()
    connector=next(p for p in d["pads"]
                   if p.get("ref")=="J_IN" and p["Net"]=="PGND")
    bb=K.pad_bbox(connector)
    assert bb[2]-bb[0] > 2.3   # Huge 94.5mil physical land
    assert bb[3]-bb[1] > 2.3
    rotated={"X":1000.,"Y":-1000.,"Rotation":90,
             "Pad":["RECT",100.,40.,0]}
    bx=K.pad_bbox(rotated)
    assert bx[3]-bx[1] > bx[2]-bx[0]
    poly=next(p for p in d["pads"] if p["Pad"][0]=="POLYGON")
    assert K.pad_bbox(poly)[2] > K.pad_bbox(poly)[0]
    with pytest.raises(ValueError):
        K.pad_bbox({"X":0,"Y":0,"Pad":["UNKNOWN",3.,4.]})


def test_readback_sha_change_blocks_stale_drill_review(tmp_path,monkeypatch):
    fake=tmp_path/"forged_native.json"
    fake.write_text("{}",encoding="utf-8")
    monkeypatch.setattr(K,"READBACK",fake)
    with pytest.raises(ValueError,match="SHA mismatch"):
        K.read_source()


def test_real_native_eprj2_bytes_must_match_readback_source(tmp_path,monkeypatch):
    assert K.BOARD.is_file()
    # Read the actual saved EasyEDA archive, not only the already-checked JSON.
    import hashlib
    actual=hashlib.sha256(K.BOARD.read_bytes()).hexdigest()
    assert actual==K.EXPECTED_BOARD_SHA256
    forged=tmp_path/"changed_board.eprj2"
    forged.write_bytes(b"corrupted native candidate")
    monkeypatch.setattr(K,"BOARD",forged)
    with pytest.raises(ValueError,match="native G1 .eprj2 SHA mismatch"):
        K.read_source()


def test_wrong_native_board_identity_in_report_is_rejected(tmp_path,monkeypatch):
    report=json.loads(K.REPORT.read_text(encoding="utf-8"))
    report["candidate"]["sha256"]="0"*64
    forged=tmp_path/"wrong_report.json"
    forged.write_text(json.dumps(report),encoding="utf-8")
    monkeypatch.setattr(K,"REPORT",forged)
    with pytest.raises(ValueError,match="Unexpected active G1 native CAD identity"):
        K.read_source()
