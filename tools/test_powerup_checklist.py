"""Tests for tools/powerup_checklist.py.

The sheet's whole value is that its numbers are not retyped: these tests check the
numbers trace back to the JSON they came from, and that the committed markdown is
exactly what a fresh render produces.
"""

from __future__ import annotations

import json

import pytest

from powerup_checklist import (
    ROOT, SOURCE_TYPES, STAGE_STATES, STATES, criteria, load, render, stages,
)

MD = ROOT / "design/v3/stage_f/上电检查表.md"


@pytest.fixture(scope="module")
def sheet():
    data = load()
    return criteria(data), stages(criteria(data))


def test_the_joint_limit_is_the_one_the_budget_tool_computes(sheet):
    c, _ = sheet
    conn = json.loads((ROOT / "design/v3/bom/connector_budget.json").read_text(encoding="utf-8"))
    expected = conn["joint_limit"]["per_joint_ohm"] * 1e6
    assert c["joint_limit"] == f"{expected:.1f} µΩ"
    assert 55.0 < expected < 60.0          # 57.8 uohm, not the 50 uohm placeholder


def test_the_oc_criterion_is_the_measured_chain(sheet):
    c, _ = sheet
    ct = json.loads((ROOT / "design/v3/bom/ct_design.json").read_text(encoding="utf-8"))
    assert c["oc_pin"] == f"{ct['as_built']['oc_pin_v_at_ipk']:.3f} V"
    assert c["oc_at"] == f"{ct['measured']['i_pk_a']:.2f} A"
    assert c["trip"] == f"{ct['as_built']['trip_peak_a']:.1f} A"


def test_the_no_load_output_follows_from_the_fixed_ratio(sheet):
    """A DCX has no regulation: at 48 V in, no-load Vout is 48/24 and nothing else."""
    c, _ = sheet
    assert c["vout_nl"] == "2.00 V"


def test_the_inductor_peaks_come_from_the_saturation_study(sheet):
    """The current limit for the first limited-energy run is a design output, not a guess."""
    c, _ = sheet
    lr = json.loads((ROOT / "design/v3/bom/lr_design.json").read_text(encoding="utf-8"))
    assert c["startup_peak"] == f"{lr['peaks_a']['startup']:.1f} A"
    assert c["fault_peak"] == f"{lr['peaks_a']['fault_fast_oc_13us']:.0f} A"


FIELDS = ("check", "criterion", "source", "action", "test_state",
          "measurement_location", "source_type")


def test_every_check_has_all_seven_fields(sheet):
    _, sheet_stages = sheet
    for stage in sheet_stages:
        assert stage["items"], stage["id"]
        for row in stage["items"]:
            assert all(row.get(key) for key in FIELDS), row
            assert row["test_state"] in STATES, row
            assert row["source_type"] in SOURCE_TYPES, row


def test_each_stage_uses_only_its_declared_states(sheet):
    _, sheet_stages = sheet
    for stage in sheet_stages:
        allowed = STAGE_STATES[stage["id"]]
        for row in stage["items"]:
            assert row["test_state"] in allowed, (stage["id"], row["test_state"])


def stage_text(sheet_stages, stage_id):
    stage = next(s for s in sheet_stages if s["id"] == stage_id)
    return " ".join(row["check"] + " " + row["criterion"] + " " + row["source"]
                    for row in stage["items"])


def test_rated_current_stress_is_not_in_the_no_load_stage(sheet):
    """Issue #2: OC 0.573 V and Cr 41.4 V are 100 A numbers, not no-load ones."""
    c, sheet_stages = sheet
    text = stage_text(sheet_stages, "S3")
    for token in (c["oc_pin"], c["cr_peak"], "100 A"):
        assert token not in text, token


def test_rated_current_stress_is_owned_by_the_rated_stage(sheet):
    c, sheet_stages = sheet
    text = stage_text(sheet_stages, "S4")
    for token in (c["oc_pin"], c["cr_peak"], c["fault_peak"]):
        assert token in text, token


def test_the_low_bus_stage_separates_average_limit_from_peak(sheet):
    """0.5 A average source limit cannot be compared with the 36.1 A 48 V peak."""
    c, sheet_stages = sheet
    text = stage_text(sheet_stages, "S2")
    assert "平均" in text and "峰值" in text
    assert c["startup_peak_12v"] in text
    assert c["startup_peak"] not in text


def test_the_48v_cold_start_peak_lives_in_the_48v_stage(sheet):
    c, sheet_stages = sheet
    assert c["startup_peak"] in stage_text(sheet_stages, "S3")


def test_the_reg_criterion_is_a_chip_check_not_the_deck_pwl(sheet):
    _, sheet_stages = sheet
    s1 = next(s for s in sheet_stages if s["id"] == "S1")
    row = next(r for r in s1["items"] if "REG" in r["check"])
    assert row["source_type"] == "datasheet"
    assert "PWL" not in row["criterion"] and "150" not in row["criterion"]


def test_bias_only_does_not_claim_dynamic_sr_commutation(sheet):
    _, sheet_stages = sheet
    s1 = next(s for s in sheet_stages if s["id"] == "S1")
    row = next(r for r in s1["items"] if "门极" in r["check"])
    assert "静态" in row["criterion"]
    assert "换流" not in row["criterion"]


def test_the_bootstrap_rating_and_its_stress_are_split(sheet):
    c, sheet_stages = sheet
    s1 = next(s for s in sheet_stages if s["id"] == "S1")
    rating = next(r for r in s1["items"] if "自举二极管" in r["check"])
    assert "≥ 100 V" in rating["criterion"]
    assert c["boot_reverse"] not in rating["criterion"]
    assert c["boot_reverse"] in stage_text(sheet_stages, "S3")


def test_the_thermal_criterion_is_measured_tj_not_a_design_rth(sheet):
    _, sheet_stages = sheet
    s4 = next(s for s in sheet_stages if s["id"] == "S4")
    row = next(r for r in s4["items"] if "Tj" in r["check"])
    assert "Tj ≤" in row["criterion"]
    assert "50 K/W" in row["criterion"] and "模型假设" in row["criterion"]


def test_the_sheet_stops_before_the_rated_matrix(sheet):
    """S4 hands off; it must not claim the rating was demonstrated."""
    _, sheet_stages = sheet
    last = sheet_stages[-1]
    assert last["id"] == "S4"
    text = " ".join(" ".join(str(value) for value in row.values()) for row in last["items"])
    assert "只能由" in text and "不得用短时波形替代" in text


def test_the_checklist_matches_a_fresh_render(sheet):
    c, sheet_stages = sheet
    assert MD.read_text(encoding="utf-8") == render(sheet_stages, c)


def test_a_drifted_number_changes_the_render(sheet):
    """If the render lock could not fail, it would not be a lock."""
    c, sheet_stages = sheet
    baseline = render(sheet_stages, c)
    drifted = dict(c, joint_limit="50.0 µΩ")
    assert render(sheet_stages, drifted) != baseline
