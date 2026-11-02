"""Checks only reproducible diagnostic inputs, never approves SR protection."""
from __future__ import annotations

import make_sr_fault_probes as probes


def test_srp_decks_are_regenerable_and_have_all_eight_gate_and_current_probes():
    for case in probes.CASES:
        original = probes.source(case).read_text(encoding="utf-8")
        generated = probes.destination(case).read_text(encoding="utf-8")
        assert generated == probes.build(original, case)
        for n in range(1, 5):
            for side in ("A", "B"):
                assert f".meas tran SR_{n}{side}_END FIND V(g{side.lower()}{n}) AT=319u" in generated
                assert f"SR_{n}{side}_POST_PK" in generated
                assert f"SR_{n}{side}_POST_I_PK" in generated
        assert generated.count(".meas tran SR_") == 24
        assert "UNRUN eight-SR" in generated
        assert generated.count("Sflt_hot out flt_hot ctl_hot 0 HOTFLT") == 1


def test_injection_and_power_circuit_preserved_verbatim():
    # All non-probe circuit text must be identical to the accepted parent.
    for case in probes.CASES:
        parent = probes.source(case).read_text(encoding="utf-8")
        generated = probes.destination(case).read_text(encoding="utf-8")
        core = generated.split("* UNRUN eight-SR", 1)[1]
        core = core.split("\n", 4)[4]
        core = core.replace(probes.SAVE, "", 1).replace(probes.MEAS, "", 1)
        assert core == parent
