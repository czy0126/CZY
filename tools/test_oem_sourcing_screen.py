"""Regression for sourced OEM capacitor and connector trade-offs, no physical approval."""
from __future__ import annotations

import copy
import csv
import json

import pytest

import oem_sourcing_screen as o


def rows():
    return {r["mpn"]: r for r in o.build()["capacitor_options"]}


def test_exact_oem_parts_and_live_requirements_are_not_guessed():
    d = o.build()
    assert d["source_count_oem_links"] >= 10
    assert d["targets"]["capacitance_min_mf"] == pytest.approx(7.05)
    assert d["targets"]["bank_cap_esr_budget_mohm"] == pytest.approx(.07)
    assert d["targets"]["bank_ripple_required_arms"] == pytest.approx(84.092907)
    assert d["targets"]["max_d1_full_assembly_height_mm"] == 16
    assert d["targets"]["max_d3_stretch_full_assembly_height_mm"] == 10
    assert set(rows()) == {
        "T530X477M006ATE004", "6SVPS470M", "6SVP470M"}
    assert not d["safety"]["fabrication_approved"]
    assert not d["safety"]["actual_bom_updated"]
    assert not d["safety"]["vendor_quotes_received"]
    assert d["safety"][
        "series_cap_bank_esr_budget_is_not_output_150uohm_loop_budget"]


def test_15_original_positions_are_only_nominal_cap_not_worst_case():
    for x in rows().values():
        assert x["min_units_by_nominal_cap_only"] == 15
        assert x["min_units_by_low_tolerance_cap"] == 19
        assert x["current_nominal_15units_cap_mf"] == pytest.approx(7.05)
        assert x["current_15units_low_tolerance_cap_mf"] == pytest.approx(5.64)
        assert x["current_15units_under_cap_bank_esr_budget"] is False


def test_low_esr_kemet_part_has_real_temperature_dependent_ripple_ratings():
    x = rows()["T530X477M006ATE004"]
    assert x["voltage_v_nominal_until_105c_oem"] == pytest.approx(6.3)
    assert x["voltage_v_at_125c_oem_or_unknown"] == pytest.approx(4.22)
    assert x["case_body_size_mm"]["manufacturer_height_max_or_unknown"] == pytest.approx(4.3)
    assert x["esr_temperature_c_from_oem_or_unspecified"] == 25
    assert x["min_units_by_ideal_equal_esr_only"] == 58
    points = x["min_units_by_ripple_at_listed_oem_temperatures"]
    assert points["45"]["min_units_ripple_only"] == 11
    assert points["85"]["min_units_ripple_only"] == 15
    assert points["125"]["min_units_ripple_only"] == 42
    assert all(a["min_units_all_simple_arithmetic_targets"] == 58
               for a in points.values())
    assert x["current_15units_ideal_equal_esr_mohm"] == pytest.approx(.266667)
    assert x["esr_and_ripple_specs_not_same_operating_point"]
    assert not x["physical_layout_and_mixed_bank_qualified"]


def test_panasonic_parts_do_not_claim_100a_bank_or_physical_height():
    x = rows()["6SVPS470M"]
    y = rows()["6SVP470M"]
    assert x["min_units_by_ideal_equal_esr_only"] == 286
    assert x["min_units_by_ripple_at_listed_oem_temperatures"]["105"][
        "min_units_ripple_only"] == 21
    assert y["min_units_by_ideal_equal_esr_only"] == 215
    assert y["min_units_by_ripple_at_listed_oem_temperatures"]["105"][
        "min_units_ripple_only"] == 20
    for item in (x, y):
        assert item["case_body_size_mm"][
            "manufacturer_height_max_or_unknown"] is None
        assert item["esr_temperature_c_from_oem_or_unspecified"] is None
        assert item["thermal_ac_and_dcbias_models_still_needed"]


