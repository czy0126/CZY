"""Lock the offline checks used before any G1 driver copper is created."""

import importlib.util
import sys
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location("g1_route", G1 / "route_driver_eco.py")
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def pad(ref, number, net, x, y, w, h):
    return {"ref": ref, "pin": str(number), "net": net,
            "bbox": (x - w / 2, y - h / 2, x + w / 2, y + h / 2), "x": x, "y": y}


def test_segment_crossing_between_different_nets_is_detected():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5), pad("B", "1", "N2", 10, 0, 0.5, 0.5)]
    segs = [{"net": "N1", "width": 0.25, "a": (0, 0), "b": (10, 0)},
            {"net": "N2", "width": 0.25, "a": (5, -5), "b": (5, 5)}]
    assert route.find_conflicts(pads, segs)


def test_clearance_to_a_foreign_net_pad_is_enforced():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5),
            pad("B", "1", "N2", 5, 0.5, 0.5, 0.5)]
    seg = [{"net": "N1", "width": 0.25, "a": (0, 0), "b": (10, 0)}]
    assert route.find_conflicts(pads, seg, clearance=0.2)
    pads[1] = pad("B", "1", "N2", 5, 2.0, 0.5, 0.5)
    assert not route.find_conflicts(pads, seg, clearance=0.2)


def test_same_net_pad_may_be_touched():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5), pad("A", "2", "N1", 5, 0, 0.5, 0.5)]
    seg = [{"net": "N1", "width": 0.25, "a": (0, 0), "b": (5, 0)}]
    assert not route.find_conflicts(pads, seg, clearance=0.2)


def test_an_endpoint_off_its_net_pad_is_reported():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5), pad("B", "1", "N1", 10, 0, 0.5, 0.5)]
    path = {"net": "N1", "width": 0.25, "points": [(0, 0), (10, 0), (12, 0)]}
    assert route.endpoint_problems(pads, path)
    path["points"] = [(0, 0), (10, 0)]
    assert not route.endpoint_problems(pads, path)


def test_the_planned_routes_pass_the_offline_check():
    pads = route.load_pads(route.HERE / "driver_readback.json")
    problems = route.check_plan(pads, route.PLAN)
    assert not problems, problems


def test_editor_split_at_a_junction_is_accepted():
    plan = {"N1": {"width": 0.2, "paths": [[(0, 0), (10, 0)]]}}
    lines = [{"net": "N1", "layer": 1, "width": 0.2, "a": (0, 0), "b": (4, 0)},
             {"net": "N1", "layer": 1, "width": 0.2, "a": (4, 0), "b": (10, 0)}]
    assert not route.verify_lines(plan, lines)


def test_gap_in_readback_coverage_is_rejected():
    plan = {"N1": {"width": 0.2, "paths": [[(0, 0), (10, 0)]]}}
    lines = [{"net": "N1", "layer": 1, "width": 0.2, "a": (0, 0), "b": (4, 0)},
             {"net": "N1", "layer": 1, "width": 0.2, "a": (6, 0), "b": (10, 0)}]
    assert route.verify_lines(plan, lines)


def test_line_off_the_plan_is_rejected():
    plan = {"N1": {"width": 0.2, "paths": [[(0, 0), (10, 0)]]}}
    lines = [{"net": "N1", "layer": 1, "width": 0.2, "a": (0, 0), "b": (10, 0)},
             {"net": "N1", "layer": 1, "width": 0.2, "a": (0, 0.5), "b": (10, 0.5)}]
    assert route.verify_lines(plan, lines)
