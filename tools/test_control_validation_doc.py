"""Tests for pcb/control_validation/控制验证板_设计与测试说明_2026-10-31.md.

Issue #2 found two kinds of defects in this plan: a PGD test that only swept a
static positive VD (which says nothing about proportional drive), and a UVLO
test that demanded REG = 11 V at VDD = 4.25 V (the datasheet's REG regulator
does not regulate below ~11 V; REG follows VDD there).  These tests make the
corrected conditions hard to lose, and require every T-test to carry an
excitation, a current limit/fault stop, and a scope port.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "pcb/control_validation/控制验证板_设计与测试说明_2026-10-31.md"


@pytest.fixture(scope="module")
def text():
    return DOC.read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n### ")
    end2 = rest.find("\n## ")
    cuts = [cut for cut in (end, end2) if cut != -1]
    return rest[: min(cuts)] if cuts else rest


def test_t3_uses_a_real_negative_vds_commutation_setup(text):
    t3 = section(text, "### T3 PGD 比例驱动（真实负 VDS / 换流条件）")
    assert "负 VDS" in t3
    assert "F-SEC" in t3
    assert "体二极管" in t3
    assert "−35 mV" in t3 and "−100 mV" in t3
    # The old test's only stimulus was a positive VD sweep; that is insufficient.
    assert "VD1 从 1.5 V 扫到 15 V" not in text


def test_t3_names_its_precondition_instead_of_claiming_a_static_sweep(text):
    t3 = section(text, "### T3 PGD 比例驱动（真实负 VDS / 换流条件）")
    assert "T7" in t3 and "前置" in t3
    assert "没有 F-SEC 电流时" in t3


def test_t6_follows_the_low_vdd_reg_pass_through(text):
    t6 = section(text, "### T6 偏置、REG 跟随与 UVLO（按 datasheet 真实工作模式）")
    assert "跟随" in t6
    assert "VREGON" in t6 and "VREGOFF" in t6
    assert "4.1–4.8 V" in t6 and "3.63–4.25 V" in t6
    assert "VDD=4.25 V 时不得要求 REG=11 V" in t6
    # The old table demanded 11 V at all three VDD points.
    assert "VDD 4.25/12/26 V 三点 | REG 11 V" not in text


def test_every_t_test_has_excitation_limit_port_and_criterion(text):
    headings = [line for line in text.splitlines() if line.startswith("### T")]
    assert len(headings) == 7, headings
    for heading in headings:
        table = section(text, heading)
        for column in ("激励", "限流", "停机", "观测端口", "通过判据"):
            assert column in table, (heading, column)


def test_common_fault_stops_cover_shoot_through_temperature_and_current(text):
    common = section(text, "### 5.0 固定夹具、测点与通用停机条件")
    for token in ("直通", "壳温", "烟雾", "切断 J1 与 J3"):
        assert token in common, token


def test_the_fixture_table_names_the_source_impedance(text):
    common = section(text, "### 5.0 固定夹具、测点与通用停机条件")
    assert "100 Ω" in common and "10 Ω" in common
    assert "10 mH" in common


def test_t7_is_the_enabling_fixture_and_stays_low_energy(text):
    t7 = section(text, "### T7 低能量开关试验")
    assert "T3 的前置夹具" in t7
    assert "≤10 A" in t7
    assert "不得接 48 V" in t7
