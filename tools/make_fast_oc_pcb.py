"""Routed PCB for the TLV3501 fast-overcurrent ECO module.

The module exists because the D0 fast-overcurrent channel is slow in its three
RC filters, not in its comparator (see ``make_fast_oc_eco``).  The schematic
alone could not be wired onto anything, so this generator turns the same part
table into a two-layer board, routes it with the router that already does the
SR validation board, and refuses to call it done unless kicad-cli reports zero
violations and zero unconnected items.

What this board does NOT have: no latch (that is D0's CD4013), no isolation, no
bulk-energy path.  ``hardware_built`` and ``fabrication_approved`` stay false;
``NOT_FOR_FAB`` applies to the main board, not to this bench module.

Run:
    python tools/make_fast_oc_pcb.py --check
"""

from __future__ import annotations

import argparse
import json
import uuid

import make_fast_oc_eco as eco
import make_sr_fault_board_pcb as srpcb
import sr_board_router as router

OUT = eco.OUT
BOARD = "fast_oc.kicad_pcb"
REPORT = "fast_oc_pcb.json"
NS = uuid.UUID("2d7b6c55-1c8e-4a72-9d0f-3b1e5c8a6f24")

# 52 x 38 mm leaves room for four M3 holes and still fits in a 60 mm envelope.
BOARD_W_MM = 52.0
BOARD_D_MM = 38.0
MOUNTING_HOLES = ((5.0, 5.0), (47.0, 5.0), (5.0, 33.0), (47.0, 33.0))
THICKNESS_MM = 1.6
ROUTE_MM = 0.25
HOLE_COURTYARD_R_MM = 3.7
# The hole label sits 4.9 mm above the hole and the holes are 5 mm from the
# edge, so a visible label lands outside a 38 mm board (DRC: silk_edge_clearance).
# The official KiCad mounting holes hide it as well.  The SR board keeps it
# visible -- its board is bigger and its committed file must not change.
HIDE_HOLE_REFERENCE = True

# Everything on this module is a signal; there is no current path that needs a
# wider track.  0.25 mm is the SR board's signal width and clears every pad on
# a 0603 grid.
NET_WIDTHS: dict[str, float] = {}


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ------------------------------------------------------------------ placement
# Blocks keep related parts together so the router does not have to thread the
# whole board for one decoupling cap.
BLOCKS = {
    "connector": (1.0, 2.0, 12.0, 34.0),
    "reference": (13.0, 2.0, 24.0, 16.0),
    "comparator": (26.0, 2.0, 40.0, 16.0),
    "divider": (13.0, 18.0, 30.0, 31.0),
    "output": (31.0, 18.0, 50.0, 31.0),
    "probe": (1.0, 32.0, 51.0, 36.5),
}
BLOCK_OF = {
    "connector": ["J1"],
    "reference": ["U2", "R1", "C3"],
    "comparator": ["U1", "C2"],
    "divider": ["D2", "D1", "R2", "R3", "C4"],
    "output": ["C1", "R4", "R5", "R6", "R8", "Q1", "R7"],
    "probe": [f"TP{i}" for i in range(1, 9)],
}
BLOCK_ORDER = ("connector", "reference", "comparator", "divider", "output", "probe")


def _hole_rects() -> list[tuple[float, float, float, float]]:
    size = 2 * HOLE_COURTYARD_R_MM
    return [srpcb._rect(x, y, size, size) for x, y in MOUNTING_HOLES]


def placement() -> list[srpcb.Placed]:
    """Deterministic first-fit packing, largest parts first inside each block."""
    table = {p.ref: p for p in eco.parts() if p.footprint}
    unknown = sorted({r for refs in BLOCK_OF.values() for r in refs} - set(table))
    if unknown:
        raise SystemExit(f"parts with a footprint but no block: {unknown}")
    unplaced = sorted(set(table) - {r for refs in BLOCK_OF.values() for r in refs})
    if unplaced:
        raise SystemExit(f"parts with no block assignment: {unplaced}")

    def area(ref: str) -> float:
        x0, y0, x1, y1 = srpcb.courtyard_bounds(srpcb.stock_text(table[ref].footprint))
        return (x1 - x0) * (y1 - y0)

    placed: list[srpcb.Placed] = []
    obstacles = _hole_rects()
    for block in BLOCK_ORDER:
        refs = sorted(BLOCK_OF[block], key=lambda r: (-area(r), r))
        for ref in refs:
            part = table[ref]
            fp = part.footprint
            box = srpcb.courtyard_bounds(srpcb.stock_text(fp))
            x, y = srpcb._first_fit(BLOCKS[block], box, obstacles)
            item = srpcb.Placed(ref, part.value, fp, block, x, y, 0.0, box)
            placed.append(item)
            obstacles.append(item.rect)
    return sorted(placed, key=lambda p: srpcb._natural(p.ref))


