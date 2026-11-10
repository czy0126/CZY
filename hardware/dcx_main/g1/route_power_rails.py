"""The G1 output as two explicit physical rails: VOUT and PGND.

``output_joint_reduction_cases.json`` names the CAD action it is waiting for:
"identify VOUT and PGND from SR-Cout pads to external load as two explicit
physical rails ... enumerate every transition ... A missing interface cannot
be considered 0-ohm."  Until those rails exist as geometry, the 100 A output
path is an arithmetic assumption, not a board feature.

This module is the offline half: it lays the two rails from the pads that are
actually on the routed candidate -- the eight SR source tabs (PGND), the output
capacitor pads, the four provisional transformer centre-tap pads (VOUT) and
``J_OUT`` -- and checks every segment against the committed readback with the
same clearance and endpoint rules ``route_driver_eco`` uses.  It does not
apply anything; ``--emit-js`` prints the body that would create these lines.

Facts this draft does NOT assert:

* The rails are 2.0 mm copper -- layer 1 for both runs and the PGND bus, layer 2
  only for the VOUT trunk that has to cross the PGND rail (two vias).  2 mm at
  100 A is not an ampacity claim; the real high-current interface is the output
  busbar/inlay (G2).  Pad-to-rail necks are 1.0 mm: a 2 mm neck cannot clear the
  SEC / drain pads 0.86-1.0 mm away on the source tabs.
* The CTAP endpoints are the 24 design-owned provisional pads, not vendor
  terminals, so the VOUT connection will move when the winding terminals are
  frozen.
* The output capacitor bank is one placeholder part on this board (15 x 470 uF
  is still TO SELECT and the ESR screen does not yet close), so the "local
  Cout" branch here reaches the placeholder only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import route_driver_eco as R

HERE = Path(__file__).resolve().parent
READBACK = HERE / "driver_route_readback.json"
READBACK_OUT = HERE / "power_rails_readback.json"
PLAN_OUT = HERE / "power_rail_plan.json"
REPORT_OUT = HERE / "power_rails_report.json"
CANDIDATE = "dcx_main_board_g1_power_rails.eprj2"

RAIL_W = 2.0           # the two rails
LEAD_W = 1.0           # pad -> rail leads; a 2 mm lead cannot clear the neighbours
RAIL_Y = 96.0          # PGND rail: below the gate resistors (y 88), above J_OUT
VOUT_BUS_Y = 35.5      # below the transformer envelopes (y <= 32.7), above CT (y 37)
SR_TAB_Y = 84.470      # SR1..4 source tab centre (readback), y grows downward

#: SR source tab centres read back from the routed candidate.
SR_TABS = (13.401, 23.401, 51.399, 61.399, 89.400, 99.400, 127.401, 137.401)
#: CTAP provisional pads (VOUT) and the x each dodge drops through.  A straight
#: drop at the pad x would run through the SEC_B pad 7 mm below it, so each drop
#: steps into the inter-transformer gap first.
CTAP_DODGE = ((37.0, 39.0), (75.0, 77.0), (113.0, 115.0), (151.0, 153.0))
#: The VOUT trunk crosses the PGND rail, so it leaves through a via and returns
#: to layer 1 only at the J_OUT.1 stub.
VOUT_VIA_LEFT = (4.3, 49.0)
VOUT_VIA_RIGHT = (73.5, 110.0)


def plan() -> dict[str, dict]:
    """Layer-1 polylines for both rails, in board mm (Y down)."""
    pgnd_leads = [[(x, SR_TAB_Y), (x, RAIL_Y)] for x in SR_TABS]
    return {
        "VOUT": {"width": LEAD_W, "paths": [
            # CTAP pad -> dodge -> bus.
            *[[(p, 20.0), (d, 20.0), (d, VOUT_BUS_Y)] for p, d in CTAP_DODGE],
            # The bus itself carries the full output current.
            [(CTAP_DODGE[0][1], VOUT_BUS_Y), (CTAP_DODGE[-1][1], VOUT_BUS_Y)],
            # Cout placeholder -> via -> J_OUT.1 (the J_OUT stub closes the run).
            [(4.3, 47.0), VOUT_VIA_LEFT],
            [(VOUT_VIA_RIGHT[0], VOUT_VIA_RIGHT[1]), (73.5, 116.0)],
        ]},
        "PGND": {"width": LEAD_W, "paths": [
            [(5.7, 47.0), (5.7, RAIL_Y)],
            [(78.5, RAIL_Y), (78.5, 116.0)],
            *pgnd_leads,
        ]},
    }


def bus() -> dict[str, dict]:
    """The two full-width rail runs (2 mm) and the VOUT layer-2 trunk."""
    return {
        "PGND": {"width": RAIL_W, "paths": [
            [(5.7, RAIL_Y), (SR_TABS[-1], RAIL_Y)]]},
        "VOUT": {"width": RAIL_W, "layer": 2, "paths": [
            [(VOUT_VIA_LEFT[0], VOUT_VIA_LEFT[1]),
             (VOUT_VIA_LEFT[0], VOUT_VIA_RIGHT[1]),
             VOUT_VIA_RIGHT]]},
    }


def vias() -> list[dict]:
    return [{"net": "VOUT", "x": VOUT_VIA_LEFT[0], "y": VOUT_VIA_LEFT[1],
             "hole": R.VIA_HOLE, "diameter": R.VIA_DIAMETER},
            {"net": "VOUT", "x": VOUT_VIA_RIGHT[0], "y": VOUT_VIA_RIGHT[1],
             "hole": R.VIA_HOLE, "diameter": R.VIA_DIAMETER}]


def copper() -> list[dict]:
    """Everything this draft creates, as one plan list for the shared checker."""
    return [plan(), bus()]


def plans_with_existing_route() -> list:
    """The rails plus the driver increment already on the routed candidate.

    The rails are applied on top of that copper, so checking them alone would
    miss a rail crossing a driver trace.
    """
    return [R.PLAN, R.STUBS, R.BOTTOM, *copper()]


def vias_with_existing_route() -> list[dict]:
    return [*R.VIAS, *vias()]


def problems(readback: Path = READBACK) -> list[dict]:
    """Offline conflicts and endpoint failures against the readback."""
    pads = R.load_pads(readback)
    return R.check_plan(pads, plans_with_existing_route(),
                        vias=vias_with_existing_route())


def summary(readback: Path = READBACK) -> dict:
    """The route facts a reviewer needs, computed from the plan and readback."""
    pads = R.load_pads(readback)
    segs = R.segments(copper())
    rails = {}
    for net in ("VOUT", "PGND"):
        mine = [s for s in segs if s["net"] == net]
        length = sum(math.dist(s["a"], s["b"]) for s in mine)
        ends = {(x, y) for s in mine for x, y in (s["a"], s["b"])}
        # Provisional pads have no ref on the board; name them by position so the
        # report never hides which terminal a rail actually reaches.
        refs = sorted({f"{p['ref']}.{p['pin']}" if p["ref"]
                       else f"{p['net']}@({p['x']:.2f},{p['y']:.2f})"
                       for p in pads
                       if p["net"] == net
                       and any(math.dist((p["x"], p["y"]), e) <= 0.02 for e in ends)})
        layers = sorted({s["layer"] for s in mine})
        widths = sorted({s["width"] for s in mine})
        vias_on_net = [v for v in vias() if v["net"] == net]
        rails[net] = {"segments": len(mine), "length_mm": round(length, 3),
                      "layers": layers, "widths_mm": widths,
                      "endpoint_refs": refs,
                      "vias": [[v["x"], v["y"]] for v in vias_on_net]}
    return {
        "status": "DRAFT_TWO_RAILS_NOT_AMPACITY_QUALIFIED",
        "readback": READBACK.name,
        "rails": rails,
        "not_qualified": [
            "the rail widths are shapes, not an ampacity claim; the high-current "
            "interface is the G2 output busbar/inlay",
            "the CTAP endpoints are provisional pads, not vendor terminals",
            "the output capacitor bank is one placeholder part, not 15 x 470 uF",
            "no bolt, busbar or separable joint is modelled here",
        ],
    }


def verify(readback: Path = READBACK_OUT) -> dict:
    """Rebuild the increment record from a fresh reopen readback of the candidate.

    The readback contains the driver increment as well, so coverage and vias are
    checked against the union, not against the rails alone -- a rail that was
    never created must show up as a coverage problem, not be masked by the
    driver's copper.
    """
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    lines = R.lines_from_readback(readback)
    rb_vias = R.vias_from_readback(readback)
    line_problems = R.verify_lines(plans_with_existing_route(), lines)
    via_problems = R.verify_vias(vias_with_existing_route(), rb_vias)
    base = json.loads((HERE / "driver_readback.json").read_text(encoding="utf-8"))["value"]
    old = {c["ref"]: (c["X"], c["Y"]) for c in base["components"]}
    drift = [{"ref": c["ref"], "dx_mil": round(c["X"] - old[c["ref"]][0], 4),
              "dy_mil": round(c["Y"] - old[c["ref"]][1], 4)}
             for c in value["components"] if c["ref"] in old
             and (abs(c["X"] - old[c["ref"]][0]) > 1e-6 or abs(c["Y"] - old[c["ref"]][1]) > 1e-6)]
    counts_ok = (len(value["components"]) == 77 and len(value["pads"]) == 299
                 and len(value["nets"]) == 65 and value["polylines"] == 38)
    rail_segs = R.segments(copper())
    return {
        "date": "2026-11-10",
        "status": "G1_POWER_RAILS_ON_CANDIDATE_NOT_FOR_FAB",
        "board": CANDIDATE,
        "geometry_evidence": "NATIVE_REOPEN_READBACK",
        "native_drc_passed": False,
        "layout_counts": {"components": len(value["components"]), "pads": len(value["pads"]),
                          "nets": len(value["nets"]), "polylines": value["polylines"],
                          "unchanged": counts_ok},
        "lines": {"readback": len(lines),
                  "by_layer": {str(n): sum(1 for s in lines if s.get("layer") == n)
                               for n in sorted({s.get("layer") for s in lines})},
                  "planned_segments": len(R.segments(plans_with_existing_route())),
                  "power_rail_segments": len(rail_segs),
                  "power_rail_length_mm": round(sum(math.dist(s["a"], s["b"])
                                                     for s in rail_segs), 3),
                  "coverage_problems": line_problems},
        "vias": {"planned": len(vias_with_existing_route()), "readback": len(rb_vias),
                 "power_rail_vias": [[v["x"], v["y"]] for v in vias()],
                 "problems": via_problems},
        "placement_drift": drift,
        "power_rail_plan_status": summary()["status"],
        "native_drc": {"source": "driver_drc_raw.json (route candidate, before the rails)",
                       "why_not_run_here": "the candidate has changed; re-running DRC is a "
                                           "separate open/close and is not claimed by this report"},
        "limitations": [
            "The VOUT endpoints are the 24 design-owned provisional pads, not vendor terminals.",
            "Cout is one placeholder part; the 15 x 470 uF bank is not qualified (ESR screen fails).",
            "The 2 mm rails are shapes, not an ampacity claim; 100 A is the G2 busbar/inlay.",
            "Only the driver increment and these two rails are routed; every other net is open.",
            "Native DRC has not been re-run on this candidate; the route candidate's raw result "
            "is not a pass (0 physical errors, 224 connection errors).",
            "This does not change the NOT_FOR_FAB gate.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="offline clearance/endpoint check")
    ap.add_argument("--emit-js", action="store_true", help="print the LCEDA body")
    ap.add_argument("--write-plan", action="store_true", help="write power_rail_plan.json")
    ap.add_argument("--verify", action="store_true",
                    help="build power_rails_report.json from a fresh reopen readback")
    args = ap.parse_args(argv)
    if args.emit_js:
        print(R.emit_js(copper(), vias()))
        return 0
    if args.verify:
        report = verify()
        REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8", newline="\n")
        ok = (report["layout_counts"]["unchanged"]
              and not report["lines"]["coverage_problems"]
              and not report["vias"]["problems"]
              and not report["placement_drift"])
        print(json.dumps({"ok": ok, "lines": report["lines"], "vias": report["vias"],
                          "drift": report["placement_drift"]}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    issues = problems()
    for p in issues:
        print(p)
    if args.write_plan:
        PLAN_OUT.write_text(json.dumps(summary() | {"problems": issues}, indent=2,
                                       ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {PLAN_OUT}")
    print("power rails ok: 2 rails, 0 problems" if not issues
          else f"power rails FAILED: {len(issues)} problems")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
