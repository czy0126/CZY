"""High-output decks are parameter-only, so the power-stage model stays identical."""
from __future__ import annotations

import pytest

import make_high_output_decks as dh


def test_every_candidate_is_exactly_a_vin_and_load_change():
    source = dh.BASE.read_text(encoding="utf-8")
    for name, (vin, rl) in dh.CASES.items():
        candidate = dh.build(source, vin, rl)
        header, rest = candidate.split("* Source: sr_tank_dual_v33_ss_1ms_100a_phys.cir; only VIN and RL change.\n", 1)
        expected_param = f".param VIN={vin} RL={rl} LP=10u LR_TOTAL=1u CR_TOTAL=620n"
        assert rest.replace(expected_param, dh.PARAM) == source
        assert "UNRUN" in header
        assert dh.filename(name).read_text(encoding="utf-8") == candidate


def test_source_contains_the_expected_parameter_anchor_once():
    assert dh.BASE.read_text(encoding="utf-8").count(dh.PARAM) == 1
    assert len(dh.CASES) == 4


def test_the_input_power_probe_differs_from_the_candidate_only_in_the_save_block():
    """Without I(Rin) in the raw there is no input power, hence no efficiency.

    The probe must stay a *save* change: if it ever drifts into a different
    circuit, the efficiency it reports is not the candidate's efficiency.
    """
    source = dh.BASE.read_text(encoding="utf-8")
    for name, (vin, rl) in dh.PROBE_CASES.items():
        plain = dh.build(source, vin, rl)
        probe = dh.build_probe(source, vin, rl)
        plain_lines = plain.splitlines(keepends=True)
        probe_lines = probe.splitlines(keepends=True)
        ledger_block = dh.save_block(dh.LEDGER_DECK.read_text(encoding="utf-8"))
        assert dh.save_block(probe) == ledger_block
        assert len(ledger_block) > len(dh.save_block(plain))
        # Everything outside the save block is byte-identical.
        def without_block(lines):
            block = dh.save_block("".join(lines))
            start = lines.index(block[0])
            return lines[:start] + lines[start + len(block):]

        assert without_block(probe_lines) == without_block(plain_lines)
        assert dh.filename(name).read_text(encoding="utf-8") == probe


def test_the_probe_carries_the_probes_the_ledger_actually_reads():
    """A save line that omits V(vin) or I(Cout) makes the ledger fail loudly.

    That is the failure this test was written after: the first version appended
    `I(Cin) I(Rin)` to the first `.save` line only, and ``energy_ledger_100a``
    refused the raw with 18 missing probes.
    """
    source = dh.BASE.read_text(encoding="utf-8")
    for vin, rl in dh.PROBE_CASES.values():
        block = " ".join(dh.save_block(dh.build_probe(source, vin, rl)))
        for probe in ("I(Cin)", "I(Rin)", "V(vin)", "I(Cout)", "V(ocd)", "V(cs1)"):
            assert probe in block


def test_a_save_block_needs_exactly_one_directive():
    with_duplicate = ".save V(out)\n.save V(sw)\n"
    with pytest.raises(ValueError):
        dh.save_block(with_duplicate)


def test_a_probe_deck_names_a_real_candidate():
    """The probe is only meaningful if the same VIN/RL also exists as a candidate."""
    for vin, rl in dh.PROBE_CASES.values():
        assert (vin, rl) in dh.CASES.values()
