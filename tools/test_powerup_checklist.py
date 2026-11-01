"""Tests for tools/powerup_checklist.py.

The sheet's whole value is that its numbers are not retyped: these tests check the
numbers trace back to the JSON they came from, and that the committed markdown is
exactly what a fresh render produces.
"""

from __future__ import annotations

import json

import pytest

from powerup_checklist import ROOT, criteria, load, render, stages

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


def test_every_check_has_a_criterion_a_source_and_an_action(sheet):
    _, sheet_stages = sheet
    for stage in sheet_stages:
        assert stage["items"], stage["id"]
        for item in stage["items"]:
            check, criterion, source, action = item
            assert check and criterion and source and action, item


def test_the_sheet_stops_before_the_rated_matrix(sheet):
    """S4 hands off; it must not claim the rating was demonstrated."""
    _, sheet_stages = sheet
    last = sheet_stages[-1]
    assert last["id"] == "S4"
    text = " ".join(" ".join(item) for item in last["items"])
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
