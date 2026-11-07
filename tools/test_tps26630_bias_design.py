"""Offline checks for the reviewable TPS26630 SR-bias power path concept."""
from __future__ import annotations

import copy
import json

import pytest

import tps26630_bias_design as d


def test_oem_package_exact_mapping_is_complete_and_unique():
    checked = d.check_files()
    assert checked["status"] == "INPUT_TABLES_CHECKED_NOT_FAB"
    assert checked["pins"] == 36
    assert checked["fabrication_approved"] is False
    assert d.EXPECTED[("U1", "1")] == "EFUSE_IN"
    assert d.EXPECTED[("U1", "2")] == "EFUSE_IN"
    assert d.EXPECTED[("U1", "5")] == "VIN_SYS"
    assert d.EXPECTED[("U1", "12")] == "SHDN"
    assert d.EXPECTED[("U1", "11")] == "FLOAT"  # open MODE latch-off
    assert d.EXPECTED[("U1", "EP")] == "PGND"


def test_ti_external_blocking_fet_source_and_drain_are_not_swapped():
    assert {d.EXPECTED[("Q1", str(i))] for i in (1, 2, 3)} == {"VIN_SYS"}
    assert {d.EXPECTED[("Q1", str(i))] for i in (5, 6, 7, 8)} == {"EFUSE_IN"}
    assert d.EXPECTED[("Q1", "4")] == "BGATE"
    assert [d.EXPECTED[("Q2", str(i))] for i in (1, 2, 3)] == [
        "DRV", "VIN_SYS", "BGATE"
    ]


def test_15v_cannot_use_internal_default_uvlo_15p6v():
    report = d.report()
    nom = report["nominal"]
    assert 11.8 < nom["uvlo_rising_v"] < 12.3
    assert 18.5 < nom["ovp_rising_v"] < 18.9
    assert 14.25 > report["sensitivity"]["uvlo_rising_range_v"][1]
    assert 15.75 < report["sensitivity"]["ovp_rising_range_v"][0]
    assert nom["divider_current_at_15v_a"] == pytest.approx(
        15 / (909e3+35.7e3+64.9e3))


def test_rilim_sizing_and_nominal_inrush_sourced_to_ti_equations():
    report = d.report()
    a = report["nominal"]
    assert a["ilim_nominal_a"] == pytest.approx(0.6)
    assert a["ramp_time_s"] == pytest.approx(6.864e-3)
    assert a["ideal_cap_charge_current_a"] == pytest.approx(
        11.1e-6 * 15 / 6.864e-3)
    assert a["energy_stored_in_bank_j"] == pytest.approx(0.00124875)
    assert 0.17 < a["efuse_avg_inrush_fet_dissipation_w"] < 0.19
    # This must NOT become a claim about the real instantaneous peak or SOA.
    assert "no inrush peak/SOA guarantee" in a["assumption"]


def test_tolerance_what_if_respects_0p6a_nominal_limit_but_is_not_qualification():
    report = d.report()
    x = report["sensitivity"]
    assert x["charging_plus_load_a"] < 0.10
    assert x["charging_plus_load_a"] > 0.05
    assert x["not_a_vendor_guaranteed_corner"] is True
    assert report["readiness"]["blocking_fet_soa_at_15v_verified"] is False
    assert report["readiness"]["oem_model_simulated"] is False
    assert report["readiness"]["fab_release"] is False


@pytest.mark.parametrize("bad", [0, float("inf"), float("nan"), -1])
def test_nonphysical_ramp_cap_never_produces_a_design(bad):
    with pytest.raises(ValueError):
        d.ramp(cap_f=bad, dvd_cap_f=22e-9, vin_v=15)


def test_current_mpn_are_concepts_not_fabrication_authorizations():
    r = d.report()
    assert r["device"] == {
        "u1": "TPS26630RGET", "q1": "CSD19537Q3T",
        "q2": "BSS138-7-F", "package": "RGE24 + thermal pad",
        "configuration": (
            "external reverse-block FET and Q2, MODE open, "
            "SHDN externally pulled low for default off"
        ),
    }
    assert r["readiness"]["no_main_power_stage_release"] is True


def test_1ms_discharge_requirement_remains_blocked_by_separate_design():
    r = d.report()
    assert r["readiness"]["discharge_redesign_completed"] is False
    assert any("R57" in b for b in r["blocking_decisions"])
    assert r["readiness"]["h1_h5_scope_complete"] is False


def test_five_divider_and_shutdown_resistors_are_orderable_not_generic_values():
    import csv
    with d.BOM.open(encoding="utf-8", newline="") as stream:
        entries = {row["ref"]: row for row in csv.DictReader(stream)}
    exact = {
        "RUV_TOP": "CRCW0603909KFKEA",
        "RUV_MID": "CRCW060335K7FKEA",
        "ROV_BOT": "CRCW060364K9FKEA",
        "R_EN_PD": "CRCW0603100KFKEA",
        "R_EN_SER": "CRCW06031K00FKEA",
    }
    assert {r: entries[r]["mpn"] for r in exact} == exact
    assert all(entries[r]["fab_qualified"] == "false" for r in exact)
    evidence = d.check_files()
    assert evidence["selected_divider_and_enable_resistors"] == 5
    assert evidence["q2_ciss_oem_max_at_vds10v_pf"] == 50


def test_oem_bss138_max_capacitance_not_typical_infineon_value():
    import csv
    with d.BOM.open(encoding="utf-8", newline="") as stream:
        entries = {row["ref"]: row for row in csv.DictReader(stream)}
    q2 = entries["Q2"]
    assert q2["mpn"] == "BSS138-7-F"
    assert q2["manufacturer"] == "Diodes Incorporated"
    assert "MAX 50pF" in q2["value"] and "@VDS10V" in q2["value"]
    assert q2["fab_qualified"] == "false"
    assert q2["source_url"] == "https://www.diodes.com/datasheet/download/BSS138.pdf"


def test_full_d1_eight_synchronous_mosfets_and_four_24624_sizing_reads_live_bom():
    import make_sr_fault_board as sr
    result = d.report()["possible_full_d1_sr_gate_drive"]
    assert result["sr_fets"] == 8
    assert result["ucc24624_drivers"] == 4
    assert result["freq_hz"] == pytest.approx(200622)
    expected_gate = 8 * sr.QG_TYP_10V * 200622
    expected_idle = 4 * sr.IVDD_RUN_MAX
    assert result["gate_charge_current_typ_a"] == pytest.approx(expected_gate)
    assert result["combined_nominal_screen_a"] == pytest.approx(
        expected_gate + expected_idle)
    assert 0.11 < result["combined_nominal_screen_a"] < 0.12
    assert 5.2 < result["ratio_of_nominal_0p6a_limit_to_screen"] < 5.4
    assert result["requires_common_ground_and_regenerable_bias_check"] is True
    assert result["not_a_worst_case_bound"] is True
