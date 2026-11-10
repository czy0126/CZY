"""The G1 output path had no geometry.

`output_joint_reduction_cases.json` asks for VOUT and PGND "from SR-Cout pads to
external load as two explicit physical rails" and for every interface to be
enumerated.  `route_power_rails.py` is that draft: the endpoints are read back
from the routed candidate, and the offline checker is the shared one from
`route_driver_eco`, so the tests below pin the interfaces and prove the gate is
not vacuous (a 2 mm pad neck must fail it).

Everything here is offline; nothing opens the editor.
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location("g1rails", G1 / "route_power_rails.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

MIL = 39.37007874015748


def endpoints(net: str) -> set[tuple[float, float]]:
    return {pt for s in p.R.segments(p.copper()) if s["net"] == net
            for pt in (s["a"], s["b"])}


def test_vout_reaches_all_four_centre_taps_the_cout_pad_and_j_out_1():
    ends = endpoints("VOUT")
    for x in (37.0, 75.0, 113.0, 151.0):
        assert (x, 20.0) in ends, x  # the four provisional CTAP pads
    assert (4.3, 47.0) in ends  # Cout.1
    assert (73.5, 116.0) in ends  # J_OUT.1


def test_pgnd_reaches_all_eight_sr_source_tabs_the_cout_pad_and_j_out_2():
    ends = endpoints("PGND")
    for x in p.SR_TABS:
        assert (x, p.SR_TAB_Y) in ends, x
    assert (5.7, 47.0) in ends  # Cout.2
    assert (78.5, 116.0) in ends  # J_OUT.2


def test_the_committed_readback_has_no_clearance_or_endpoint_problem():
    assert p.problems() == []


def test_the_report_names_every_interface_and_claims_no_ampacity():
    rails = p.summary()["rails"]
    assert set(rails["VOUT"]["endpoint_refs"]) == {
        "Cout.1", "J_OUT.1", "VOUT@(37.00,20.00)", "VOUT@(75.00,20.00)",
        "VOUT@(113.00,20.00)", "VOUT@(151.00,20.00)"}
    assert set(rails["PGND"]["endpoint_refs"]) == {
        "Cout.2", "J_OUT.2",
        "SR1A.3", "SR1B.3", "SR2A.3", "SR2B.3",
        "SR3A.3", "SR3B.3", "SR4A.3", "SR4B.3"}
    s = p.summary()
    assert s["status"] == "DRAFT_TWO_RAILS_NOT_AMPACITY_QUALIFIED"
    assert any("not an ampacity claim" in n for n in s["not_qualified"])


def test_each_centre_tap_drop_steps_aside_before_it_descends():
    # A straight drop at the pad x runs through the SEC_B pad 7 mm below it.
    for pad_x, dodge_x in p.CTAP_DODGE:
        assert abs(dodge_x - pad_x) >= 1.5, (pad_x, dodge_x)
        assert (dodge_x, 20.0) in endpoints("VOUT")
        assert (dodge_x, p.VOUT_BUS_Y) in endpoints("VOUT")


def test_the_pgnd_bus_connects_every_source_lead_and_the_two_ends():
    bus = p.bus()["PGND"]
    assert bus["width"] == p.RAIL_W
    ((a, b),) = bus["paths"]
    assert a == (5.7, p.RAIL_Y) and b == (p.SR_TABS[-1], p.RAIL_Y)
    for x in p.SR_TABS:
        assert a[0] <= x <= b[0], x


def test_only_the_vout_trunk_leaves_layer_one_and_two_vias_join_it():
    assert {s["layer"] for s in p.R.segments(p.copper()) if s["net"] == "PGND"} == {1}
    assert {s["layer"] for s in p.R.segments(p.copper()) if s["net"] == "VOUT"} == {1, 2}
    assert [(v["net"], (v["x"], v["y"])) for v in p.vias()] == [
        ("VOUT", p.VOUT_VIA_LEFT), ("VOUT", p.VOUT_VIA_RIGHT)]


def test_verify_on_the_route_readback_names_the_rails_as_missing():
    """The readback that predates the rails must fail coverage for exactly them."""
    report = p.verify(p.READBACK)
    problems = report["lines"]["coverage_problems"]
    assert {x["kind"] for x in problems} == {"coverage"}
    assert len(problems) == len(p.R.segments(p.copper()))
    assert {x["net"] for x in problems} == {"VOUT", "PGND"}
    assert len(report["vias"]["problems"]) == 2
    assert report["placement_drift"] == []
    assert report["layout_counts"]["unchanged"] is True
    assert report["native_drc_passed"] is False
    assert report["board"] == p.CANDIDATE


def test_the_applier_writes_a_fresh_copy_and_never_opens_the_routed_candidate():
    spec = importlib.util.spec_from_file_location("g1apply", G1 / "apply_power_rails.py")
    a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a)
    assert a.SOURCE.name == "dcx_main_board_g1_driver_route.eprj2"
    assert a.TARGET.name == "dcx_main_board_g1_power_rails.eprj2"
    assert a.SOURCE != a.TARGET
    assert '"VOUT"' in a.BODY and '"PGND"' in a.BODY
    assert "eda.pcb_PrimitiveVia.create(" in a.BODY


def test_the_committed_plan_file_is_what_the_module_computes():
    committed = json.loads((G1 / "power_rail_plan.json").read_text(encoding="utf-8"))
    assert committed == p.summary() | {"problems": []}


def test_a_two_millimetre_pad_neck_fails_the_same_check():
    """The gate is real: the 1 mm necks exist because 2 mm does not clear."""
    wide = p.plan()
    for spec_ in wide.values():
        spec_["width"] = p.RAIL_W
    issues = p.R.check_plan(p.R.load_pads(p.READBACK), [wide, p.bus()], vias=p.vias())
    assert issues, "a 2 mm neck must collide with the SEC / drain pads"


def test_the_emitted_js_carries_this_plan_in_mil_and_y_up():
    js = p.R.emit_js(p.copper(), p.vias())
    assert js.count("eda.pcb_PrimitiveVia.create(") == 1  # one call, looped over VIA_ROWS
    assert "copperLayers < 2" in js

    def mil(x, y):
        return round(x * MIL, 3), round(-y * MIL, 3)

    for s in p.R.segments(p.copper()):
        row = [s["net"], s["layer"], round(s["width"] * MIL, 3),
               *mil(*s["a"]), *mil(*s["b"])]
        assert json.dumps(row) in js, row
    for v in p.vias():
        row = [v["net"], *mil(v["x"], v["y"]),
               round(v["hole"] * MIL, 3), round(v["diameter"] * MIL, 3)]
        assert json.dumps(row) in js, row
    assert math.isclose(round(4.3 * MIL, 3), 169.291)
