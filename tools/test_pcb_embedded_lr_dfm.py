"""Source-bound PTH/thermal bottleneck checks on real embedded PCB winding CAD.

All resistance and current-density numbers here are *analytic estimates*,
not electrical/thermal qualification. Hardware sign-off must remain false.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

import pcb_embedded_lr_dfm as d


def test_deterministic_manufacturer_dfm_and_100c_barrel_sensitivity():
    report,assumptions=d.evaluate()
    assert report["schema"]=="D1_EMBEDDED_PCB_LR_MANUFACTURABILITY_SCREEN_V1"
    assert len(report["via_plating_sensitivity"])==3
    assert [x["trial_barrel_thickness_um"] for x in report["via_plating_sensitivity"]]==[18,25,35]
    assert report["Lr_rms_at_100A_output_A"]<10
    assert report["Lr_overload_rms_A"]>11
    assert report["highest_existing_Lr_transient_peak_A"]>100
    assert report["via_count_in_series"]==2
    assert report["one_turn_pair_parallel_copper_area_mm2"]==pytest.approx(.35)
    assert report["three_turns_no_via_Pdc_100C_W"]==pytest.approx(1.939731)
    assert report["not_for_fab"] is True
    assert report["manufacturer_copper_barrel_qualified"] is False
    assert report["main_power_board_winding_integrated"] is False
    assert assumptions["manufacturer_plating_verified"] is False


def test_via_rms_current_density_and_dc_loss_high_relative_to_foil():
    r=d.evaluate()[0]
    v=r["via_plating_sensitivity"]
    assert r["pair_foil_rated_RMS_current_density_A_mm2"]>26
    assert v[0]["rated_RMS_9p45A_current_density_A_mm2"]>450
    assert v[1]["rated_RMS_9p45A_current_density_A_mm2"]>320
    assert v[2]["rated_RMS_9p45A_current_density_A_mm2"]>220
    assert all(q["current_density_vs_bilayer_foil_ratio"]>8 for q in v)
    assert v[1]["two_vias_series_Pdc_rated_W"]>0.21
    assert all(q["plating_and_thermal_unverified"] is True for q in v)
    assert v[0]["two_vias_series_Pdc_rated_W"]>v[1]["two_vias_series_Pdc_rated_W"]>v[2]["two_vias_series_Pdc_rated_W"]


def test_native_3turn_cad_geometry_is_source_locked():
    r=d.evaluate()[0]
    assert len(r["source_sha256_canonical_lf"])==4
    for name,sha in r["source_sha256_canonical_lf"].items():
        f=d.ROOT/name
        assert d.sha_lf(f)==sha
    assert hashlib.sha256(d.native.PCB.read_bytes()).hexdigest()==r["native_cad_exact_sha256"]
    assert d.native.PCB.is_file()
    assert d.native.REPORT.is_file()
    assert d.native.DRC.is_file()


def test_saved_dfm_json_and_vendor_review_csv_are_reproducible():
    body,csv_text=d.contents()
    assert d.REPORT.read_text(encoding="utf-8")==body
    assert d.RFQ.read_text(encoding="utf-8")==csv_text
    rows=list(csv.DictReader(csv_text.splitlines()))
    assert len(rows)>=12
    assert len([x for x in rows if x["item"].startswith("series_via_")])==3
    assert rows[-1]["evidence_status"]=="NOT_FOR_FAB"


def test_wrong_drill_or_stackup_cannot_sneak_through(monkeypatch,tmp_path):
    original=json.loads(d.ASSUMPTIONS.read_text(encoding="utf-8"))
    for key,val,fragment in (("assumed_finished_drill_mm",0.4,"drill"),
                             ("board_thickness_mm",2.0,"thickness")):
        cfg=json.loads(json.dumps(original))
        cfg[key]=val
        new=tmp_path/(key+".json")
        new.write_text(json.dumps(cfg),encoding="utf-8")
        monkeypatch.setattr(d,"ASSUMPTIONS",new)
        with pytest.raises(ValueError,match="(drill|length)"):
            d.evaluate()
    monkeypatch.setattr(d,"ASSUMPTIONS",d.ROOT/"design/v3/maxwell/pcb_embedded_lr_dfm_assumptions.json")


def test_unreviewed_vendor_assumptions_cannot_be_marked_true(monkeypatch,tmp_path):
    a=json.loads(d.ASSUMPTIONS.read_text(encoding="utf-8"))
    a["manufacturer_plating_verified"]=True
    f=tmp_path/"false_vendor.json"
    f.write_text(json.dumps(a),encoding="utf-8")
    monkeypatch.setattr(d,"ASSUMPTIONS",f)
    with pytest.raises(ValueError,match="self-certify"):
        d.evaluate()


def test_geometry_staleness_fails_fast(monkeypatch,tmp_path):
    f=tmp_path/"corrupted_board.kicad_pcb"
    f.write_bytes(d.native.PCB.read_bytes()+b"\n; FAKE EXTRA CAD PRIMITIVE")
    monkeypatch.setattr(d.native,"PCB",f)
    with pytest.raises(ValueError,match="stale"):
        d.evaluate()
