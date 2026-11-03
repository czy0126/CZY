"""Prove 120A transient candidates have identical cold startup/fault physics."""
from __future__ import annotations

import make_120a_transients as tr
from hotfault_diagnostic import circuit_differences


def test_only_load_changes_in_true_cold_models():
    for name, source in tr.SOURCES.items():
        original = source.read_text(encoding="utf-8")
        generated = tr.dest(name).read_text(encoding="utf-8")
        assert generated == tr.build(original, name)
        assert generated.splitlines()[len(tr.note(name).splitlines()):] == \
            original.replace(tr.PARAM, tr.NEW).splitlines()
        assert "UNRUN" in generated.splitlines()[0]
        assert ".tran 0 8m 0 10n uic" in generated
        assert ".ic V(out)" not in "\n".join(
            x for x in generated.splitlines() if not x.startswith("*")
        )


def test_the_fault_note_restates_severity_for_the_15p4m_load():
    """The inherited block says 1.818 mOhm / 11x -- true for its 20 mOhm parent.

    This candidate's RL is 15.4 mOhm, so the same 2 mOhm branch (Ron 1m +
    Rflt 1m) is 1.770 mOhm, i.e. 8.7x.  Reading the parent's number next to
    RL=15.4m would overstate the fault by 25 %.
    """
    cold_oc = tr.build(tr.SOURCES["cold_oc"].read_text(encoding="utf-8"), "cold_oc")
    assert "1.770 mOhm = 8.7x" in cold_oc
    cold = tr.build(tr.SOURCES["cold"].read_text(encoding="utf-8"), "cold")
    assert "1.770 mOhm" not in cold


def test_severe_overload_only_in_oc_variant():
    cold = tr.dest("cold").read_text(encoding="utf-8")
    oc = tr.dest("cold_oc").read_text(encoding="utf-8")
    assert "Sflt out flt ctl 0 SFLT" not in cold
    assert "Sflt out flt ctl 0 SFLT" in oc
    assert "OC_TRIP WHEN V(oc)=1 CROSS=1" in oc
    assert "IPRI_AFTER MAX abs(I(Lr))" in oc
    assert "0.9" not in tr.PARAM  # no arbitrary relaxed OC threshold


def test_the_cshunt_control_changes_only_a_solver_option():
    """The aid must be comparable: comments and .options may differ, nothing else.

    ``circuit_differences`` strips comments, .tran and .options, so an empty
    result is the statement that the 8 ms fault circuit is unchanged.  If a
    future edit drops or reorders a device, this test goes red rather than
    letting the comparison mix a circuit change into a numerical one.
    """
    base = tr.dest("cold_oc").read_text(encoding="utf-8")
    variant = tr.cshunt_dest("cold_oc").read_text(encoding="utf-8")
    assert variant == tr.cshunt_variant(base)
    assert tr.CSHUNT_OPTIONS in variant
    assert "cshunt=1e-15" in variant
    assert circuit_differences(base, variant) == []
    assert ".tran 0 8m 0 10n uic" in variant
    assert "Sflt out flt ctl 0 SFLT" in variant
    # The control stays a control: it is never generated for the clean cold start.
    assert not tr.cshunt_dest("cold").exists()
