"""The two CT current-sense nets (CS1 / CS2) as routed, layer-aware geometry.

The frozen G1 plan (docs/D1_EXECUTION_KIT/49_... §day 3-5) asks for the SR and
Cout zone allocation, independent Kelvin, and the output inlay interface.  The
zone allocation is blocked on the magnetics' physical terminals and on a Cout
MPN that survives the ESR screen; the Kelvin list is not.  This module routes
the two 3-pad sense nets the README's Kelvin table already names:

* ``CS1``: CT ``SEC_A`` (104, 56) -> D_CT1.1 (109, 70.95) and D_CT3.3 (119, 70)
* ``CS2``: CT ``SEC_B`` (104, 48) -> D_CT2.1 (115, 70.95) and D_CT4.3 (125, 70)

CS1 crosses CS2's corridor on the way, so CS1 leaves through three vias and runs
on layer 2 between (106.2, 56) and (119, 69); CS2 stays on layer 1.  Width is
0.3 mm -- the same sense width as the driver increment -- and that is not a
current rating.

Not asserted: the SR gate/drain Kelvin pairs (the ``GA*/GB*`` groups) are not
routed, the CT terminals are still the design-owned provisional pads, and the
four SR local layouts are not placed.  ``apply_kelvin.py`` applies this plan to
a fresh copy of ``dcx_main_board_g1_power_rails.eprj2`` and reads it back.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import route_driver_eco as R
import route_power_rails as P

HERE = Path(__file__).resolve().parent
READBACK = P.READBACK_OUT
READBACK_OUT = HERE / "kelvin_readback.json"
PLAN_OUT = HERE / "kelvin_plan.json"
REPORT_OUT = HERE / "kelvin_report.json"
CANDIDATE = "dcx_main_board_g1_kelvin.eprj2"

WIDTH = 0.3

KELVIN = {
    "CS1": {"width": WIDTH, "paths": [
        [(104.0, 56.0), (106.2, 56.0)],          # CT SEC_A -> via
        [(109.0, 66.5), (109.0, 70.95)],         # via -> D_CT1.1
        [(119.0, 69.0), (119.0, 70.0)],          # via -> D_CT3.3
    ]},
    "CS2": {"width": WIDTH, "paths": [
        [(104.0, 48.0), (102.0, 48.0), (102.0, 65.0), (125.0, 65.0), (125.0, 70.0)],
        [(115.0, 65.0), (115.0, 70.95)],         # branch -> D_CT2.1
    ]},
}

#: CS1 crosses CS2's y=65 corridor, so it changes layer instead of weaving.
#: The y=66.5 run passes through the via at (109, 66.5) -- no separate branch
#: (the editor merges collinear overlapping lines, so a sub-segment of this run
#: would come back as one longer line and fail the coverage check).
CS1_BOTTOM = {"CS1": {"width": WIDTH, "layer": 2, "paths": [
    [(106.2, 56.0), (106.2, 66.5), (119.0, 66.5), (119.0, 69.0)],
]}}

VIAS = [{"net": "CS1", "x": 106.2, "y": 56.0, "hole": R.VIA_HOLE, "diameter": R.VIA_DIAMETER},
        {"net": "CS1", "x": 109.0, "y": 66.5, "hole": R.VIA_HOLE, "diameter": R.VIA_DIAMETER},
        {"net": "CS1", "x": 119.0, "y": 69.0, "hole": R.VIA_HOLE, "diameter": R.VIA_DIAMETER}]


def copper() -> list[dict]:
    return [KELVIN, CS1_BOTTOM]


def vias() -> list[dict]:
    return list(VIAS)


def plans_with_existing_route() -> list:
    """Everything on the board this plan is applied to, plus the plan itself."""
    return [*P.plans_with_existing_route(), *copper()]


def vias_with_existing_route() -> list[dict]:
    return [*P.vias_with_existing_route(), *vias()]


def problems(readback: Path = READBACK) -> list[dict]:
    pads = R.load_pads(readback)
    return R.check_plan(pads, plans_with_existing_route(), vias=vias_with_existing_route())


def summary(readback: Path = READBACK) -> dict:
    pads = R.load_pads(readback)
    segs = R.segments(copper())
    nets = {}
    for net in ("CS1", "CS2"):
        mine = [s for s in segs if s["net"] == net]
        ends = {(x, y) for s in mine for x, y in (s["a"], s["b"])}
        refs = sorted({f"{p['ref']}.{p['pin']}" if p["ref"]
                       else f"{p['net']}@({p['x']:.2f},{p['y']:.2f})"
                       for p in pads
                       if p["net"] == net
                       and any(math.dist((p["x"], p["y"]), e) <= 0.02 for e in ends)})
        nets[net] = {"segments": len(mine),
                     "length_mm": round(sum(math.dist(s["a"], s["b"]) for s in mine), 3),
                     "layers": sorted({s["layer"] for s in mine}),
                     "endpoint_refs": refs}
    return {
        "status": "DRAFT_CT_KELVIN_ON_CS1_CS2",
        "readback": readback.name,
        "width_mm": WIDTH,
        "nets": nets,
        "vias": [[v["x"], v["y"]] for v in vias()],
        "not_qualified": [
            "only the two CT sense nets are routed; the SR gate/drain Kelvin pairs are not",
            "the CT terminals are design-owned provisional pads, not vendor terminals",
            "0.3 mm is a sense width, not a current rating",
            "the four SR local layouts and the Cout bank are not placed",
            "native DRC has not been run on this candidate",
        ],
    }


def verify(readback: Path = READBACK_OUT) -> dict:
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
    kelvin_segs = R.segments(copper())
    return {
        "date": "2026-11-10",
        "status": "G1_CT_KELVIN_ON_CANDIDATE_NOT_FOR_FAB",
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
                  "kelvin_segments": len(kelvin_segs),
                  "kelvin_length_mm": round(sum(math.dist(s["a"], s["b"])
                                                for s in kelvin_segs), 3),
                  "coverage_problems": line_problems},
        "vias": {"planned": len(vias_with_existing_route()), "readback": len(rb_vias),
                 "kelvin_vias": [[v["x"], v["y"]] for v in vias()],
                 "problems": via_problems},
        "placement_drift": drift,
        "kelvin_plan_status": summary()["status"],
        "limitations": [
            "CS1/CS2 only: the SR gate/drain Kelvin pairs are not routed.",
            "The CT terminals are provisional pads; CS1/CS2 will move with the vendor terminals.",
            "Only the driver increment, the two output rails and these two sense nets are "
            "routed; every other net is open.",
            "Native DRC has not been run on this candidate; the route candidate's raw result is "
            "not a pass.",
            "This does not change the NOT_FOR_FAB gate.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="offline clearance/endpoint check")
    ap.add_argument("--emit-js", action="store_true", help="print the LCEDA body")
    ap.add_argument("--write-plan", action="store_true", help="write kelvin_plan.json")
    ap.add_argument("--verify", action="store_true", help="build kelvin_report.json")
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
    print("kelvin nets ok: 2 nets, 0 problems" if not issues
          else f"kelvin nets FAILED: {len(issues)} problems")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
