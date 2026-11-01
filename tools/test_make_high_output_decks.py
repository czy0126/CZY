"""High-output decks are parameter-only, so the power-stage model stays identical."""
from __future__ import annotations

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
