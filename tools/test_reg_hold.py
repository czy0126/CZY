"""Independent checks of the REG hold thermal bound and its datasheet anchors."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

import reg_hold


def _lines() -> list[str]:
    text = (Path(reg_hold.ROOT) / reg_hold.DATASHEET).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()]


def _after(token: str, count: int) -> list[str]:
    lines = _lines()
    index = lines.index(token)
    return lines[index + 1:index + 1 + count]


def test_the_current_anchors_come_from_the_vendored_datasheet():
    assert [float(v) for v in _after("IREGSC", 5)[2:5]] == [4.5, 9.5, 13.0]
    assert [float(v) for v in _after("IREGLIM", 5)[2:5]] == [41.0, 60.0, 95.0]
    assert reg_hold.IREG_SC_MAX_A == pytest.approx(13e-3)
    assert reg_hold.IREGLIM_MAX_A == pytest.approx(95e-3)


def test_the_thermal_numbers_come_from_the_vendored_datasheet():
    lines = _lines()
    rth = float(lines[lines.index("Junction-to-ambient thermal resistance") + 1])
    assert rth == pytest.approx(reg_hold.RTH_JA_C_PER_W)
    tj = float(lines[lines.index("Junction temperature") + 2])
    assert tj == pytest.approx(reg_hold.TJ_MAX_C)


def test_the_foldback_is_not_claimed_to_be_specified():
    data = reg_hold.analysis()["datasheet"]
    assert data["foldback_curve_specified"] is False
    assert data["ireg_sc"]["max_a"] < data["ireg_lim"]["max_a"]


def test_the_current_limit_anchor_alone_exceeds_the_junction_limit():
    anchor = reg_hold.analysis()["anchors"]["current_limit_95ma"]
    r_total = reg_hold.R_CROWBAR + reg_hold.RDS_Q41
    expected_w = ((reg_hold.VDD_NOM - reg_hold.IREGLIM_MAX_A * r_total)
                  * reg_hold.IREGLIM_MAX_A + reg_hold.VDD_NOM * reg_hold.IVDD_RUN_MAX_A)
    assert anchor["vreg_eq_v"] == pytest.approx(reg_hold.IREGLIM_MAX_A * r_total)
    assert anchor["controller_w"] == pytest.approx(expected_w)
    assert anchor["rise_k"] == pytest.approx(expected_w * reg_hold.RTH_JA_C_PER_W)
    assert anchor["tj_c"] == pytest.approx(25.0 + expected_w * reg_hold.RTH_JA_C_PER_W)
    assert anchor["tj_c"] > reg_hold.TJ_MAX_C
    assert anchor["tj_c"] > reg_hold.TJ_ABS_MAX_C


def test_the_short_circuit_anchor_would_be_acceptable_but_is_not_measured():
    anchor = reg_hold.analysis()["anchors"]["short_circuit_13ma"]
    assert anchor["controller_w"] < 0.25
    assert anchor["within_tj_max"] is True
    assert reg_hold.analysis()["decision"]["measured"] is False


def test_allowed_current_matches_a_brute_force_solve_and_falls_with_ambient():
    vdd, r_total = reg_hold.VDD_NOM, reg_hold.R_CROWBAR + reg_hold.RDS_Q41
    for ambient in (25.0, 40.0, 50.0, 70.0):
        current = reg_hold.allowed_current_a(vdd, r_total, ambient)
        assert reg_hold.thermal(current, r_total, vdd, ambient)["tj_c"] == pytest.approx(
            reg_hold.TJ_MAX_C)
        # A slightly larger current must cross the limit.
        assert reg_hold.thermal(current * 1.01, r_total, vdd, ambient)["tj_c"] > reg_hold.TJ_MAX_C
        # A slightly smaller one must stay under it.
        assert reg_hold.thermal(current * 0.99, r_total, vdd, ambient)["tj_c"] < reg_hold.TJ_MAX_C
    table = reg_hold.analysis()["allowed_continuous_current_a"]
    values = [table[key] for key in ("25", "40", "50", "70")]
    assert values == sorted(values, reverse=True)
    assert table["25"] == pytest.approx(reg_hold.allowed_current_a(vdd, r_total, 25.0))


def test_the_bench_limit_sits_between_the_idle_load_and_the_thermal_limit():
    table = reg_hold.analysis()["allowed_continuous_current_a"]
    assert reg_hold.BENCH_BIAS_LIMIT_A < table["50"]
    assert reg_hold.BENCH_BIAS_LIMIT_A > 10 * reg_hold.IVDD_RUN_MAX_A
    bench = reg_hold.analysis()["bench_bias_limit"]
    assert bench["margin_at_25_c"] > 1.4
    assert bench["margin_at_50_c"] > 1.0


def test_no_sustained_crowbar_is_approved_and_the_actions_say_why():
    decision = reg_hold.analysis()["decision"]
    assert decision["sustained_crowbar_approved"] is False
    assert "above TJ max" in decision["scenario_summary"]
    assert len(decision["required"]) >= 4
    assert any("crowbar" in item for item in decision["required"])
    assert any("bias cut" in item for item in decision["required"])


def test_the_report_carries_the_same_numbers_as_the_module():
    import make_sr_fault_board as board
    reported = board.report(board.parts())["reg_hold"]
    expected = reg_hold.analysis()
    assert reported == expected


def test_the_result_is_arithmetic_not_a_power_supply_design():
    data = reg_hold.analysis()
    assert data["open_items"]
    assert any("no hardware" in item for item in data["open_items"])
    assert math.isfinite(data["board"]["tau_s"])


def test_storage_limit_is_not_a_junction_operating_limit():
    assert reg_hold.TJ_ABS_MAX_C == 125.0
    assert reg_hold.STORAGE_MAX_C == 150.0
    data = reg_hold.analysis()
    assert data["status"] == "CONDITIONAL_SCENARIOS_NOT_15V_BOUNDS"
    assert data["bench_bias_limit"]["requires_actual_vdd_and_cc_trace"] is True
    assert data["bench_bias_limit"]["not_a_safe_current_guarantee"] is True
    assert "do not automatically" in data["bench_bias_limit"]["rule"]