def test_high_ampacity_pressfit_contact_zone_can_fail_150uohm_budget():
    connector = o.build()["connector_risk"]
    assert connector["assumed_counted_contacts_total_both_poles"] == 2
    assert connector["loop_resistance_budget_uohm_both_poles"] == 150
    low = connector["family_pressfit_contact_zone_range_cases"][
        "manufacturer_family_low_uohm_not_exact_part"]
    high = connector["family_pressfit_contact_zone_range_cases"][
        "manufacturer_family_high_uohm_not_exact_part"]
    assert low["both_poles_total_contact_uohm"] == 200
    assert low["full_two_pole_arithmetic_uohm"] == pytest.approx(236.798)
    assert high["full_two_pole_arithmetic_uohm"] == pytest.approx(436.798)
    assert not low["passes_150uohm_arithmetic_only"]
    assert not high["passes_150uohm_arithmetic_only"]
    assert connector["manufacturer_rated_current_does_not_certify_low_loop_resistance"]
    assert not connector["physical_approval"]


def test_tdk_h_250_and_h_1200_bsat_not_substituted():
    d = o.build()["magnetics"]
    assert d["elp38_i38_Amin_mm2"] == 192
    assert d["elp43_i43_Amin_mm2"] == 217
    assert d["core_sheet_Bs_100c_mT_at_H250"] == 310
    assert d["generic_n97_Bs_100c_mT_at_H1200"] == 410
    assert d["core_material_Bs_measurement_conditions_not_interchangeable"]
    assert d["raw_product_is_finished_magnetic"] is False
    assert not d["actual_100c_L_I_gap_and_24_real_physical_pads_verified"]


def test_unsafe_source_identity_and_unrealistic_numbers_are_rejected():
    x = json.loads(o.SRC.read_text(encoding="utf-8"))
    for wrong in ("http://search.kemet.com/whatever",
                  "https://malicious.example/whatever",
                  "https://user:pass@search.kemet.com/whatever"):
        bad = copy.deepcopy(x)
        bad["sources"][0]["official_url"] = wrong
        with pytest.raises(ValueError, match="official manufacturer"):
            o.validate_inputs(bad)
    for field, val in (("cap_uF", 0), ("min_cap_fraction", 1.25),
                       ("esr_mohm_at_100khz", float("nan"))):
        bad = copy.deepcopy(x)
        bad["capacitor_candidates"][0][field] = val
        with pytest.raises(ValueError, match="invalid capacitor|tolerance fraction"):
            o.validate_inputs(bad)
    bad = copy.deepcopy(x)
    bad["capacitor_candidates"][0]["layout_footprint_approved"] = True
    with pytest.raises(ValueError, match="NOT PCB signoff"):
        o.validate_inputs(bad)


def test_upstream_16mm_d1_10mm_d3_and_source_json_snapshot_stay_aligned(
        tmp_path, monkeypatch):
    current = o.build()
    assert json.loads(o.OUT.read_text(encoding="utf-8")) == current
    assert o.main(["--check"]) == 0
    # A report with fake physical release must not pass source checking.
    tampered = {**current, "safety": {
        **current["safety"], "fabrication_approved": True}}
    f = tmp_path / "fake_screen.json"
    f.write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setattr(o, "OUT", f)
    assert o.main(["--check"]) == 2


def test_ratio_helper_rejects_missing_negative_nan_inputs():
    for a, b in ((1, 0), (0, 1), (1, -1),
                 (float("nan"), 1), (float("inf"), 1)):
        with pytest.raises(ValueError):
            o.ceil_for(a, b)


def test_legacy_power_stage_candidates_handoff_is_not_stuck_at_10mm_or_2p5v():
    path = o.ROOT / "docs/D1_EXECUTION_KIT/templates/power_stage_candidate_options.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        opts = list(csv.DictReader(stream))
    kemet = next(r for r in opts if r["mpn_or_question"] ==
                 "KEMET T530X477M006ATE004")
    assert kemet["type"] == "OEM_LOW_ESR_6R3_CANDIDATE"
    assert kemet["evidence_grade"] == "EXACT_OEM_PART_SHEET"
    assert kemet["rated_voltage_v"] == "6.3"
    assert float(kemet["esr_mohm_per_part"]) == 4
    assert kemet["source_url"].startswith("https://search.kemet.com/")
    assert "current 0.07mOhm needs >=58" in kemet["review_notes"]
    for r in opts:
        if r["ref"] in {"Lr", "Cr", "Cin"}:
            assert "D1 full assembly 16" in r["max_height_mm"]
            assert "D3 stretch 10" in r["max_height_mm"]
        if r["ref"] == "Cout" and r["rated_voltage_v"] == "2.5":
            assert "LEGACY" in r["review_notes"]
