"""Lock the offline checks used before any G1 driver copper is created."""

import importlib.util
import json
import sys
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location("g1_route", G1 / "route_driver_eco.py")
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def pad(ref, number, net, x, y, w, h, layer=1):
    return {"ref": ref, "pin": str(number), "net": net, "layer": layer,
            "bbox": (x - w / 2, y - h / 2, x + w / 2, y + h / 2), "x": x, "y": y}


def via(net, x, y, diameter=0.5):
    return {"net": net, "x": x, "y": y, "diameter": diameter, "hole": 0.2}


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


def test_the_two_layer_resolution_passes_the_offline_check():
    pads = route.load_pads(route.HERE / "driver_readback.json")
    problems = route.check_plan(pads, [route.PLAN, route.STUBS, route.BOTTOM],
                                vias=route.VIAS)
    assert not problems, problems


def test_the_via_geometry_sits_inside_the_board_rule_file():
    """``driver_rules_raw.json`` is the board's own rule set (``pcb_Drc``).

    A 0.2 mm drill made the native DRC report 13 "Via Size" errors, and the
    outer diameter cannot grow to 0.6 mm to pay for a thicker ring: three
    trace-to-via clearances are only 0.559 / 0.564 / 0.595 mm.
    """
    rules = json.loads((G1 / "driver_rules_raw.json").read_text(encoding="utf-8"))
    form = rules["value"]["config"]["Physics"]["Via Size"]["viaSize"]["form"]
    assert route.VIA_HOLE >= form["viaInnerdiameterMin"]
    assert route.VIA_DIAMETER >= form["viaOuterdiameterMin"]
    assert route.VIA_DIAMETER - route.VIA_HOLE >= 0.2 - 1e-9  # 0.1 mm ring per side
    assert {v["hole"] for v in route.VIAS} == {route.VIA_HOLE}
    assert {v["diameter"] for v in route.VIAS} == {route.VIA_DIAMETER}


def test_a_bottom_trace_may_pass_under_a_top_smd_pad():
    pads = [pad("A", "1", "N1", 0, 5, 0.5, 0.5), pad("B", "1", "N2", 10, 5, 0.5, 0.5)]
    seg = [{"net": "N1", "width": 0.3, "layer": 2, "a": (0, 5), "b": (10, 5)}]
    assert not route.find_conflicts(pads, seg, clearance=0.15)


def test_a_bottom_trace_must_clear_a_through_hole_pad():
    pads = [pad("J", "1", "N2", 5, 5, 0.5, 0.5, layer=12)]
    seg = [{"net": "N1", "width": 0.3, "layer": 2, "a": (0, 5), "b": (10, 5)}]
    assert route.find_conflicts(pads, seg, clearance=0.15)


def test_traces_on_different_layers_do_not_conflict():
    segs = [{"net": "N1", "width": 0.3, "layer": 1, "a": (0, 0), "b": (10, 0)},
            {"net": "N2", "width": 0.3, "layer": 2, "a": (5, -5), "b": (5, 5)}]
    assert not route.find_conflicts([], segs, clearance=0.15)


def test_a_via_must_clear_a_pad_on_any_layer():
    pads = [pad("A", "1", "N2", 0, 0, 0.5, 0.5, layer=1)]
    vias = [via("N1", 0.4, 0.0)]
    assert route.find_conflicts(pads, [], clearance=0.15, vias=vias)
    vias = [via("N1", 2.0, 0.0)]
    assert not route.find_conflicts(pads, [], clearance=0.15, vias=vias)


def test_a_same_net_via_is_a_valid_endpoint():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5, layer=12)]
    vias = [via("N1", 5, 5)]
    path = {"net": "N1", "layer": 2, "points": [(5, 5), (0, 0)]}
    assert not route.endpoint_problems(pads, path, vias=vias)


def test_a_bottom_endpoint_cannot_land_on_a_top_only_pad():
    pads = [pad("A", "1", "N1", 0, 0, 0.5, 0.5)]
    path = {"net": "N1", "layer": 2, "points": [(0, 0), (5, 0)]}
    assert route.endpoint_problems(pads, path)


def test_an_endpoint_landing_on_a_foreign_via_is_rejected():
    vias = [via("N2", 5, 5)]
    path = {"net": "N1", "layer": 2, "points": [(5, 5), (0, 0)]}
    assert route.endpoint_problems([], path, vias=vias)


def test_a_dangling_via_is_rejected():
    pads = route.load_pads(route.HERE / "driver_readback.json")
    problems = route.check_plan(pads, [route.STUBS], vias=[via("SW", 0, 0)])
    assert any(p["kind"] == "via-dangling" for p in problems)


def test_verification_distinguishes_layers():
    plan = {"N1": {"width": 0.2, "layer": 1, "paths": [[(0, 0), (10, 0)]]}}
    lines = [{"net": "N1", "layer": 2, "width": 0.2, "a": (0, 0), "b": (10, 0)}]
    assert route.verify_lines(plan, lines)


def test_emit_js_carries_the_layer_and_the_vias():
    js = route.emit_js([route.PLAN, route.STUBS, route.BOTTOM], route.VIAS)
    assert "pcb_PrimitiveVia.create" in js
    assert "getTheNumberOfCopperLayers" in js
    assert '["SW", 2,' in js
    assert '["HB", 1,' in js


def test_readback_vias_must_match_the_plan():
    readback = [{"net": "SW", "x": 52.499, "y": 63.9, "hole": 0.2, "diameter": 0.5}]
    assert not route.verify_vias([route.VIAS[10]], readback)
    assert route.verify_vias([route.VIAS[10]], [])


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
