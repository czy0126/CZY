"""D1 real-board magnetic release: source-bound nonlinear and Z gating."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from d1_magnetic_core_release_gate import build, OUT, LR, CAT, POLICY


def test_report_is_exact_from_real_sources_and_fab_blocked():
    r = build()
    assert r == json.loads(OUT.read_text("utf8"))
    assert r["fab_release"] == "NOT_FOR_FAB"
    assert r["hardware_fab_gates"]["release_approved"] is False
    assert r["status"] == "NO_STOCK_CORE_PASSES_D1_FAULT_FLUX_AND_MECHANICAL_RESERVE"
    assert len(r["source_sha256_lf"]) == 6


def test_four_planar_transformers_are_not_the_resonant_core():
    r = build()
    t = r["transformer_T1_to_T4"]
    assert t["quantity"] == 4
    assert "EILP32" in t["original_design_core"]
    assert t["primary_turns"] == 3
    assert t["two_secondary_half_turns_each"] == 1
    assert t["original_core_Ae_mm2"] == 130
    assert t["original_gap_analytic_mm"] == pytest.approx(0.1211, abs=1e-4)
    assert t["actual_all_four_vendor_3D_terminal_DOT_verified"] is False


def test_lrs_five_catalogue_cores_fail_joint_80pct_hot_fault_and_full_height():
    r = build()
    vals = r["catalogue_eilp_candidate_screen"]
    assert len(vals) == 5
    assert not any(v["passes_joint_fault_flux_and_Z_reserve"] for v in vals)
    case = {v["id"]:v for v in vals}
    assert case["ELP38_I38"]["two_turn_B_at_max_Rfq_T"] == pytest.approx(0.2911, abs=1e-4)
    assert case["ELP38_I38"]["remaining_Z_for_TIM_coldplate_screws_mm"] == 3.51
    assert case["ELP58_I58"]["passes_0p248T_arithmetic"]
    assert not case["ELP58_I58"]["passes_assumed_2mm_remaining_Z"]


def test_two_turn_requires_fast_current_limit_or_custom_core():
    r = build()
    a = r["design_resolution_options"]["A_2turn_keep_ELP38"]
    b = r["design_resolution_options"]["B_custom_enlarged_low_Z_N97_core"]
    c = r["design_resolution_options"]["C_custom_gap_3turn"]
    assert a["need_limit_Lr_fault_peak_A_at_0p248T"] == pytest.approx(103.513, abs=.001)
    assert a["accept_before_fast_OC_measured"] is False
    assert b["min_Amin_mm2_for_2turn_0p92uH_at_121p515A"] == pytest.approx(225.391, abs=.002)
    assert b["increase_vs_stock_ELP38_Amin_percent"] > 17
    assert c["gap_analytic_mm"] > 2
    assert c["new_Cu_ac_fringe_and_gap_tolerance_FEA_required"]


def test_external_inductance_cannot_be_frozen_to_1uH_without_leakage_trim():
    r = build()
    d = r["Lr_original_design"]
    assert d["prototype_1uH_RfQ_sizing_gap_mm"] == pytest.approx(.94613, abs=.0001)
    assert d["net_external_0p92uH_gap_analytic_mm"] == pytest.approx(1.03092, abs=.0001)
    assert d["oversized_1uH_when_0p08uH_leakage_is_added_total_uH"] == 1.08
    assert d["estimated_tank_frequency_ratio_for_1p08_vs_1p00"] == pytest.approx(.96225, abs=2e-5)
    assert d["airgap_must_be_measured_after_actual_transformer_leakage"]
    assert d["tdk_gap_curve_published_for_N87_not_N97"]


def test_ct_core_remains_unqualified_even_with_small_flux():
    r = build()
    ct = r["CT_primary_current_sensing"]
    assert ct["primary_secondary_turns_ratio"] == 100
    assert ct["concept_Ae_mm2"] == pytest.approx(20.1)
    assert ct["material_MPN_3D_footprint_vendor_DOT_verified"] is False


def test_tampered_catalogue_breaks_physical_source_gate(tmp_path, monkeypatch):
    import d1_magnetic_core_release_gate as G
    cat=json.loads(CAT.read_text("utf8"))
    next(c for c in cat["cores"] if c["id"]=="ELP38_I38")["amin_mm2"]=1
    f=tmp_path/"fake.json"
    f.write_text(json.dumps(cat),encoding="utf8")
    monkeypatch.setattr(G, "CAT", f)
    with pytest.raises(ValueError,match="not the reviewed core"):
        G.build()


def test_policy_height_change_fails_closed(tmp_path,monkeypatch):
    import d1_magnetic_core_release_gate as G
    policy=json.loads(POLICY.read_text("utf8"))
    next(s for s in policy["stages"] if s["id"]=="D1_100A")["height_limit_mm"]=10
    f=tmp_path/"fakepolicy.json"
    f.write_text(json.dumps(policy),encoding="utf8")
    monkeypatch.setattr(G,"POLICY",f)
    with pytest.raises(ValueError,match="baseline changed"):
        G.build()
