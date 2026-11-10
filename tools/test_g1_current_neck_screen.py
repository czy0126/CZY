"""Fail-closed regression for saved/reopened G1 100 A copper-neck screen."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g1_current_neck_screen as S


def track(net, x1, y1, x2, y2, ident):
    return {"id": ident, "net": net, "layer": 1,
            "x1": x1/S.MIL_MM, "y1": -y1/S.MIL_MM,
            "x2": x2/S.MIL_MM, "y2": -y2/S.MIL_MM,
            "width": 1/S.MIL_MM}


def fixture():
    lines = []
    for x in (39, 77, 115, 153):
        lines.append(track("VOUT", x-2, 20, x, 20, f"vout-h-{x}"))
        lines.append(track("VOUT", x, 20, x, 35.5, f"vout-v-{x}"))
    for x in (13.401, 23.401, 51.399, 61.399,
              89.400, 99.400, 127.401, 137.401):
        lines.append(track("PGND", x, 84.470, x, 96., f"pgnd-{x}"))
    wide_bus = track("VOUT", 39, 35.5, 77, 35.5, "wide-vout-bus")
    wide_bus["width"] = 2/S.MIL_MM
    lines.append(wide_bus)
    return lines


def test_actual_narrow_neck_topology_and_dc_floor():
    result = S.analyze(fixture())
    assert len(result["vout_four_ctap_branches"]) == 4
    assert len(result["pgnd_eight_sr_source_branches"]) == 8
    assert all(x["length_mm"] == pytest.approx(17.5, abs=1e-4)
               for x in result["vout_four_ctap_branches"])
    assert all(x["length_mm"] == pytest.approx(11.53, abs=1e-4)
               for x in result["pgnd_eight_sr_source_branches"])
    scenarios = {x["nominal_thickness_um"]: x for x in result["scenarios"]}
    assert scenarios[70]["vout_necks_uohm"] == pytest.approx(1416.3, abs=.3)
    assert scenarios[70]["pgnd_necks_uohm"] == pytest.approx(466.6, abs=.2)
    assert scenarios[70]["combined_necks_uohm"] == pytest.approx(1882.8, abs=.4)
    assert scenarios[70]["ideal_100a_neck_loss_w"] == pytest.approx(18.83, abs=.02)
    assert scenarios[210]["combined_necks_uohm"] > 600
    assert all(not s["within_complete_rail_budget"] for s in result["scenarios"])
    assert result["fabrication_approved"] is False


def test_wrong_net_missing_neck_duplicate_and_width_regressions_fail():
    lines = fixture()
    lines[0]["net"] = "PGND"
    with pytest.raises(ValueError, match="VOUT CTAP"):
        S.analyze(lines)
    lines = fixture()
    lines.pop(10)
    with pytest.raises(ValueError, match="SR PGND"):
        S.analyze(lines)
    lines = fixture()
    lines[1]["id"] = lines[0]["id"]
    with pytest.raises(ValueError, match="duplicated"):
        S.analyze(lines)
    lines = fixture()
    lines[0]["width"] = .8/S.MIL_MM
    with pytest.raises(ValueError, match="VOUT CTAP"):
        S.analyze(lines)


def test_copper_corners_and_parallel_math():
    branch = [S.unpack(fixture()[0])]
    assert S.resistance(branch, 70, 100) > S.resistance(branch, 210, 100)
    assert S.resistance(branch, 70, 100) > S.resistance(branch, 70, 20)
    with pytest.raises(ValueError):
        S.resistance(branch, 0)
    with pytest.raises(ValueError):
        S.parallel_resistance([float("nan")])
    assert math.isclose(S.parallel_resistance([.002, .002]), .001)


def test_committed_reopen_report_reproducible():
    # Reads actual pinned SHA and geometry; offline test never fabricates solver results.
    assert S.report() == __import__("json").loads(S.REPORT.read_text(encoding="utf-8"))
