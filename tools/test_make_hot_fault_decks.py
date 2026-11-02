"""Fault injection is independent and must never be confused with cold-start."""
from __future__ import annotations

import make_hot_fault_decks as m


def test_two_independent_fault_decks_are_regenerable_from_same_ss_circuits():
    assert len(m.SOURCE) == 2
    for key, source in m.SOURCE.items():
        original = source.read_text(encoding="utf-8")
        result = m.destination(key).read_text(encoding="utf-8")
        assert result == m.build(original, key)
        assert result.count("Sflt_hot out flt_hot ctl_hot 0 HOTFLT") == 1
        assert result.count(m.NEW_TRAN) == 1
        assert m.OLD_TRAN not in result
        assert ".ic V(out)=1.89 V(ss)=4" in result
        # 2 ms pre-fault window: with .ic 4 V, SS only reaches ~4.485 V at 1 ms,
        # below PR #20's 4.8..5.1 V settled-state band.
        assert "0 2320u 2000u" in result
        assert "HOT_SS_BEFORE AVG V(ss)" in result
        assert "HOT_VOUT_EARLY AVG V(out)" in result
        assert "HOT_VOUT_LATE AVG V(out)" in result
        assert "HOT_IFLT_AFTER MAX I(Rflt_hot)" in result
        assert "HOT_CTRL_AFTER AVG V(ctl_hot)" in result
        assert "+ V(ctl_hot) I(Rflt_hot)" in result
        assert "HOT_IPRI_AFTER MAX abs(I(Lr))" in result
        # Regenerability also protects every existing original circuit line.
        expected = original.replace(m.OLD_TRAN, m.NEW_TRAN)
        assert expected in result.replace(
            m.FAULT + m.PROBES, "").replace(m.FAULT_SAVE, "")


def test_the_diagnostic_deck_changes_only_the_solver_and_where_it_stops():
    # PR #20 asks for a documented SOLVER_DIAGNOSTIC run before the published
    # 175..215 us peaks are trusted.  A diagnostic is only a diagnostic if the
    # circuit is untouched: every difference from the base hot-fault deck must
    # be a header comment, the .tran stop, or the .options tolerances.
    for key in m.SOURCE:
        base = m.build(m.SOURCE[key].read_text(encoding="utf-8"), key)
        diag = m.diagnostic(base, key)
        assert diag.count(m.DIAG_TRAN) == 1
        assert m.NEW_TRAN not in diag
        assert m.DIAG_OPTIONS in diag
        # The diagnostic .options line *extends* the base one as a substring,
        # so only a line-level check distinguishes them.
        assert [l for l in diag.splitlines() if l.startswith(".options")] == [m.DIAG_OPTIONS]
        # Stop on the saved axis at 220 us: the base run stalled at 296.93 us,
        # so a run that stops earlier stays out of the stall and is cheap.
        # 220 (not 215) keeps the 48 V control trip at 215.10 us inside.
        assert round(m.saved_stop_us(diag), 6) == 220.0
        # Same fault, same probes, same circuit: only the solver differs.
        stripped_diag = diag.replace(m.DIAG_TRAN, m.NEW_TRAN)
        stripped_diag = stripped_diag.replace(m.DIAG_OPTIONS, m.BASE_OPTIONS)
        assert diag.count("Sflt_hot out flt_hot ctl_hot 0 HOTFLT") == 1
        assert diag.count(m.PROBES) == 1
        assert "SOLVER_DIAGNOSTIC" in diag
        assert "not a result" in diag
        # Header prepended, body byte-identical to the base deck.
        assert stripped_diag.endswith(base)


def test_the_diagnostic_deck_does_not_replace_the_base_record():
    for key in m.SOURCE:
        assert m.diagnostic_destination(key) != m.destination(key)
        assert m.diagnostic_destination(key).name.endswith("_diag.cir")


def test_fault_time_is_not_confused_with_saved_time_axis():
    assert "2170u 0 2180u 5" in m.FAULT
    assert "FROM=175u TO=320u" in m.PROBES
    assert "FROM=120u TO=170u" in m.PROBES
    assert "not a cold start" in m.build(m.SOURCE["48v_120a"].read_text(encoding="utf-8"), "48v_120a")