# ------------------------------------------------------------------ routing
def net_names(parts: list) -> list[str]:
    names = sorted({n for p in parts for n in p.nets.values()})
    return [""] + names


def pads_of(placed: list[srpcb.Placed]) -> list[router.Pad]:
    table = {p.ref: p for p in eco.parts() if p.footprint}
    names = net_names(list(table.values()))
    index = {name: i for i, name in enumerate(names)}
    pads: list[router.Pad] = []
    for p in placed:
        part = table[p.ref]

        def net_of(ref: str, number: str, _index=index, _part=part) -> int:
            name = _part.nets.get(number)
            return _index[name] if name else -1

        pads.extend(router.extract_pads(srpcb.stock_text(p.footprint), p.ref,
                                        p.x, p.y, net_of))
    return pads


def route_plan(pads: list[router.Pad], names: list[str]) -> tuple[dict[int, float], list[int]]:
    """Widest fan-out first, then long nets; every net is 0.25 mm.

    Ordering by pad count puts the shared rails (V5, PGND) down before the
    two-pad signals, which is what the router's rip-up pass expects: the nets
    that many parts depend on should not be the ones displaced.
    """
    counts: dict[int, int] = {}
    for pad in pads:
        if pad.net >= 0:
            counts[pad.net] = counts.get(pad.net, 0) + 1
    order = sorted(counts, key=lambda n: (-counts[n], names[n]))
    widths = {n: NET_WIDTHS.get(names[n], ROUTE_MM) for n in order}
    return widths, order


def end_distance(pads: list[router.Pad]) -> float:
    """Longest pad-to-pad distance inside one net: a lower bound on track length."""
    worst = 0.0
    by_net: dict[int, list[router.Pad]] = {}
    for pad in pads:
        if pad.net >= 0:
            by_net.setdefault(pad.net, []).append(pad)
    for group in by_net.values():
        for a in group:
            for b in group:
                worst = max(worst, ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5)
    return worst


# The router keeps 0.40 mm of extra room around a pad whose net is still
# unrouted so that later nets cannot seal its exit.  On this board that reserve
# is wider than the gap it is guarding: the inner SOT-23-6 pins sit 1.375 mm
# from the opposite pad row, which fits a 0.25 mm track (0.775 mm of margin)
# but not the reserve on both sides (1.575 mm).  Six deterministic net orders
# left the board at 40/42 or 41/42 with it on and reached 42/42 with it off,
# while kicad-cli still reported no clearance violation -- so here the reserve
# bought nothing and sealed the pins instead.  The value is in the report
# rather than only in this comment.
ESCAPE_MM = 0.0


def route(placed: list[srpcb.Placed] | None = None) -> router.RouteResult:
    placed = placed or placement()
    pads = pads_of(placed)
    names = net_names([p for p in eco.parts() if p.footprint])
    widths, order = route_plan(pads, names)
    return router.route(pads, BOARD_W_MM, BOARD_D_MM, list(MOUNTING_HOLES),
                        widths=widths, order=order, escape_mm=ESCAPE_MM)


# ------------------------------------------------------------------ board file
_LAYER_NAME = {0: "F.Cu", 1: "B.Cu"}


