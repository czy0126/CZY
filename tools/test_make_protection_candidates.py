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


def test_each_candidate_is_the_parent_plus_only_the_protection_additions(base_text: str) -> None:
    base_lines = base_text.splitlines()
    for case in m.CANDIDATES:
        candidate = m.build(base_text, case)
        assert strip_insertions(candidate, case) == base_lines


def test_both_primary_and_all_eight_sr_gates_are_clamped(base_text: str) -> None:
    for case in m.CANDIDATES:
        text = m.build(base_text, case)
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


def test_the_latch_is_blanked_until_soft_start_completes(base_text: str) -> None:
    """An unarmed 1.8 V threshold latches on the startup inrush.

    The first PROT-B raw proved it: V(prot)=0.998 and V(out)=1.5e-8 at the
    first saved sample, i.e. the candidate converter was dead for the whole
    window.  The set term therefore has to sit behind an arming latch that
    closes once the soft-start ramp is done.
    """
    for case, spec in m.CANDIDATES.items():
        if not spec["arming"]:
            continue
        text = m.build(base_text, case)
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


def test_the_header_marks_the_deck_unrun_and_not_hardware(base_text: str) -> None:
    for case in m.CANDIDATES:
        first = m.build(base_text, case).splitlines()[0]
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


def test_generation_is_deterministic(base_text: str) -> None:
    for case in m.CANDIDATES:
        assert m.build(base_text, case) == m.build(base_text, case)
