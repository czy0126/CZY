"""Paired controls must change one variable each, never the power circuit."""
from __future__ import annotations

import pytest

import make_paired_protection_controls as c


def _original(case: str) -> str:
    return (c.ROOT / c.SPECS[case]).read_text(encoding="utf-8")


def test_both_control_families_are_exactly_regenerable():
    for name in c.SPECS:
        original = _original(name)
        for kind in c.KINDS:
            generated = c.destination(name, kind).read_text(encoding="utf-8")
            assert generated == c.build(original, kind), (name, kind)
            assert generated.startswith(c.HEADER[kind])
            assert generated.count("inhib 0 PROT_KILL") == 10
            assert generated.count(c.ACTIVE) + generated.count(c.INACTIVE) == 1


def test_the_vt_control_only_moves_the_switch_threshold():
    for name in c.SPECS:
        original = _original(name)
        body = c.build(original, "noclamp")[len(c.HEADER["noclamp"]):]
        assert body.replace(c.INACTIVE, c.ACTIVE, 1) == original


def test_the_threshold_control_keeps_the_switch_model_byte_identical():
    for name in c.SPECS:
        original = _original(name)
        generated = c.build(original, "thrmute")
        assert c.ACTIVE in generated
        assert c.INACTIVE not in generated
        threshold = c.TRIGGER.search(original).group(2)
        body = generated[len(c.HEADER["thrmute"]):]
        restored = c.TRIGGER.sub(
            lambda m: f"{m.group(1)}>{threshold}{m.group(3)}", body, count=1)
        assert restored == original, name


def test_control_refuses_bad_power_deck():
    sample = _original(next(iter(c.SPECS)))
    for kind in c.KINDS:
        with pytest.raises(ValueError):
            c.build(sample.replace(c.ACTIVE, ".model BAD SW(Ron=.05 Roff=1G Vt=.5)"), kind)
        with pytest.raises(ValueError):
            c.build(sample.replace("cshunt=1e-15", "cshunt=0"), kind)
        with pytest.raises(ValueError):
            c.build(sample.replace("-(1-V(prot))", ""), kind)


def test_controls_do_not_claim_protection_is_functional():
    for case in c.SPECS:
        for kind in c.KINDS:
            txt = c.destination(case, kind).read_text(encoding="utf-8")
            assert "protection is intentionally inoperative" in txt
            assert "UNRUN" in txt[:120]
