"""Regression of low-current comparison derived from real frozen D1 cold start."""
from __future__ import annotations

import re

import pytest

import poc_low_current_decks as poc


def test_four_decks_are_reproducible_from_one_golden_power_stage():
    for case, mode in poc.CASES:
        assert poc.path(case, mode).is_file()
        assert poc.path(case, mode).read_text(encoding="utf-8") == poc.deck(case, mode)
    assert poc.main if callable(poc.main) else False


@pytest.mark.parametrize("case,resistance", [("5a", ".4"), ("10a", ".2")])
def test_sr_on_off_have_identical_transformer_tank_ct_and_primary(case, resistance):
    a = poc.deck(case, "on").splitlines()
    b = poc.deck(case, "off").splitlines()
    # These lines are not redrawn for PoC; a difference invalidates the A/B test.
    components = ("Lp", "Ls", "K1", "K2", "K3", "K4", "Kct",
                  "Lr ", "Cr ", "Rbur ", "Rf ", "Cf ",
                  "Rdt ", "Rrt ", "Cbt ", "Cout ", "Rload ",
                  "Vbus ", "Vaux ")
    for line_a in a:
        if line_a.startswith(components):
            assert line_a in b, line_a
    a_param = next(x for x in a if x.startswith(".param VIN="))
    b_param = next(x for x in b if x.startswith(".param VIN="))
    assert a_param == b_param
    assert "VIN=48" in a_param
    assert f"RL=0{resistance}" in a_param
    assert all(f"Xsa{i} " in "\n".join(a) and f"Xsa{i} " in "\n".join(b)
               for i in range(1, 5))


def test_no_sr_driver_in_forced_diode_mode_and_all_eight_gates_clamped():
    d = poc.deck("5a", "off")
    active = [line for line in d.splitlines() if line and not line.startswith("*")]
    assert not any(re.match(r"^Xsr[1-4]\s", line) for line in active)
    assert "Vreg reg sgnd 0 ; SR_OFF" in d
    for i in range(1, 5):
        assert f"VCLAMP_A{i} ga{i} sgnd 0" in d
        assert f"VCLAMP_B{i} gb{i} sgnd 0" in d
        assert f"Xsa{i} " in d and f"Xsb{i} " in d
        assert f"VSa{i} " in d and f"VSb{i} " in d
    assert ".include ../../models/sr_device_v3.lib" in d
    # Keep the real calibrated MOS body diode, not an invented Schottky MPN.
    assert "DRECT" not in d


def test_sr_on_original_timing_and_fault_network_are_retained():
    d = poc.deck("10a", "on")
    assert all(f"Xsr{i} " in d for i in range(1, 5))
    assert "Vreg reg sgnd PWL(" in d
    assert "VCLAMP_" not in d
    for node in ("I(VSa1)", "I(VSb1)", "V(ga1)", "V(gb1)", "I(Lr)"):
        assert node in d
    assert "POC_GATE_A1_MAX" in d and "POC_PRIMARY_MAX" in d


@pytest.mark.parametrize("case,mode", [("5a", "bad"), ("100a", "on")])
def test_unsupported_scenarios_are_not_silently_created(case, mode):
    with pytest.raises(ValueError):
        poc.deck(case, mode)


def test_generation_fails_if_primary_design_reference_changes():
    parent = poc.PARENT.read_text(encoding="utf-8")
    tampered = parent.replace(poc.SOURCE_PARAMETERS, ".param VIN=52 RL=20m")
    with pytest.raises(ValueError, match="baseline tank"):
        poc.deck("5a", "off", tampered)


def test_manifest_never_fabricates_ltspice_or_power_on_signoff():
    report = poc.manifest()
    assert report["status"] == "MODEL_ONLY_NOT_FOR_HARDWARE"
    assert not report["config"]["power_stage_power_on_authorized"]
    assert not report["config"]["output_actual_current_verified"]
    assert not report["config"]["physical_diode_temperature_verified"]
    assert set(report["cases"]) == {
        "5a_on", "5a_off", "10a_on", "10a_off"
    }
    assert all(not c["LTspice_simulated"] for c in report["cases"].values())


def test_provenance_header_is_platform_independent_for_windows_and_linux():
    # KiCad/LTspice decks are committed with a stable POSIX source-path label.
    for case, mode in poc.CASES:
        line = poc.deck(case, mode).splitlines()[1]
        assert line == (
            "* AUTO-GENERATED from sim/v3/sr_tank_dual_v33_cold_phys.cir; "
            "NO hardware verification."
        )
        assert "\\\\" not in line
