"""Output loop must include outgoing rail, PGND return and contact losses."""
from __future__ import annotations
import json
import pytest

from connector_budget import DESIGN_BASIS_OHM, busbar_resistance
from output_loop_budget import (
    CANDIDATES, CURRENT_A, REFERENCE, RESULT, TEMPERATURE_C, CONTACTS_TOTAL,
    loop_resistance, report, scenario,
)


def test_both_rails_are_counted_at_100c():
    r = loop_resistance(30, 1, 15, 20)
    single = busbar_resistance(.015, .030, .001, TEMPERATURE_C)
    assert r["bar_pair_ohm"] == pytest.approx(2 * single)
    assert r["loop_ohm"] == pytest.approx(2 * single + 4 * 20e-6 + 30e-6)


def test_compact_candidate_only_conditionally_within_150uohm():
    s = scenario("compact_1mm", 30, 1, 15)
    assert s["bars_pair_uohm"] == pytest.approx(22.660, abs=.002)
    assert s["total_uohm_at_20u_joint"] == pytest.approx(132.660, abs=.002)
    assert s["loss_w_at_20u_joint"] == pytest.approx(1.3266, abs=.0001)
    assert s["drop_mv_at_20u_joint"] == pytest.approx(13.266, abs=.001)
    assert s["screen_pass_20u_joint"] is True
    assert s["screen_pass_50u_joint"] is False
    assert s["joint_limit_uohm_each"] == pytest.approx(24.335, abs=.002)


def test_thin_copper_never_sneaks_through_budget():
    s = scenario("thin_0p5mm", 20, .5, 25)
    assert not s["screen_pass_20u_joint"]
    assert s["joint_limit_uohm_each"] < 2.0


def test_invalid_geometry_and_negative_unknowns_are_rejected():
    for vals in [(0, 30, 15, 20), (30, -1, 15, 20),
                 (30, 1, 15, -1), (30, 1, 15, 20, -1)]:
        with pytest.raises(ValueError):
            loop_resistance(*vals)


def test_reference_copper_unqualified_and_result_cannot_authorize_fab():
    r = report()
    assert r["status"] == "CONCEPT_SCREEN_ONLY_NOT_FOR_FAB"
    assert r["fabrication_approved"] is False
    assert r["hardware_qualified"] is False
    assert r["reference_ampacity_qualified"] is False
    assert r["number_of_current_rails"] == 2
    assert r["total_unverified_joints"] == CONTACTS_TOTAL
    assert CURRENT_A == 100
    assert DESIGN_BASIS_OHM == pytest.approx(.00015)
    assert len(r["cases"]) == len(CANDIDATES)


def test_committed_report_matches_generator_without_fabricated_evidence():
    assert RESULT.is_file()
    assert json.loads(RESULT.read_text(encoding="utf-8")) == report()
    assert REFERENCE.is_file()
