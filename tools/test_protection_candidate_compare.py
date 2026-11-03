"""Tests for the PROT-02 comparison logic (no raw files required)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import make_protection_candidates as make
import protection_candidate_compare as cmp

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"


@pytest.fixture(scope="module")
def base_text() -> str:
    return BASE.read_text(encoding="utf-8")


def test_first_sustained_low_ignores_a_short_dip() -> None:
    t = np.arange(0.0, 10.0001e-6, 0.1e-6)
    y = np.full_like(t, 10.0)
    y[30:35] = 0.0          # 0.4 us dip, shorter than the 1 us hold
    y[60:] = 0.0            # real turn-off
    assert cmp.first_sustained_low(t, y, 2e-6) == pytest.approx(6.0e-6)


def test_last_high_time_ignores_nothing_and_reports_the_dip_edge() -> None:
    t = np.arange(0.0, 10.0001e-6, 0.1e-6)
    y = np.full_like(t, 10.0)
    y[30:35] = 0.0
    y[60:] = 0.0
    assert cmp.last_high_time(t, y, 2e-6) == pytest.approx(5.9e-6)


def test_all_gates_low_time_takes_the_latest_gate() -> None:
    records = {"1a": {"last_high_s": 3e-6}, "1b": {"last_high_s": 7e-6}}
    assert cmp.all_gates_low_time(records, 1e-6) == pytest.approx(7e-6)


def test_all_gates_low_time_falls_back_to_the_latch_when_no_gate_is_high() -> None:
    records = {"1a": {"last_high_s": None}, "1b": {"last_high_s": None}}
    assert cmp.all_gates_low_time(records, 2e-6) == pytest.approx(2e-6)


def test_the_trigger_is_parsed_from_the_generated_deck(base_text: str) -> None:
    a = make.build(base_text, "prot_a_oc1v")
    b = make.build(base_text, "prot_b_fast10u_1p8v")
    assert cmp.trigger_from_deck(a) == ("V(oc)", "0", 1.0)
    assert cmp.trigger_from_deck(b) == ("V(ocdf)", "V(ocm)", 1.8)


def test_a_node_pair_trigger_is_read_as_a_difference() -> None:
    d = {"V(ocdf)": np.array([1.0, 2.0]), "V(ocm)": np.array([0.0, 0.5])}
    assert np.allclose(cmp.trigger_waveform(d, "V(ocdf)", "V(ocm)"), [1.0, 1.5])
    assert np.allclose(cmp.trigger_waveform(d, "V(ocdf)", "0"), [1.0, 2.0])


def test_the_fault_network_is_unchanged_by_the_candidate() -> None:
    for case, spec in make.CANDIDATES.items():
        parent = make.PARENTS[spec["parent"]].read_text(encoding="utf-8")
        assert cmp.shared_fault_network(parent) == cmp.shared_fault_network(
            make.build(parent, case))


def test_all_ten_clamps_must_be_present(base_text: str) -> None:
    assert cmp.gate_clamps_present(make.build(base_text, "prot_a_oc1v"))
    broken = make.build(base_text, "prot_a_oc1v").replace(
        "Sgb4 gb4 sgnd inhib 0 PROT_KILL\n", "")
    assert not cmp.gate_clamps_present(broken)


def test_the_cshunt_flag_is_read_from_the_whole_options_line() -> None:
    parent = (ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.cir").read_text(
        encoding="utf-8")
    assert ".options plotwinsize=0 method=gear cshunt=1e-15\n" in parent
    assert cmp.solver_is_cshunt(parent)
    plain = BASE.read_text(encoding="utf-8")
    assert not cmp.solver_is_cshunt(plain)


def test_the_solver_shunt_is_reported_for_any_value() -> None:
    assert cmp.solver_cshunt_farads(".options cshunt=1e-15") == "1e-15"
    assert cmp.solver_cshunt_farads(".options method=gear cshunt=5e-15") == "5e-15"
    assert cmp.solver_cshunt_farads(".options plotwinsize=0") is None
    assert cmp.solver_is_cshunt(".options cshunt=2e-15")


def test_the_rail_is_named_by_the_case_not_the_deck_file() -> None:
    """A sweep deck is called d1_prot03_shunt_2f_A_CANDIDATE.cir and carries no
    rail in its name; reading the rail from the file would label 50 V as 48 V."""
    assert cmp.rail("prot_a_oc1v_50v") == "50 V"
    assert cmp.rail("prot_b_fast10u_1p8v") == "48 V"


def test_the_limits_name_the_sweep_shunt_instead_of_assuming_one_femtofarad() -> None:
    rows = cmp.limitation_rows("prot_a_oc1v_50v", "5e-15", covered=False, end_s=250.150953e-6,
                      declared_stop_s=320e-6, candidate_done=True)
    assert any("cshunt=5e-15" in row for row in rows)
    assert any("50 V" in row for row in rows)
    assert any("250.151" in row for row in rows)


def test_the_base_probe_list_does_not_ask_for_protection_nodes() -> None:
    base = cmp.base_names()
    assert "V(prot)" not in base
    assert "V(inhib)" not in base
    assert len([n for n in base if n.startswith(("V(g", "V(a", "V(b", "I(VS"))]) == 24
    assert "V(prot)" in cmp.candidate_names("V(oc)")
    assert "V(ocdf)" not in cmp.candidate_names("V(oc)")
    assert "V(ocdf)" in cmp.candidate_names("V(ocdf)")


def test_high_side_gate_is_measured_against_the_switch_node() -> None:
    gh = np.array([10.0, 20.0, 20.0])
    sw = np.array([0.0, 20.0, 24.0])
    assert np.allclose(cmp.high_side_gate(gh, sw), [10.0, 0.0, -4.0])


def test_device_names_cover_four_pairs_and_two_sides() -> None:
    keys = [cmp.device_names(p, s)["key"] for p in cmp.PAIRS for s in cmp.SIDES]
    assert len(keys) == 8
    assert len(set(keys)) == 8


def test_relative_change_is_undefined_for_a_zero_base() -> None:
    assert cmp.relative(100.0, 80.0) == pytest.approx(-0.2)
    assert cmp.relative(0.0, 80.0) is None
    assert cmp.relative(None, 80.0) is None
