"""Tests for tools/cout_bank.py.

The bank is sized by the *worst* of three independent requirements, so the tests
pin the ceiling, the "which one wins" selection, and the parallel laws that make
the count valid in the first place.
"""

from __future__ import annotations

from cout_bank import CANDIDATES, REQUIREMENTS, parts_needed, report

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


def test_a720_oem_max_height_must_not_use_distributor_nominal():
    """YAGEO/KEMET OEM spec A720V477M2R5APE003 gives H MAX 2.1mm,
    not the 1.9mm value previously copied from a reseller summary."""
    a720 = next(p for p in CANDIDATES if p["mpn"]=="KEMET A720V477M2R5APE003")
    assert a720["height_mm"] == 2.1
    bank = next(b for b in report()["banks"] if b["part"]==a720["mpn"])
    assert bank["height_mm"] == 2.1
