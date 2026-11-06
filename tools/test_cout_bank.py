"""Tests for tools/cout_bank.py.

The bank is sized by the *worst* of three independent requirements, so the tests
pin the ceiling, the "which one wins" selection, and the parallel laws that make
the count valid in the first place.

The RMS requirement is the one that moves with the load, and it is quoted at the
worst measured point rather than at the rated one.  The literals below are
hard-coded on purpose: reading them back out of the tool would let the tool and
its test agree on a stale number.
"""

from __future__ import annotations

import json

import pytest

from cout_bank import CANDIDATES, REPO, REQUIREMENTS, parts_needed, report

# (sizing point, artefact, ripple_rms_a) -- every value recomputed from the raw
# before it was written into the artefact.  The two 120 A points are the measured
# I(Cout) RMS; the 100 A deck does not save that trace, so its number is the
# four-SR reconstruction, which reads about 1.2 % high.
POINTS = [
    ("rated_100a", "design/v3/bom/passive_requirements.json", 52.478279189636574),
    ("overload_48v_120a", "design/v3/power_priority/stress_48v_120a.json", 55.58079304753917),
    ("overload_50v_120a", "design/v3/power_priority/stress_50v_120a.json", 56.061937679462794),
]

PART_3MOHM = {"mpn": "synthetic-3m", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 3e-3,
              "irms_a": 11.69, "case": "-", "height_mm": 1.9}
PART_1MOHM = {"mpn": "synthetic-1m", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 1e-3,
              "irms_a": 11.69, "case": "-", "height_mm": 1.9}


def test_count_is_the_ceiling_of_each_requirement():
    bank = parts_needed(PART_3MOHM)
    assert bank["counts"] == {"capacitance": 9, "esr": 15, "rms": 5}
    assert bank["n"] == 15


def test_esr_governs_a_low_esr_part_only_when_it_is_the_largest():
    assert parts_needed(PART_3MOHM)["governed_by"] == "esr"
    assert parts_needed(PART_1MOHM)["governed_by"] == "capacitance"


def test_parallel_laws_capacitance_adds_and_esr_divides():
    bank = parts_needed(PART_3MOHM)
    n = bank["n"]
    assert abs(bank["bank_capacitance_f"] - n * 470e-6) < 1e-15
    assert abs(bank["bank_esr_ohm"] - 3e-3 / n) < 1e-15
    assert abs(bank["bank_irms_a"] - n * 11.69) < 1e-12


def test_meets_every_requirement_and_just_meets_the_governing_one():
    for part in CANDIDATES:
        bank = parts_needed(part)
        assert bank["bank_capacitance_f"] >= REQUIREMENTS["capacitance_f"] - 1e-15
        assert bank["bank_esr_ohm"] <= REQUIREMENTS["esr_ohm"] + 1e-15
        assert bank["bank_irms_a"] >= REQUIREMENTS["irms_a"]
        # one fewer part must break the governing requirement, or the count is not minimal
        smaller = {**part}
        n = bank["n"]
        assert (n - 1) * part["c_f"] < REQUIREMENTS["capacitance_f"] or \
               part["esr_ohm"] / (n - 1) > REQUIREMENTS["esr_ohm"] or \
               (n - 1) * part["irms_a"] < REQUIREMENTS["irms_a"]


def test_lowering_the_esr_target_adds_parts():
    strict = parts_needed(PART_3MOHM, {**REQUIREMENTS, "esr_ohm": 0.1e-3})
    assert strict["n"] == 30
    assert strict["governed_by"] == "esr"


def test_report_flags_that_the_part_data_is_unverified():
    data = report()
    assert data["no_output_ripple_spec"] is True
    assert "not datasheet-verified" in data["status"]
    assert {bank["part"] for bank in data["banks"]} == {part["mpn"] for part in CANDIDATES}


# ---------------------------------------------------------------- sizing point
def test_the_requirement_is_the_worst_measured_load_not_the_rated_one():
    """The 120 A overload runs are in the evidence set, so they set the requirement.

    Sizing the ripple rating on the 100 A point would buy a bank whose parts run
    hotter than the requirement says at a load that has already been simulated.
    """
    data = report()
    requirements = data["requirements"]
    points = requirements["sizing_points"]
    assert set(points) == {key for key, _path, _ripple in POINTS}
    assert requirements["sized_at"] == points["overload_50v_120a"]["source"]
    assert requirements["irms_a"] == pytest.approx(points["overload_50v_120a"]["ripple_rms_a"])
    # ordering is real physics, not an assumption: 50 V overload > 48 V overload > rated
    assert (requirements["irms_a"] > points["overload_48v_120a"]["ripple_rms_a"]
            > points["rated_100a"]["ripple_rms_a"])
    assert data["checks"]["the_requirement_is_the_worst_measured_load"] is True


