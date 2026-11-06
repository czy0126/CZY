"""Regression gates for the physical fast-OC <-> D0 harness.

This catches an unsafe *assembly instruction* even when KiCad ERC and
combinational logic tests still pass.  No hardware measurements are claimed.
The V5=5V resistor calculation is a nominal logic screening, NOT a real
brown-out / backfeed / ten-gate turn-off safety qualification.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_d0_protection_board as d0  # noqa: E402
import make_fast_oc_eco as mod  # noqa: E402

GUIDE = d0.ROOT / "docs/D1_EXECUTION_KIT/34_TLV3501快速过流ECO模块.md"


def one(parts, ref, unit=1):
    found = [p for p in parts if p.ref == ref and p.unit == unit]
    assert len(found) == 1, (ref, unit, len(found))
    return found[0]


def ohms(part):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kM]?)", part.value)
    assert match is not None, (part.ref, part.value)
    return float(match.group(1)) * {"": 1, "k": 1e3, "M": 1e6}[match.group(2)]


def test_harness_pins_and_opposite_trip_polarities_are_not_shorted():
    local, remote = d0.parts(), mod.parts()
    assert one(remote, "J1").nets == one(local, "J10").nets == {
        "1": "V5", "2": "PGND", "3": "OCD", "4": "FAST_EXT_N"
    }
    assert one(remote, "Q1").nets["3"] == "FAST_EXT_N"
    assert one(local, "U11", 6).nets == {"13": "FAST_EXT_N", "12": "FAST_EXT_H"}
    assert one(local, "U19", 1).nets == {
        "1": "FAST_TRIP", "2": "FAST_EXT_H", "3": "FAST_COMBINED"
    }
    assert one(local, "J10").nets["4"] != "FAST_TRIP"


def test_open_wire_requests_fault_and_normal_no_fault_reaches_inverter_vih():
    local, remote = d0.parts(), mod.parts()
    pull_up = one(remote, "R7")
    pull_down = one(local, "R100")
    assert pull_up.nets == {"1": "V5", "2": "FAST_EXT_N"}
    assert pull_down.nets == {"1": "FAST_EXT_N", "2": "PGND"}
    assert ohms(pull_up) == 10_000 and ohms(pull_down) == 100_000
    # With a broken J1.4, the D0-side R100 forces logical LOW (fault).
    # With a healthy cable and Q1 OFF, 10k/100k divides the common V5.
    nominal = 5.0 * ohms(pull_down) / (ohms(pull_up) + ohms(pull_down))
    assert nominal == pytest.approx(4.545454545, rel=1e-5)
    # +/-10% part-selection screen. TI CD4069UB VIH(min) at VDD=5V: 4.0V.
    # NOT a guarantee over V5 variation, leakage, harness noise or brownout.
    corner = 5.0 * (0.9 * ohms(pull_down)) / (
        1.1 * ohms(pull_up) + 0.9 * ohms(pull_down))
    assert corner > 4.0


def test_10v_step_does_not_magically_trip_after_one_time_constant():
    # The input pole is 1us, but crossing a 76.6%-of-step threshold takes
    # more than one tau. The full shutdown chain is slower and unverified.
    trip_v = mod.divider()["trip_burden_v"]
    tau = mod.C_IN * mod.R_TOP * mod.R_BOT / (mod.R_TOP + mod.R_BOT)
    assert 0 < trip_v < 10.0
    t_cross = -tau * math.log1p(-trip_v / 10.0)
    assert 1.40e-6 < t_cross < 1.60e-6


def test_assembly_guide_matches_the_actual_harness_and_rejects_old_wiring():
    guide = GUIDE.read_text(encoding="utf-8")
    assert "J1.4  FAST_EXT_N  -> D0 J10.4 FAST_EXT_N" in guide
    assert "禁止" in guide and "TP8" in guide
    assert "U11F" in guide and "U19" in guide
    assert "1.45µs" in guide
    assert "UNVERIFIED" in guide and "反灌" in guide
    # Regression: do not publish the obsolete physically dangerous jumper.
    assert not re.search(r"J1\.4\s+FAST_TRIP\s*(?:->|→)", guide)
    assert not re.search(r"J1\.4\s+(?:->|→)\s*D0\s+FAST_TRIP", guide)
