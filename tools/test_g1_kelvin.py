"""The two CT sense nets had no routed geometry.

The frozen G1 plan names "independent Kelvin" as day 3-5 work.  The SR local
layouts are blocked on unverified magnetic terminals and the Cout bank on an
unresolved MPN, but the two 3-pad sense nets (CS1 / CS2) are fully concrete on
the board.  `route_kelvin.py` routes them with the shared checker and
`apply_kelvin.py` puts them on a fresh copy of the power-rail candidate.

Offline only; nothing here opens the editor.
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

G1 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g1"
sys.path.insert(0, str(G1))
spec = importlib.util.spec_from_file_location("g1kelvin", G1 / "route_kelvin.py")
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


def endpoints(net: str) -> set[tuple[float, float]]:
    return {pt for s in k.R.segments(k.copper()) if s["net"] == net
            for pt in (s["a"], s["b"])}


def test_cs1_reaches_the_ct_pad_and_both_diode_pads():
    ends = endpoints("CS1")
    assert (104.0, 56.0) in ends          # CT SEC_A provisional pad
    assert (109.0, 70.95) in ends         # D_CT1.1
    assert (119.0, 70.0) in ends          # D_CT3.3


def test_cs2_reaches_the_ct_pad_and_both_diode_pads():
    ends = endpoints("CS2")
    assert (104.0, 48.0) in ends          # CT SEC_B
    assert (115.0, 70.95) in ends         # D_CT2.1
    assert (125.0, 70.0) in ends          # D_CT4.3


def test_the_plan_has_no_clearance_endpoint_or_via_problem_against_the_board():
    assert k.problems() == []


def test_the_sense_nets_clear_the_unassigned_diode_pads():
    """D_CT1.2 / D_CT2.2 sit between the pads the sense nets serve.

    The direct verticals through (109, ...) and (115, ...) ran straight over
    them; the native DRC reported it (0 mil to a pad that needs >= 6 mil).
    The checker only sees these pads now that ``load_pads`` keeps net-less pads.
    """
    pads = k.R.load_pads(k.READBACK)
    none = [p for p in pads if not p["net"]]
    assert len(none) == 5
    assert k.R.find_conflicts(none, k.R.segments(k.copper())) == []


def test_the_summary_names_every_junction_and_its_layers():
    s = k.summary()
    assert s["status"] == "DRAFT_CT_KELVIN_ON_CS1_CS2"
    assert set(s["nets"]["CS1"]["endpoint_refs"]) == {
        "CS1@(104.00,56.00)", "D_CT1.1", "D_CT3.3"}
    assert set(s["nets"]["CS2"]["endpoint_refs"]) == {
        "CS2@(104.00,48.00)", "D_CT2.1", "D_CT4.3"}
    assert s["nets"]["CS1"]["layers"] == [1, 2]
    assert s["nets"]["CS2"]["layers"] == [1]
    assert s["vias"] == [[106.2, 56.0], [110.1, 66.5], [119.0, 69.0]]
    assert math.isclose(s["nets"]["CS1"]["length_mm"], 34.55)
    assert math.isclose(s["nets"]["CS2"]["length_mm"], 54.15)


def test_the_vias_are_all_cs1_and_join_its_two_layers():
    assert [(v["net"], (v["x"], v["y"])) for v in k.vias()] == [
        ("CS1", (106.2, 56.0)), ("CS1", (110.1, 66.5)), ("CS1", (119.0, 69.0))]
    assert {s["layer"] for s in k.R.segments(k.copper()) if s["net"] == "CS2"} == {1}


def test_verify_on_the_pre_kelvin_readback_names_exactly_these_nets_missing():
    report = k.verify(k.READBACK)
    problems = report["lines"]["coverage_problems"]
    assert {x["kind"] for x in problems} == {"coverage"}
    assert len(problems) == len(k.R.segments(k.copper()))
    assert {x["net"] for x in problems} == {"CS1", "CS2"}
    assert len(report["vias"]["problems"]) == 3
    assert report["placement_drift"] == []
    assert report["layout_counts"]["unchanged"] is True
    assert report["native_drc_passed"] is False
    assert report["board"] == k.CANDIDATE


def test_the_report_quotes_the_native_drc_raw_instead_of_asserting_a_pass():
    report = json.loads((G1 / "kelvin_report.json").read_text(encoding="utf-8"))
    raw = json.loads((G1 / "kelvin_drc_raw.json").read_text(encoding="utf-8"))["value"]
    groups = {g["name"]: g.get("count") for g in raw["raw"]}
    assert report["drc"]["source"] == "kelvin_drc_raw.json"
    assert report["drc"]["connection_errors"] == groups.get("Connection Error", 0)
    assert report["drc"]["netlist_errors"] == groups.get("Netlist Error", 0)
    assert report["drc"]["physical_errors"] == k.drc_summary()["physical_errors"]
    assert report["drc"]["physical_errors"] == 0        # the two kelvin run was clean
    assert report["native_drc_passed"] is False         # open nets are not a pass


def test_the_committed_plan_file_is_what_the_module_computes():
    committed = json.loads((G1 / "kelvin_plan.json").read_text(encoding="utf-8"))
    assert committed == k.summary() | {"problems": []}


def test_the_applier_copies_the_power_rail_candidate_not_the_routed_one():
    spec = importlib.util.spec_from_file_location("g1applyk", G1 / "apply_kelvin.py")
    a = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a)
    assert a.SOURCE.name == "dcx_main_board_g1_power_rails.eprj2"
    assert a.TARGET.name == "dcx_main_board_g1_kelvin.eprj2"
    assert a.SOURCE != a.TARGET
    assert '"CS1"' in a.BODY and '"CS2"' in a.BODY
    assert "eda.pcb_PrimitiveVia.create(" in a.BODY


def test_the_emitted_body_carries_layer_two_for_cs1_only():
    js = k.R.emit_js(k.copper(), k.vias())
    assert '"CS1", 2,' in js or '"CS1",2,' in js
    assert '"CS2", 2,' not in js and '"CS2",2,' not in js
