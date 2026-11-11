"""Reject low-profile 100A busbar and Cout claims without actual model qualification.

Tested against the saved/reopened G1 107-line board's frozen source records,
without changing the .eprj2. These are actual manufacturable-style trial
outlines and STEP solids, NOT fabricated/verified electrical connections.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_busbar_cad as B


def test_two_actual_source_rail_polygons_and_trial_holes():
    r=B.load()
    out=B.outlines(r)
    centers=B.centres(r)
    assert set(out)=={"VOUT","PGND"}
    assert r["candidate"]["sha256"]==B.BOARD_SHA
    assert len(out["VOUT"])==len(out["PGND"])==8
    assert centers["VOUT"][0]==pytest.approx(112.9995)
    assert centers["PGND"][0]==pytest.approx(61.3994)
    for n in out:
        assert B.is_inside(centers[n],out[n])
        assert 0<=B.bbox(out[n])[0] and B.bbox(out[n])[2]<=155
        assert 0<=B.bbox(out[n])[1] and B.bbox(out[n])[3]<=131
    assert centers["VOUT"][0]-centers["PGND"][0]==pytest.approx(51.6001)


def test_5mm_arithmetic_pass_but_reject_excess_16mm_height():
    d=B.screen(5,50)
    assert d["calculated_both_pole_uohm"]==pytest.approx(147.529)
    assert d["height_without_TIM_clamp_holes_mm"]==pytest.approx(19.25)
    assert d["height_margin_without_TIM_clamp_mm"]==pytest.approx(-3.25)
    assert not d["height_arithmetic_only_pass"]
    assert d["resistance_arithmetic_only_pass"]
    assert d["fab_approved"] is False


def test_1p2mm_contact_resistance_is_the_relevant_trade():
    low=B.screen(1.2,20)
    high=B.screen(1.2,50)
    assert low["height_without_TIM_clamp_holes_mm"]==pytest.approx(15.45)
    assert low["height_margin_without_TIM_clamp_mm"]==pytest.approx(.55)
    assert low["calculated_both_pole_uohm"]==pytest.approx(121.511)
    assert high["calculated_both_pole_uohm"]==pytest.approx(181.511)
    assert low["resistance_arithmetic_only_pass"]
    assert not high["resistance_arithmetic_only_pass"]
    assert low["no_source_land_to_bar_interconnect_model"]
    assert low["TIM_and_clamp_and_standoff_tolerances_excluded"]
    assert not low["native_cad_modified"] and not low["fab_approved"]


def test_reject_nonsensical_joint_geometry():
    with pytest.raises(ValueError):
        B.screen(-1,20)
    with pytest.raises(ValueError):
        B.screen(1.2,-1)


def test_correct_primary_polymer_4mF_0p2mohm_bank_and_optional_hot_mlcc():
    d=json.loads((ROOT/"hardware/dcx_main/g2/cout_oem_candidate.json").read_text(encoding="utf-8"))
    assert d["schema"]=="d1_g2_cout_oem_candidate/2"
    assert d["design_basis"]["min_bank_capacitance_uF_nominal_model"]==4000
    assert d["design_basis"]["target_bank_esr_mohm_nominal_model"]==0.2
    main=d["main_energy_storage"]
    assert main["exact_mpn"]=="A720V477M2R5APE003"
    assert main["rated"]["capacitance_uF"]==470
    assert main["rated"]["rated_voltage_v"]==2.5
    assert main["rated"]["temp_range_c"][1]==105
    assert main["preliminary_parallel_bank"]["quantity"]==15
    assert main["preliminary_parallel_bank"]["nominal_capacitance_uF"]==7050
    assert main["preliminary_parallel_bank"]["capacitance_min_from_initial_tolerance_uF"]==5640
    assert main["preliminary_parallel_bank"]["ideal_esr_mohm_at_100khz_25c"]==pytest.approx(3/15)
    assert main["preliminary_parallel_bank"]["copper_spreading_and_rms_share_verified"] is False
    extra=d["optional_high_frequency_bypass"]
    assert extra["exact_mpn"]=="GRM32EE70J107ME15L"
    assert extra["rated"]["temp_range_c"][1]==125
    assert extra["effective_uF_at_2v"] is None
    assert extra["quantity"].startswith("NOT_FROZEN")
    assert "BELOW the 4mF main Cout requirement" in extra["note"]
    assert d["current_native_G1"]["actual_device_count"]==1
    assert d["gates"]["actual_15_polymer_devices_in_native_CAD"] is False
    assert d["gates"]["manufacturing_approved"] is False
