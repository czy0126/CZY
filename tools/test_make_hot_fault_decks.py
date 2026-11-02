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
        assert "HOT_SS_BEFORE AVG V(ss)" in result
        assert "HOT_IPRI_AFTER MAX abs(I(Lr))" in result
        # Regenerability also protects every existing original circuit line.
        assert original.replace(m.OLD_TRAN, m.NEW_TRAN) in result.replace(
            m.FAULT + m.PROBES, "")


def test_fault_time_is_not_confused_with_saved_time_axis():
    assert "1050u 0 1060u 5" in m.FAULT
    assert "FROM=175u TO=320u" in m.PROBES
    assert "FROM=120u TO=170u" in m.PROBES
    assert "not a cold start" in m.build(m.SOURCE["48v_120a"].read_text(encoding="utf-8"), "48v_120a")
