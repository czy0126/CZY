"""The Cout bank's own copper, which `part ESR / N` leaves out.

`cout_bank.json` sizes the bank as `part ESR / N` and says in its caveat that
this assumes zero interconnect.  SOURCE-04 asks for the same term from the
other side ("include spreading copper/joints").  The physics that makes the
caveat true is one line: each capacitor is in series with its own copper, so
the copper enters *before* the parallel combination and the bank ESR is
`1 / sum(1 / (ESR_part + R_branch_i))`, not `ESR_part / N`.

These tests pin the arithmetic, the provenance of the geometry, and the two
results a reader will quote: how much the placement costs, and how far the
worst branch is beyond the allowance that would cost 10 %.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cout_bank_path as cp  # noqa: E402
import main_board_mechanical as mbm  # noqa: E402
import output_path_budget as opb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JSON_OUT = ROOT / "design/v3/bom/cout_bank_path.json"


def cout_json() -> dict:
    return json.loads((ROOT / "design/v3/bom/cout_bank.json").read_text(encoding="utf-8"))


def placed_bank() -> dict:
    return cout_json()["banks"][0]


# ---------------------------------------------------------------- arithmetic
def test_the_parts_only_esr_is_the_bank_esr_times_the_count():
    """0.2 mohm at N = 15 means the part is 3 mohm, and that is the only part
    number the sizing ever recorded."""
    assert cp.part_esr_ohm(placed_bank()) == pytest.approx(3e-3, rel=1e-12)


def test_zero_copper_reproduces_part_esr_over_n():
    """With no interconnect the model must collapse to what the sizing published,
    otherwise the two tools are not describing the same bank."""
    esr = 3e-3
    assert cp.parallel_esr(esr, [0.0] * 15) == pytest.approx(esr / 15, rel=1e-12)


def test_copper_is_in_series_before_the_parallel_combination():
    """Four equal branches of 0.5 mohm give (3 + 0.5) / 4 = 0.875, not the two
    likely mistakes: 3/4 (copper dropped) or 3/4 + 0.5 (one branch added
    unscaled).  Both look plausible and both are wrong."""
    esr, branch, n = 3e-3, 0.5e-3, 4
    exact = cp.parallel_esr(esr, [branch] * n)
    assert exact == pytest.approx((esr + branch) / n, rel=1e-12)
    assert exact != pytest.approx(esr / n, rel=1e-6)              # copper dropped
    assert exact != pytest.approx(esr / n + branch, rel=1e-6)     # one branch, unscaled
    assert exact / (esr / n) - 1.0 == pytest.approx(branch / esr, rel=1e-12)


def test_an_unequal_branch_set_matches_the_conductance_sum():
    esr, branches = 3e-3, [0.6e-3, 0.9e-3, 1.4e-3]
    expected = 1.0 / sum(1.0 / (esr + b) for b in branches)
    assert cp.parallel_esr(esr, branches) == pytest.approx(expected, rel=1e-12)


def test_a_thicker_plane_lowers_the_bank_esr():
    banks = [cp.bank_esr_with_copper(placed_bank(), oz * opb.OZ_M)["bank_esr_mohm"]
             for oz in (1, 2, 4)]
    assert banks[0] > banks[1] > banks[2]


# ---------------------------------------------------------------- provenance
def test_the_units_come_from_the_placement_study():
    """Move Cout1 and the answer must move; nothing here may be a constant."""
    placed = cp.units(mbm.report())
    assert len(placed) == placed_bank()["n"] == 15
    assert placed[0]["ref"] == "Cout1" and placed[0]["x_mm"] == pytest.approx(14.0)
    assert placed[-1]["ref"] == "Cout15" and placed[-1]["x_mm"] == pytest.approx(128.8)


def test_the_lane_width_is_the_measured_unit_pitch():
    placed = cp.units(mbm.report())
    assert cp.unit_pitch_mm(placed) == pytest.approx(8.2, abs=1e-9)


def test_each_unit_is_assigned_to_the_nearest_group_centre():
    groups = opb._geometry()["groups"]
    for unit in cp.units(mbm.report()):
        chosen = cp.nearest_group(unit["x_mm"], groups)
        others = [abs(unit["x_mm"] - g["x_mm"]) for g in groups]
        assert abs(unit["x_mm"] - chosen["x_mm"]) == pytest.approx(min(others), rel=1e-12)


def test_the_bank_row_is_straight_and_above_the_sr_row():
    placed = cp.units(mbm.report())
    ys = {p["y_mm"] for p in placed}
    assert len(ys) == 1, ys
    assert min(ys) > 82.0   # the SR row the current comes from


# ---------------------------------------------------------------- the results
def test_the_placement_costs_about_a_third_of_the_bank_esr():
    """The headline.  0.2 mohm is a parallel-of-parts number; the placed copper
    takes it to about 0.27 mohm, and that move is larger than the 0.1 mohm
    decision that doubles the part count."""
    data = cp.bank_esr_with_copper(placed_bank(), 2 * opb.OZ_M)
    assert data["bank_esr_mohm"] == pytest.approx(0.269, abs=0.003)
    assert data["parts_only_esr_mohm"] == pytest.approx(0.2, rel=1e-12)
    assert 0.30 < data["rise_frac"] < 0.40, data["rise_frac"]


def test_the_worst_branch_is_far_beyond_the_ten_percent_allowance():
    """0.3 mohm per branch is what a 10 % rise allows at N = 15 / 3 mohm.  The
    farthest unit in the row sits at ~1.4 mohm."""
    allowance = cp.allowance(3e-3, 15, 0.10)
    assert allowance == pytest.approx(0.3e-3, rel=1e-12)
    data = cp.bank_esr_with_copper(placed_bank(), 2 * opb.OZ_M)
    assert data["worst_branch_mohm"] * 1e-3 / allowance > 4.0


def test_more_parts_buy_copper_tolerance_linearly():
    """The 6.3 V / 30-unit option tolerates twice the branch resistance for the
    same percentage rise, exactly because the allowance is `target*N - ESR`."""
    fifteen = cp.allowance(3e-3, 15, 0.10)
    thirty = cp.allowance(6e-3, 30, 0.10)
    assert thirty / fifteen == pytest.approx(2.0, rel=1e-12)


def test_the_current_share_spread_is_reported_not_assumed_equal():
    """SOURCE-04 also asks about thermal imbalance.  Resistance alone cannot give
    temperature, but it does give the share, and the share is not 1/15."""
    data = cp.bank_esr_with_copper(placed_bank(), 2 * opb.OZ_M)
    share = data["current_share"]
    assert sum(u["share_pct"] for u in share["per_unit"]) == pytest.approx(100.0, abs=0.05)
    assert share["highest_pct"] > share["nominal_pct"] > share["lowest_pct"]
    assert share["highest_over_nominal"] > 1.05


# ---------------------------------------------------------------- honesty
def test_the_report_does_not_claim_a_bound_for_an_unrouted_plane():
    data = cp.bank_esr_with_copper(placed_bank(), 2 * opb.OZ_M)
    assert "not a bound" in data["direction"].lower()
    limits = " ".join(data["limits"])
    for phrase in ("200 kHz", "via", "not additive", "no thermal model", "no monotonic ripple bound"):
        assert phrase in limits, phrase


def test_the_committed_json_is_what_the_tool_produces():
    committed = json.loads(JSON_OUT.read_text(encoding="utf-8"))
    fresh = cp.report()
    for key in ("placed_bank", "results", "model", "checks", "finding"):
        assert committed[key] == fresh[key], f"{key} is stale -- rerun the tool"
    assert all(committed["checks"].values())
