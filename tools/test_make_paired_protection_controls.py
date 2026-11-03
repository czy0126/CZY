"""Paired controls must alter only active clamp threshold, never power circuit."""
from __future__ import annotations
import pytest
import make_paired_protection_controls as c


def test_two_50v_controls_are_exactly_regenerable():
    for name, path in c.SPECS.items():
        original = (c.ROOT / path).read_text(encoding="utf-8")
        generated = c.destination(name).read_text(encoding="utf-8")
        assert generated == c.build(original)
        assert generated[len(c.HEADER):].replace(c.INACTIVE, c.ACTIVE, 1) == original
        assert generated.count("inhib 0 PROT_KILL") == 10
        assert "UNRUN" in generated[:120]
        assert "V(ocdf,ocm)>1.8" in generated if name.startswith("prot_b") else "if(V(oc)>1," in generated


def test_control_refuses_bad_power_deck():
    sample = (c.ROOT / next(iter(c.SPECS.values()))).read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        c.build(sample.replace(c.ACTIVE, ".model BAD SW(Ron=.05 Roff=1G Vt=.5)"))
    with pytest.raises(ValueError):
        c.build(sample.replace("cshunt=1e-15", "cshunt=0"))


def test_controls_do_not_claim_protection_is_functional():
    for case in c.SPECS:
        txt = c.destination(case).read_text(encoding="utf-8")
        assert "protection is intentionally inoperative" in txt
        assert txt.count(c.INACTIVE) == 1
