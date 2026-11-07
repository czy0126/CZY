"""Independent checks of the T1 bias budget, not a qualification."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import bias_budget as b


def _lines(rel: str) -> list[str]:
    return [line.strip() for line in
            (Path(b.ROOT) / rel).read_text(encoding="utf-8").splitlines()]


def _floats_after(lines: list[str], token: str, count: int) -> list[float]:
    """First ``count`` bare numbers after the token line, skipping conditions."""
    index = lines.index(token)
    values: list[float] = []
    for line in lines[index + 1:index + 21]:
        try:
            values.append(float(line))
        except ValueError:
            continue
        if len(values) == count:
            break
    return values


def test_ucc24624_anchors_come_from_the_vendored_datasheet():
    lines = _lines(b.UCC_DS)
    # IVDDRUN: 0.77 / 1.1 / 1.5 mA, the max column at VVDD = 12 V only.
    assert _floats_after(lines, "IVDDRUN", 3) == pytest.approx([0.77, 1.1, 1.5])
    assert "VVDD = 12 V" in lines[lines.index("IVDDRUN") + 2]
    assert _floats_after(lines, "VREG", 3) == pytest.approx([9.9, 11, 11.9])
    assert _floats_after(lines, "VGHI", 3) == pytest.approx([9.95, 10.9, 11.68])
    assert b.VGHI_MAX_V == pytest.approx(11.68)
    assert b.VREG_MAX_V == pytest.approx(11.9)
    assert b.IVDD_RUN_MAX_A == pytest.approx(1.5e-3)


def test_bsc010n04ls6_gate_charge_and_ciss_come_from_the_vendored_datasheet():
    lines = _lines(b.FET_DS)
    assert _floats_after(lines, "Gate charge total1)", 2) == pytest.approx([67, 83])
    assert _floats_after(lines, "Ciss", 2) == pytest.approx([4600, 6000])
    assert b.QG_10V_MAX_C == pytest.approx(83e-9)
    assert b.CISS_MAX_F == pytest.approx(6000e-12)


def test_gate_charge_above_10v_is_extrapolated_upward_not_downward():
    assert b.qg_at(10.0) == pytest.approx(b.QG_10V_MAX_C)
    assert b.qg_at(11.68) > b.QG_10V_MAX_C
    # Linear in Ciss above the plateau.
    extra = b.CISS_MAX_F * 1.68
    assert b.qg_at(11.68) == pytest.approx(b.QG_10V_MAX_C + extra)


def test_the_new_branch_budget_is_larger_than_the_old_flat_10v_number():
    data = b.summary()["results"]
    assert data["per_controller_branch_a"] > data["old_flat_10v_budget_a"]
    assert data["per_controller_branch_a"] == pytest.approx(
        b.gate_current_a(b.branch(b.VDD_IN_MIN_V, 0.0, vf_v=b.D50_VF_MAX_V)["vgh_v"])
        + b.IVDD_RUN_MAX_A + b.fixed_leakage_a())


def test_the_branch_solve_is_self_consistent():
    row = b.branch(b.VDD_IN_MIN_V, 0.0, vf_v=b.D50_VF_MAX_V)
    recomputed = row["vdd_in_v"] - row["vf_v"] - row["i_total_a"] * (
        row["r59_ohm"] + row["q50_rds_ohm"])
    assert row["vdd_sr_v"] == pytest.approx(recomputed)
    assert row["vgh_v"] == pytest.approx(
        min(b.VGHI_MAX_V, row["vdd_sr_v"] - b.VREGDO_MAX_V))
    assert row["i_gate_a"] == pytest.approx(b.gate_current_a(row["vgh_v"]))


def test_worst_case_regulation_fails_only_by_the_unvendored_diode_drop():
    s = b.summary()
    assert s["results"]["worst_minus_required_v"] < 0
    # The shortfall is smaller than the difference between the 1 A max Vf and a
    # conservative operating-point Vf, so vendoring the diode can close it.
    assert s["results"]["break_even_diode_vf_v"] > b.D50_VF_TYP_V
    assert s["results"]["break_even_diode_vf_v"] < b.D50_VF_MAX_V


def test_functional_gate_drive_is_never_in_question_at_the_corner():
    row = b.branch(b.VDD_IN_MIN_V, 0.0, vf_v=b.D50_VF_MAX_V)
    assert row["functional_vgs"] is True
    assert row["uvlo_margin_v"] > 0


def test_four_groups_cannot_share_one_series_resistor():
    assert b.summary()["checks"]["four_groups_shared_22r_fails_regulation"] is True
    shared = b.shared_bus_branch(b.VDD_IN_MIN_V, b.CONTROLLERS_PER_MACHINE)
    assert shared["in_regulation"] is False
    assert shared["i_total_a"] == pytest.approx(
        b.CONTROLLERS_PER_MACHINE
        * b.branch(b.VDD_IN_NOM_V, 0.0, vf_v=b.D50_VF_MAX_V)["i_total_a"])


def test_scan_covers_the_required_input_and_load_range():
    rows = b.scan()
    assert len(rows) == 3 * len(b.LOAD_SCAN_A)
    assert min(r["vdd_in_v"] for r in rows.values()) == pytest.approx(b.VDD_IN_MIN_V)
    assert max(r["vdd_in_v"] for r in rows.values()) == pytest.approx(b.VDD_IN_MAX_V)
    assert min(r["extra_load_a"] for r in rows.values()) == 0.0
    assert max(r["extra_load_a"] for r in rows.values()) == pytest.approx(0.05)


def test_the_json_on_disk_is_the_module_output_and_cannot_approve_hardware():
    data = json.loads(b.JSON_PATH.read_text(encoding="utf-8"))
    assert data == b.report()
    assert data["hardware_qualified"] is False
    assert data["measured"] is False
    assert data["decision"]["single_controller_branch_required"] is True
    assert data["decision"]["four_groups_may_not_share_one_22r"] is True
    assert data["schematic_increment"]["per_controller"] is True


def test_the_unvendored_parts_are_marked_as_such():
    data = b.report()["datasheet_anchors"]["not_vendored"]
    assert data["DMP3098L-7"]["status"] == "URL_ONLY_NOT_IN_REPO"
    assert data["ES1D-E3/61T"]["status"] == "URL_ONLY_NOT_IN_REPO"
    assert b.report()["unbound"]