def test_each_sizing_point_is_the_value_its_own_artifact_holds():
    data = report()
    for key, path, ripple in POINTS:
        point = data["requirements"]["sizing_points"][key]
        assert point["source"] == path
        assert point["ripple_rms_a"] == pytest.approx(ripple, rel=1e-12)
        on_disk = json.loads((REPO / path).read_text(encoding="utf-8"))["cout_ripple"]["ripple_rms_a"]
        assert point["ripple_rms_a"] == pytest.approx(on_disk, rel=1e-12)
        assert point["raw"], f"{key} must name the raw it was measured on"
        assert point["window_us"][1] > point["window_us"][0]


def test_every_point_passes_its_own_reconstruction_check():
    """A ripple figure whose mean disagrees with Vout/RL is not a measurement."""
    data = report()
    for key, _path, _ripple in POINTS:
        point = data["requirements"]["sizing_points"][key]
        assert abs(point["mean_check_pct"]) <= 0.5, key
    assert data["checks"]["every_reconstruction_agrees_with_vout_over_rl"] is True


def test_every_sizing_point_names_the_method_it_was_measured_by():
    """Three points sorted into one maximum must say whether they are comparable.

    Two of them measure ``I(Cout)``; the 100 A deck does not save that trace, so
    it can only be rebuilt from the four SR currents with pairs 2/3 assumed equal.
    A reader who takes the max of three numbers cannot see that difference unless
    each record carries it.
    """
    data = report()
    points = data["requirements"]["sizing_points"]
    for key in points:
        assert isinstance(points[key]["method"], str) and points[key]["method"], key
    measured = {points[key]["method"] for key in points if key != "rated_100a"}
    assert len(measured) == 1, "both overload points must use one method"
    assert points["rated_100a"]["method"] not in measured
    # the reconstruction is published beside the measured value, never instead of it
    for key in points:
        if key == "rated_100a":
            continue
        point = points[key]
        assert point["ripple_rms_reconstructed_a"] > point["ripple_rms_a"] > 0.0
        assert point["method_offset_frac"] == pytest.approx(
            point["ripple_rms_reconstructed_a"] / point["ripple_rms_a"] - 1.0, rel=1e-12)
    assert data["checks"]["every_sizing_point_names_its_method"] is True


def test_the_rated_point_loses_by_more_than_the_method_offset():
    """The max() mixes methods, so the gap has to beat the bias it could hide.

    The reconstruction reads high, and the rated point is the one on that method,
    so the bias favours the loser.  That makes the ordering conservative -- but
    only while the gap is larger than the offset.
    """
    data = report()
    results = data["results"]
    points = data["requirements"]["sizing_points"]
    offsets = [points[key]["method_offset_frac"] for key in points
               if "method_offset_frac" in points[key]]
    assert results["method_offset_max_frac"] == pytest.approx(max(offsets), rel=1e-12)
    rated = points["rated_100a"]["ripple_rms_a"]
    assert results["worst_over_rated_frac"] == pytest.approx(
        data["requirements"]["irms_a"] / rated - 1.0, rel=1e-12)
    assert results["worst_over_rated_frac"] > 5 * results["method_offset_max_frac"]
    assert data["checks"]["the_rated_point_loses_by_more_than_the_method_offset"] is True


# ---------------------------------------------------------------- consequences
def test_the_overload_resizes_one_candidate_s_rms_count_but_not_the_bank():
    data = report()
    results = data["results"]
    irms = data["requirements"]["irms_a"]
    # ESR dissipation at the model's 0.2 mohm -- the number the 1 W budget is about
    assert results["esr_loss_w_at_model_esr"] == pytest.approx(irms**2 * 0.2e-3, rel=1e-12)
    assert 0.62 < results["esr_loss_w_at_model_esr"] < 0.64
    governing = data["banks"][0]
    assert governing["n"] == governing["counts"]["esr"] == 15
    assert governing["counts"]["rms"] == 5
    row = next(b for b in results["banks"] if b["part"] == governing["part"])
    # the bank is ESR-limited, so each part carries little of the ripple
    assert row["per_part_ripple_a"] == pytest.approx(irms / 15, rel=1e-12)
    assert row["per_part_ripple_margin"] > 2.5
    # only the 5.9 A candidate's RMS count moves when sized at the overload
    moves = {b["part"]: b["rms_count_at_overload"] - b["rms_count_at_rated_load"]
             for b in results["banks"]}
    assert moves["Chemi-Con APSF2R5ELL471MF08S"] == 1
    assert all(move == 0 for part, move in moves.items()
               if part != "Chemi-Con APSF2R5ELL471MF08S")


def test_the_physical_results_are_not_in_the_checks_block():
    data = report()
    assert set(data["checks"]) == {
        "the_requirement_is_the_worst_measured_load",
        "every_sizing_point_traces_to_a_committed_artifact",
        "every_reconstruction_agrees_with_vout_over_rl",
        "every_bank_meets_the_requirements_at_the_worst_load",
        "every_sizing_point_names_its_method",
        "the_rated_point_loses_by_more_than_the_method_offset",
    }
    assert "esr_loss_w_at_model_esr" in data["results"]