def copper_lines(result: router.RouteResult) -> list[str]:
    out = []
    for k, s in enumerate(result.segments):
        out.append(f'\t(segment (start {s.x0:g} {s.y0:g}) (end {s.x1:g} {s.y1:g})'
                   f' (width {s.width:g}) (layer "{_LAYER_NAME[s.layer]}")'
                   f' (net {s.net}) (uuid "{uid("segment", str(k))}"))\n')
    for k, v in enumerate(result.vias):
        out.append(f'\t(via (at {v.x:g} {v.y:g}) (size {v.radius * 2:g})'
                   f' (drill {router.VIA_DRILL_MM:g}) (layers "F.Cu" "B.Cu")'
                   f' (net {v.net}) (uuid "{uid("via", str(k))}"))\n')
    return out


def board_file(placed: list[srpcb.Placed] | None = None,
               result: router.RouteResult | None = None) -> str:
    placed = placed or placement()
    result = result if result is not None else route(placed)
    table = {p.ref: p for p in eco.parts() if p.footprint}
    names = net_names(list(table.values()))
    index = {name: i for i, name in enumerate(names)}
    w, d = BOARD_W_MM, BOARD_D_MM
    out = [
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"make_fast_oc_pcb\")\n"
        "\t(generator_version \"10.0\")\n"
        f"\t(general (thickness {THICKNESS_MM:g}))\n"
        "\t(paper \"A4\")\n\t(title_block\n"
        "\t\t(title \"DCX 48V-2V - TLV3501 fast overcurrent ECO module\")\n"
        "\t\t(comment 1 \"two-layer signal module; no latch, no isolation\")\n"
        "\t\t(comment 2 \"bench module; hardware not built\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        # Declaring mask and paste is not cosmetic: kicad-cli plots only the
        # layers this table lists and drops the rest without a word.
        '\t\t(34 "B.Paste" user)\n\t\t(35 "F.Paste" user)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        '\t\t(38 "B.Mask" user)\n\t\t(39 "F.Mask" user)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        '\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        '\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n'
        "\t(setup (pad_to_mask_clearance 0))\n"
    ]
    for i, name in enumerate(names):
        out.append(f'\t(net {i} "{name}")\n')
    for name, (x0, y0, x1, y1) in {
        "top": (0, 0, w, 0), "right": (w, 0, w, d),
        "bottom": (w, d, 0, d), "left": (0, d, 0, 0),
    }.items():
        out.append(f'\t(gr_line (start {x0:g} {y0:g}) (end {x1:g} {y1:g})'
                   f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts")'
                   f' (uuid "{uid("edge", name)}"))\n')
    for i, (x, y) in enumerate(MOUNTING_HOLES, start=1):
        out.append(srpcb._embed(
            srpcb.mounting_hole_source(hide_reference=HIDE_HOLE_REFERENCE),
            srpcb.HOLE_LIB_ID, f"H{i}", "MountingHole_3.2mm_M3", {}, names, x, y,
            0.0))
    for p in placed:
        part = table[p.ref]
        nets = {num: index[name] for num, name in part.nets.items()}
        out.append(srpcb._embed(srpcb.stock_text(p.footprint), p.footprint, p.ref,
                                p.value, nets, names, p.x, p.y, p.rot, dnp=part.dnp))
    out.extend(copper_lines(result))
    out.append(")\n")
    return "".join(out)


def used_footprints() -> set[str]:
    return {p.footprint for p in eco.parts() if p.footprint} | {srpcb.HOLE_LIB_ID}


def fp_lib_table() -> str:
    libs = sorted({p.split(":", 1)[0] for p in used_footprints()} - {"dcx"})
    rows = "".join(
        f'  (lib (name "{lib}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/../../hardware/stock_footprints/{lib}.pretty")\n'
        f'    (options "")(descr "vendored KiCad 10.0.6 footprint"))\n'
        for lib in libs)
    # The mounting hole lives in a generated library beside the board; without
    # this row kicad-cli reports it as an unknown library and then skips the
    # courtyard checks on it.
    rows += ('  (lib (name "dcx")(type "KiCad")(uri "${KIPRJMOD}/dcx.pretty")'
             '(options "")(descr "generated footprints: mounting hole"))\n')
    return ("(fp_lib_table\n"
            '  (version 7)\n'
            + rows
            + ")\n")


