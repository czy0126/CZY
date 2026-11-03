"""Tests for the PROT-02 candidate deck generator.

The important invariant is not "the block exists" but "nothing else changed".
Each candidate is rebuilt from the committed parent, its header, save
continuation and protection block are removed line by line, and what remains
must equal the parent line for line.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import make_protection_candidates as m

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"
BLOCK_START = "* ---- PROT-02 candidate: independent latched gate inhibit ---------------"
BLOCK_END_PREFIX = ".model PROT_KILL"


@pytest.fixture(scope="module")
def base_text() -> str:
    return BASE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def parent_texts() -> dict[str, str]:
    return {key: path.read_text(encoding="utf-8") for key, path in m.PARENTS.items()}


def parent_for(case: str, parent_texts: dict[str, str]) -> str:
    return parent_texts[m.CANDIDATES[case]["parent"]]


def strip_insertions(candidate: str, case: str) -> list[str]:
    """Remove the header, the save continuation and the protection block."""
    lines = candidate.splitlines()
    header_lines = m.header(case).splitlines()
    assert lines[:len(header_lines)] == header_lines
    lines = lines[len(header_lines):]
    save = m.save_line(case).rstrip("\n")
    assert lines.count(save) == 1
    lines.remove(save)
    start = lines.index(BLOCK_START)
    end = next(i for i, line in enumerate(lines) if line.startswith(BLOCK_END_PREFIX))
    assert end > start
    del lines[start:end + 1]
    return lines


def test_each_candidate_is_the_parent_plus_only_the_protection_additions(
        parent_texts: dict[str, str]) -> None:
    for case in m.CANDIDATES:
        parent = parent_for(case, parent_texts)
        candidate = m.build(parent, case)
        assert strip_insertions(candidate, case) == parent.splitlines()


def test_each_candidate_is_built_on_its_declared_parent() -> None:
    for case, spec in m.CANDIDATES.items():
        assert m.parent_deck(case) == m.PARENTS[spec["parent"]]
        assert m.destination(case).parent == Path("sim/v3").resolve()
        assert m.destination(case).name == (
            f"{m.parent_deck(case).stem}_{spec['suffix']}.cir")


def test_the_50v_candidates_keep_the_parent_cshunt_option(parent_texts: dict[str, str]) -> None:
    """The 50 V base still stalls at 296.929 us; only the cshunt child finishes.

    The candidate must not silently drop or re-tune that solver option, so it
    is checked on the generated text rather than trusted from the parent.
    """
    parent = parent_texts["50v_cshunt"]
    assert "cshunt=1e-15" in parent
    for case, spec in m.CANDIDATES.items():
        if spec["parent"] != "50v_cshunt":
            continue
        text = m.build(parent, case)
        assert ".options plotwinsize=0 method=gear cshunt=1e-15\n" in text
        assert ".tran 0 2320u 2000u 5n uic\n" in text


def test_both_primary_and_all_eight_sr_gates_are_clamped(parent_texts: dict[str, str]) -> None:
    for case in m.CANDIDATES:
        text = m.build(parent_for(case, parent_texts), case)
        for node, ref in m.GATES:
            assert f"S{node} {node} {ref} inhib 0 PROT_KILL\n" in text
        assert text.count("inhib 0 PROT_KILL") == 10
        assert ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)" in text


def test_candidate_a_uses_the_existing_oc_decision_and_no_fast_filter(base_text: str) -> None:
    text = m.build(base_text, "prot_a_oc1v")
    assert "if(V(oc)>1," in text
    assert "ocdf" not in text
    assert "Bocdf" not in text


def test_candidate_b_adds_the_filtered_fast_path_only(base_text: str) -> None:
    text = m.build(base_text, "prot_b_fast10u_1p8v")
    assert "Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k\n" in text
    assert "Cocdf ocdf ocm 10n\n" in text
    assert "if(V(ocdf,ocm)>1.8," in text
    assert "V(ocdf)" in m.save_line("prot_b_fast10u_1p8v")
    assert "V(ocdf)" not in m.save_line("prot_a_oc1v")


def test_the_fast_filter_does_not_load_the_ct_burden_node(base_text: str) -> None:
    """V(ocd) is a 10 ohm burden; a series resistor there would not give 10 us."""
    text = m.build(base_text, "prot_b_fast10u_1p8v")
    assert "Rfp" not in text
    assert "Rocdf ocdf ocm 1G" in text
    # The only element between ocd and ocdf must be the behavioural source.
    assert " ocd ocdf " not in text


def test_the_two_candidates_keep_distinct_trigger_levels(base_text: str) -> None:
    a = m.build(base_text, "prot_a_oc1v")
    b = m.build(base_text, "prot_b_fast10u_1p8v")
    assert "if(V(oc)>1," in a
    assert "if(V(oc)>1.8," not in a
    assert "if(V(ocdf,ocm)>1.8," in b
    assert "if(V(ocdf,ocm)>1," not in b


def test_the_save_block_gains_the_latch_and_primary_gate_probes(base_text: str) -> None:
    for case in m.CANDIDATES:
        text = m.build(base_text, case)
        assert m.save_line(case) in text
        for node in ("V(prot)", "V(inhib)", "V(uvlo)", "V(vddp)", "V(gh)", "V(gl)"):
            assert node in m.save_line(case)


def test_the_latch_is_blanked_until_soft_start_completes(parent_texts: dict[str, str]) -> None:
    """An unarmed 1.8 V threshold latches on the startup inrush.

    The first PROT-B raw proved it: V(prot)=0.998 and V(out)=1.5e-8 at the
    first saved sample, i.e. the candidate converter was dead for the whole
    window.  The set term therefore has to sit behind an arming latch that
    closes once the soft-start ramp is done.
    """
    for case, spec in m.CANDIDATES.items():
        if not spec["arming"]:
            continue
        text = m.build(parent_for(case, parent_texts), case)
        assert "Carm arm 0 1n IC=0\n" in text
        assert f"Barm arm 0 I=if(V(ss)>{m.ARM_SS_V},-(1-V(arm))*(1n/{m.TAU_PROT}),0)\n" in text
        assert "if(V(arm)>.5,if(" in text
        assert "V(arm)" in m.save_line(case)


def test_the_unarmed_control_keeps_the_same_path_but_no_blanking(base_text: str) -> None:
    """The negative control must differ from PROT-B only by the arming latch."""
    armed = m.build(base_text, "prot_b_fast10u_1p8v")
    unarmed = m.build(base_text, "prot_b_unarmed")
    for token in ("Carm", "Rarm", "Barm", "if(V(arm)", "V(arm)"):
        assert token in armed
        assert token not in unarmed
    assert "if(V(ocdf,ocm)>1.8," in unarmed
    assert "Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k\n" in unarmed


def test_the_arming_threshold_sits_below_the_steady_soft_start_level(base_text: str) -> None:
    assert 4.5 < m.ARM_SS_V < 5.05


def test_the_header_marks_the_deck_unrun_and_not_hardware(parent_texts: dict[str, str]) -> None:
    for case in m.CANDIDATES:
        first = m.build(parent_for(case, parent_texts), case).splitlines()[0]
        assert "UNRUN" in first
        assert "NOT hardware" in first


def test_the_parent_deck_is_rejected_if_it_already_has_a_protection_block(base_text: str) -> None:
    once = m.build(base_text, "prot_a_oc1v")
    with pytest.raises(ValueError):
        m.build(once, "prot_a_oc1v")


def test_an_unknown_candidate_is_rejected(base_text: str) -> None:
    with pytest.raises(ValueError):
        m.build(base_text, "prot_c_missing")


def test_a_parent_without_a_gate_node_is_rejected(base_text: str) -> None:
    broken = base_text.replace("V(gb4)", "V(missing)").replace("gb4", "missing")
    with pytest.raises(ValueError):
        m.build(broken, "prot_a_oc1v")


def test_the_uvlo_deck_drops_its_own_bias_and_keeps_the_same_clamp() -> None:
    text = m.uvlo_deck()
    assert "Vddp vddp 0 PWL(0 12 100u 12 100.1u 0 200u 0)" in text
    assert "Sg g 0 inhib 0 PROT_KILL" in text
    assert ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)" in text
    assert ".tran 0 200u 0 10n" in text
    # The sub-circuit carries the same arming latch as the full candidates.
    assert "Vss ss 0 5" in text
    assert "Carm arm 0 1n IC=0" in text


def test_the_latch_clear_terms_drain_the_capacitor(parent_texts: dict[str, str]) -> None:
    """A B current source's positive current leaves the node.

    ``+V(node)*(1n/100n)`` drains the 1 nF latch; the negative form is positive
    feedback.  Every power-stage deck holds Vddp at 12 V, so the branch is
    never selected there -- the first restart deck was where it ran, and it
    diverged to 1e86.  Lock the sign on every generated text.
    """
    for case in m.CANDIDATES:
        text = m.build(parent_for(case, parent_texts), case)
        assert "-V(prot)*(1n/" not in text
        assert "V(prot)*(1n/" in text
    assert "-V(prot)*(1n/" not in m.uvlo_deck()
    assert "-V(prot)*(1n/" not in m.restart_deck()
    assert "-V(arm)*(1n/" not in m.restart_deck()


def test_the_restart_deck_resets_both_latches_and_keeps_the_same_clamp() -> None:
    text = m.restart_deck()
    assert "Barm arm 0 I=if(V(uvlo)>.5,V(arm)*(1n/100n)," in text
    assert "Bprot prot 0 I=if(V(uvlo)>.5,V(prot)*(1n/100n)," in text
    assert "Sg g 0 inhib 0 PROT_KILL" in text
    assert ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)" in text
    assert "Rdrv drv g 3.2" in text
    # One step per 100 ns tau diverges; the deck must keep 10 ns.
    assert ".tran 0 10600u 0 10n" in text


def test_the_restart_stimulus_has_a_pulse_inside_and_after_the_blanked_ramp() -> None:
    text = m.restart_deck()
    # Soft-start slope is the datasheet model number, not a free parameter.
    assert m.SS_RAMP_V_PER_S == 0.5e3
    assert "Vss ss 0 PWL(0 5 100u 5 101u 0 120u 0 10120u 5)" in text
    assert "2000.1u 2.5" in text      # during the ramp, must not latch
    assert "10300.1u 2.5" in text     # after 4.8 V, must latch
    # The ramp pulse is well before the arming crossing at 9.72 ms.
    assert m.RESTART_PULSE_S < m.POWER_RETURN_S + m.ARM_SS_V / m.SS_RAMP_V_PER_S
    assert m.REARM_PULSE_S > m.POWER_RETURN_S + m.ARM_SS_V / m.SS_RAMP_V_PER_S


def test_the_arming_reset_only_adds_the_uvlo_branch() -> None:
    plain = m.latch_terms()
    reset = m.latch_terms(reset_on_uvlo=True)
    assert "V(uvlo)" not in plain
    assert "if(V(uvlo)>.5,V(arm)" in reset
    assert "if(V(ss)>4.8,-(1-V(arm))*(1n/100n),0))\n" in reset


def test_generation_is_deterministic(parent_texts: dict[str, str]) -> None:
    for case in m.CANDIDATES:
        parent = parent_for(case, parent_texts)
        assert m.build(parent, case) == m.build(parent, case)
