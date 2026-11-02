"""Prove 120A transient candidates have identical cold startup/fault physics."""
from __future__ import annotations

import make_120a_transients as tr


def test_only_load_changes_in_true_cold_models():
    for name, source in tr.SOURCES.items():
        original = source.read_text(encoding="utf-8")
        generated = tr.dest(name).read_text(encoding="utf-8")
        assert generated == tr.build(original, name)
        assert generated.splitlines()[4:] == original.replace(tr.PARAM, tr.NEW).splitlines()
        assert "UNRUN" in generated.splitlines()[0]
        assert ".tran 0 8m 0 10n uic" in generated
        assert ".ic V(out)" not in "\n".join(
            x for x in generated.splitlines() if not x.startswith("*")
        )


def test_severe_overload_only_in_oc_variant():
    cold = tr.dest("cold").read_text(encoding="utf-8")
    oc = tr.dest("cold_oc").read_text(encoding="utf-8")
    assert "Sflt out flt ctl 0 SFLT" not in cold
    assert "Sflt out flt ctl 0 SFLT" in oc
    assert "OC_TRIP WHEN V(oc)=1 CROSS=1" in oc
    assert "IPRI_AFTER MAX abs(I(Lr))" in oc
    assert "0.9" not in tr.PARAM  # no arbitrary relaxed OC threshold