def project_file() -> str:
    """The schematic's project file -- one file, one generator.

    The board lives beside ``fast_oc.kicad_pro`` and cannot have a second one.
    Emitting our own copy would make the courtyard severity depend on which
    generator ran last, so this defers to the module that owns it.
    """
    return eco.project_file()


# ------------------------------------------------------------------ checks
def report(placed: list[srpcb.Placed] | None = None,
           result: router.RouteResult | None = None,
           drc: dict[str, list[dict]] | None = None) -> dict:
    placed = placed or placement()
    result = result if result is not None else route(placed)
    pads = pads_of(placed)
    names = net_names([p for p in eco.parts() if p.footprint])
    net_count = len(names) - 1
    return {
        "kind": "TLV3501_FAST_OC_MODULE_PCB",
        "evidence_level": "GENERATED_BOARD_AND_DRC_NOT_HARDWARE",
        "hardware_built": False,
        "fabrication_approved": False,
        "board_mm": [BOARD_W_MM, BOARD_D_MM],
        "layers": 2,
        "parts_placed": len(placed),
        "nets": net_count,
        "pads": len(pads),
        "segments": len(result.segments),
        "vias": len(result.vias),
        "escape_reserve_mm": ESCAPE_MM,
        "escape_reserve_note": (
            "0.0 on this board: the 0.40 mm reserve is wider than the 1.375 mm "
            "gap between the SOT-23-6 pad rows, so it sealed the inner pins"),
        "connections_attempted": result.connections_attempted,
        "connections_made": result.connections_made,
        "unrouted": list(result.unrouted),
        "longest_single_net_span_mm": round(end_distance(pads), 2),
        "drc": None if drc is None else {
            "violations": len(drc["violations"]),
            "unconnected_items": len(drc["unconnected_items"]),
            "schematic_parity": len(drc["schematic_parity"]),
        },
        "limits": [
            "a routed, DRC-clean board says the netlist reached copper; it does "
            "not say the module works",
            "no latch, no isolation and no reverse-supply protection beyond D2",
            "the 5 V rail and the OCD node come from the harness; this board "
            "does not generate or measure them",
            "single-pad nets (the test points) cannot show a ratsnest line, so "
            "their connectivity is not proven by an unconnected count of zero",
        ],
    }


# ------------------------------------------------------------------ driver
def write() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    # The hole library is written first: ``board_file`` reads it back off disk
    # through ``stock_text``, so writing it afterwards would embed last run's
    # copy and the regenerated board would differ from a fresh checkout.
    (OUT / "dcx.pretty").mkdir(exist_ok=True)
    (OUT / "dcx.pretty" / "MountingHole_3.2mm_M3.kicad_mod").write_text(
        srpcb.mounting_hole_source(hide_reference=HIDE_HOLE_REFERENCE), encoding="utf-8")
    placed = placement()
    result = route(placed)
    (OUT / BOARD).write_text(board_file(placed, result), encoding="utf-8")
    (OUT / "fast_oc.kicad_pro").write_text(project_file(), encoding="utf-8")
    (OUT / "fp-lib-table").write_text(fp_lib_table(), encoding="utf-8")
    return {"placed": placed, "result": result}
    return {"placed": placed, "result": result}


def check() -> None:
    cli = srpcb.find_kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: DRC cannot be reproduced")
    board = OUT / BOARD
    data = write()
    drc = srpcb.run_drc(cli, board, OUT / "drc.json")
    for key, rows in drc.items():
        if rows:
            print(f"  {key}: {len(rows)}")
            for row in rows[:5]:
                print(f"    {row.get('type')}: {row.get('description')}")
    if drc["violations"] or drc["unconnected_items"] or drc["schematic_parity"]:
        raise SystemExit("DRC is not clean; the board is not a deliverable")
    print(f"board: {len(data['placed'])} parts, "
          f"{len(data['result'].segments)} segments, {len(data['result'].vias)} vias")
    print("DRC: 0 violations, 0 unconnected, 0 parity")
    (OUT / REPORT).write_text(
        json.dumps(report(data["placed"], data["result"], drc),
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        write()
        (OUT / REPORT).write_text(
            json.dumps(report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT / BOARD}")


if __name__ == "__main__":
    main()
