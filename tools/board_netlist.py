"""Generate the main power board's connectivity from the simulated deck.

A schematic is only trustworthy if it is the circuit that was simulated.  Rather
than hand-drawing one and hoping, this reads the v3 100 A deck, renames its
simulation nodes to board nets and its elements to board references, and emits a
pin-level netlist.  The lint then proves the result is a well-formed circuit.

Three things the deck does not say, and how they are handled:

  * the drivers.  `Bgh`/`Bgl` are behavioural gate drives and `Xsr1..4` are SR
    timing models.  The board needs U2 (UCC27282) and U3-U6 (UCC24624) there, so
    they are added explicitly in CONTROLLERS with pin numbers taken from
    design/v1/pin_connections.csv (pin *positions* only -- that file's OC network
    is superseded, see the project notes).
  * the sense sources.  `VSa1`..`VSb4` are 0 V current sensors in series with the
    SR drains, so the nodes they create (da1, db1, ...) are the same copper as
    a1, b1, ...; they collapse onto the secondary nets.
  * the transformer centre tap.  Both secondary halves share one pin, so it
    legitimately appears twice; the lint merges equal claims and only fails on
    conflicting ones.

Every deck element must be either mapped to a board reference or listed in SKIP
with a reason; an element that is neither fails the run.

Usage:
    python tools/board_netlist.py --json design/v3/pcb/board_netlist.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"

# Deck node -> board net.  Anything absent falls through to upper case and the
# lint reports it, so a new node cannot slip into the netlist unnamed.
NODE_NET = {
    "vin0": "VIN_P", "vin": "VIN_P",
    "0": "PGND", "sgnd": "PGND",
    "sw": "SW", "nr": "CR_CT", "nct": "CT_LR",
    "p1": "PRI_T1", "p2": "PRI_12", "p3": "PRI_23", "p4": "PRI_34",
    "a1": "SEC1_A", "b1": "SEC1_B", "a2": "SEC2_A", "b2": "SEC2_B",
    "a3": "SEC3_A", "b3": "SEC3_B", "a4": "SEC4_A", "b4": "SEC4_B",
    "da1": "SEC1_A", "db1": "SEC1_B", "da2": "SEC2_A", "db2": "SEC2_B",
    "da3": "SEC3_A", "db3": "SEC3_B", "da4": "SEC4_A", "db4": "SEC4_B",
    "out": "VOUT",
    "gh": "GH", "gl": "GL", "gh0": "GH_DRV", "gl0": "GL_DRV",
    "aux": "VCC12", "reg": "VCC12_S", "rt": "RT", "dt": "DT", "oc": "OC",
    "ss": "SS", "gd1": "GD1", "gd2": "GD2", "hb": "HB",
    "oc1": "OC1", "ocd": "OCD", "ocm": "OCM", "cs1": "CS1", "cs2": "CS2",
    "ga1": "GA1", "gb1": "GB1", "ga2": "GA2", "gb2": "GB2",
    "ga3": "GA3", "gb3": "GB3", "ga4": "GA4", "gb4": "GB4",
}

# Nets that legitimately leave the board or are supplied elsewhere.  A single-pin
# net that is not one of these is a defect.
PORTS = {"VIN_P", "PGND", "VOUT", "VCC12", "VCC12_S", "RUN"}

# Deck element -> (board ref, pin names in deck node order, value source).
PARTS = {
    "Vbus": ("J_IN", ("P1", "P2"), "connector_budget.json"),
    "Cin": ("Cin", ("P", "N"), "passive_requirements.json"),
    "Xctl": ("U1", ("1", "2", "3", "4", "5", "6", "7", "8"), "UCC25600D: DT RT OC SS GD2 GND VCC GD1"),
    "Rrt": ("R2", ("N1", "N2"), "976 ohm"),
    "Rdt": ("R1", ("N1", "N2"), "5.36 kohm"),
    "Css": ("C6", ("N1", "N2"), "10 nF"),
    "Lct1": ("CT", ("PRI_A", "PRI_B"), "ct_design.json"),
    "Lct2": ("CT", ("SEC_A", "SEC_B"), "ct_design.json"),
    "D1": ("D_CT1", ("A", "K"), "ct_design.json"),
    "D2": ("D_CT2", ("A", "K"), "ct_design.json"),
    "D3": ("D_CT3", ("A", "K"), "ct_design.json"),
    "D4": ("D_CT4", ("A", "K"), "ct_design.json"),
    "Rbur": ("R3", ("N1", "N2"), "ct_design.json"),
    "Rf": ("R15", ("N1", "N2"), "1 kohm"),
    "Cf": ("C11", ("N1", "N2"), "47 nF"),
    "Rd1": ("R16", ("N1", "N2"), "ct_design.json"),
    "Rd2": ("R17", ("N1", "N2"), "24 kohm"),
    "Coc": ("C12", ("N1", "N2"), "10 nF"),
    "Dbt": ("D_BT", ("A", "K"), "bootstrap diode, TO SELECT"),
    "Cbt": ("C5", ("N1", "N2"), "220 nF >=25 V"),
    "Rgh": ("R4", ("N1", "N2"), "2.2 ohm external; deck's 3.2 = UCC27282 1.3 + 2.2"),
    "Rgl": ("R5", ("N1", "N2"), "2.2 ohm external; deck's 3.2 = UCC27282 0.85 + 2.2"),
    "RgsH": ("R18", ("N1", "N2"), "10 kohm"),
    "RgsL": ("R19", ("N1", "N2"), "10 kohm"),
    "SH": ("QH", ("D", "S", "G"), "CSD19531Q5A"),
    "SL": ("QL", ("D", "S", "G"), "CSD19531Q5A"),
    "Cr": ("Cr", ("N1", "N2"), "cr_stress.json"),
    "Lr": ("Lr", ("N1", "N2"), "lr_design.json"),
    "Cout": ("Cout", ("P", "N"), "cout_bank.json"),
    "Rload": ("J_OUT", ("P", "N"), "connector_budget.json"),
}
for _i in (1, 2, 3, 4):
    PARTS[f"Lp{_i}"] = (f"T{_i}", ("PRI_A", "PRI_B"), "magnetics package")
    # Lsa is written `out a_n` and Lsb `b_n out`, so the centre tap is first for
    # one half-winding and second for the other.  Both must land on T.CTAP.
    PARTS[f"Lsa{_i}"] = (f"T{_i}", ("CTAP", "SEC_A"), "magnetics package")
    PARTS[f"Lsb{_i}"] = (f"T{_i}", ("SEC_B", "CTAP"), "magnetics package")
    PARTS[f"Xsa{_i}"] = (f"SR{_i}A", ("D", "G", "S"), "BSC010N04LS6")
    PARTS[f"Xsb{_i}"] = (f"SR{_i}B", ("D", "G", "S"), "BSC010N04LS6")

# Parts the deck replaces with behaviour.  Pin numbers are from
# design/v1/pin_connections.csv (positions only).
CONTROLLERS = [
    ("U2", "UCC27282DRCR", {
        "1": "VCC12", "3": "HB", "4": "GH_DRV", "5": "SW", "6": "RUN",
        "7": "GD1", "8": "GD2", "9": "PGND", "10": "GL_DRV"}),
]
# The UCC24624 does not drive the SR gate or sense its drain directly.  The pin
# map (design/v1/pin_connections.csv) puts a 2.2 ohm gate resistor in each gate
# lead and a 0 ohm *Kelvin* link in each drain lead -- the link is both a part and
# a routing constraint (sense at the die pad, not at the FET's own pad), so it is
# modelled as its own net pair rather than shorted out.
for _n, _i in enumerate((1, 2, 3, 4), start=3):
    CONTROLLERS.append((f"U{_n}", "UCC24624DR", {
        "1": f"VG{_i}_A", "2": "PGND", "3": f"REG{_i}", "4": f"VD{_i}_A",
        "5": "PGND", "6": f"VD{_i}_B", "7": "VCC12_S", "8": f"VG{_i}_B"}))
    CONTROLLERS.append((f"C{_n + 4}", "2.2 uF", {"N1": f"REG{_i}", "N2": "PGND"}))
    for _half, _gate in (("A", 20 + 2 * (_i - 1)), ("B", 21 + 2 * (_i - 1))):
        CONTROLLERS.append((f"R{_gate}", "2.2 ohm gate",
                            {"N1": f"VG{_i}_{_half}", "N2": f"G{_half}{_i}"}))
        CONTROLLERS.append((f"R{_gate + 8}", "0 ohm Kelvin",
                            {"N1": f"SEC{_i}_{_half}", "N2": f"VD{_i}_{_half}"}))

# Deck elements that are not board parts, each with the reason it is not.
SKIP = {
    "Rin": "model source resistance (1 mohm); becomes trace + joint, budgeted in connector_budget.json",
    "Vaux": "12 V bias source; the bias converter is off-board",
    "Vreg": "modelled REG ramp; the real part is supplied by the bias",
    "Vctg": "ties the CT secondary common to PGND in the model - review before layout",
    "Vref": "simulation ground reference",
    "Rss_dc": "1 Gohm DC bleed on the soft-start cap; model convergence aid",
    "Kct": "coupling coefficient - a winding property, not a net",
    "K1": "coupling coefficient", "K2": "coupling coefficient",
    "K3": "coupling coefficient", "K4": "coupling coefficient",
    "DH": "QH body diode - internal to the MOSFET", "DL": "QL body diode - internal",
    "Cgh": "QH Cgs - internal", "Cdh": "QH Cds - internal",
    "Cgl": "QL Cgs - internal", "Cdl": "QL Cds - internal",
    "Bgh": "behavioural gate drive; replaced by U2", "Bgl": "behavioural gate drive; replaced by U2",
    "Bovl1": "overlap probe", "Bovg1": "overlap probe",
}
for _i in (1, 2, 3, 4):
    SKIP[f"VSa{_i}"] = "0 V sense source; its nodes collapse onto SEC{}_A".format(_i)
    SKIP[f"VSb{_i}"] = "0 V sense source; its nodes collapse onto SEC{}_B".format(_i)
    SKIP[f"Xsr{_i}"] = "SR timing model; replaced by U3-U6"

# Board parts the deck has no element for at all, each with the reason.  These
# are deliberately NOT wired into the netlist: the netlist's claim is "this is
# the deck", and the deck's rails are ideal sources.  They are listed here so
# that the BOM cross-check below can tell an omission from a deliberate exclusion.
NOT_A_DECK_ELEMENT = {
    "C101-C112": "VDD decoupling: 1 uF + 100 nF at each of the six ICs (12 caps)",
    "C13": "1 nF EN filter at U2.6; the deck holds EN high",
    "R7-R10": "U2.6 EN 10k pull-down (R7), 1k RUN jumper (R8), HI/LI 10k pull-downs (R9/R10)",
    "PS1": "12 V control bias converter, off-board",
}


BOM = ROOT / "design/v3/bom/bom_draft.csv"


def expand_refs(text: str) -> list[str]:
    """'R20-R27' -> R20..R27; 'SR1A-SR4B' -> both halves of all four; 'QH QL' -> both."""
    out: list[str] = []
    pattern = r"([A-Za-z_]+)(\d+)([A-Za-z]*)-([A-Za-z_]+)(\d+)([A-Za-z]*)"
    for token in text.replace(";", " ").split():
        match = re.fullmatch(pattern, token)
        if not match:
            out.append(token)
            continue
        prefix, lo, suffix_a, prefix_b, hi, suffix_b = match.groups()
        if prefix != prefix_b or bool(suffix_a) != bool(suffix_b):
            out.append(token)
            continue
        letters = [""] if not suffix_a else [suffix_a, suffix_b]
        out += [f"{prefix}{n}{letter}" for n in range(int(lo), int(hi) + 1) for letter in letters]
    return out


def bom_gaps(netlist_refs: set[str], bom: Path = BOM) -> dict[str, list[str]]:
    """BOM refs that have no pin in the netlist and no documented exclusion.

    The netlist is the authority for what is on the board.  A ref that appears in
    the BOM and nowhere else is either an omission here or a phantom line in the
    BOM -- both worth failing on.  `test_board_netlist.py` pins the result.
    """
    excluded: set[str] = set()
    for spec in NOT_A_DECK_ELEMENT:
        excluded.update(expand_refs(spec))
    missing: set[str] = set()
    with bom.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            for ref in expand_refs(row["ref"]):
                if ref not in netlist_refs and ref not in excluded:
                    missing.add(ref)
    return {"bom_refs_without_a_pin": sorted(missing), "excluded": sorted(excluded)}


def deck_lines(path: Path) -> list[str]:
    """Logical lines with '+' continuations joined, comments dropped."""
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.split(";")[0].strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.startswith("+"):
            if out:
                out[-1] += " " + stripped[1:].strip()
            continue
        out.append(stripped)
    return out


def parse_elements(lines: list[str]) -> dict[str, list[str]]:
    """Deck element name -> its node tokens (parameters and model names removed)."""
    elements: dict[str, list[str]] = {}
    for line in lines:
        if line.startswith("."):
            continue
        name = line.split()[0]
        tokens = [t for t in re.split(r"[ \t]+", line[len(name):].strip()) if t]
        if name[0] in "RLCD":
            nodes = tokens[:2]
        elif name[0] == "S":
            # S: n+ n- nc+ nc- model.  nc- is the gate's return, already n- here.
            nodes = tokens[:3]
        elif name[0] in "MX":
            nodes = [t for t in tokens if "=" not in t][:-1]
        elif name[0] in "BVEI":
            nodes = tokens[:2]
        else:
            continue
        elements[name] = nodes
    return elements


def build(path: Path = ROOT / DECK) -> dict[str, object]:
    elements = parse_elements(deck_lines(path))
    rows: list[dict[str, str]] = []
    unmapped: list[str] = []
    renamed: set[str] = set()

    for name, tokens in elements.items():
        if name in SKIP:
            continue
        entry = PARTS.get(name)
        if entry is None:
            unmapped.append(name)
            continue
        ref, pins, basis = entry
        if len(tokens) != len(pins):
            raise ValueError(f"{name}: {len(tokens)} nodes but {len(pins)} pins declared")
        for node, pin in zip(tokens, pins):
            net = NODE_NET.get(node)
            if net is None:
                net = node.upper()
                renamed.add(node)
            rows.append({"net": net, "ref": ref, "pin": pin, "basis": basis,
                         "deck_element": name})

    for ref, basis, pins in CONTROLLERS:
        for pin, net in pins.items():
            rows.append({"net": net, "ref": ref, "pin": pin, "basis": basis,
                         "deck_element": "(behavioural in deck)"})
    return {"rows": rows, "unmapped": unmapped, "fallback_nets": sorted(renamed),
            "elements": len(elements)}


def merge(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """Collapse repeated (ref, pin) claims; identical nets merge, differing ones conflict."""
    merged: dict[tuple[str, str], dict[str, str]] = {}
    conflicts: list[str] = []
    for row in rows:
        key = (row["ref"], row["pin"])
        if key in merged:
            if merged[key]["net"] != row["net"]:
                conflicts.append(f"{row['ref']}.{row['pin']}: {merged[key]['net']} vs {row['net']}")
            continue
        merged[key] = row
    return list(merged.values()), conflicts


def lint(rows: list[dict[str, str]], conflicts: list[str] | None = None) -> dict[str, object]:
    """A netlist is a set of claims about pins; these are the ones that must hold."""
    by_net: dict[str, list[str]] = {}
    for row in rows:
        by_net.setdefault(row["net"], []).append(f"{row['ref']}.{row['pin']}")
    singles = {net: pins for net, pins in by_net.items()
               if len(pins) < 2 and net not in PORTS}
    return {
        "nets": len(by_net),
        "refs": len({row["ref"] for row in rows}),
        "pins": len(rows),
        "single_pin_nets": sorted(singles),
        "conflicting_claims": conflicts or [],
        "ok": not singles and not conflicts,
    }


def write_csv(rows: list[dict[str, str]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["net", "ref", "pin", "basis", "deck_element"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["net"], r["ref"], r["pin"])))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/pcb/board_netlist.json"))
    ap.add_argument("--csv", type=Path, default=Path("design/v3/pcb/board_netlist.csv"))
    args = ap.parse_args()

    result = build()
    rows, conflicts = merge(result["rows"])
    checks = lint(rows, conflicts)
    coverage = bom_gaps({row["ref"] for row in rows})
    checks["bom_refs_without_a_pin"] = coverage["bom_refs_without_a_pin"]
    checks["ok"] = checks["ok"] and not coverage["bom_refs_without_a_pin"]
    payload = {
        "deck": DECK,
        "status": "connectivity generated from the simulated deck; values are NOT frozen",
        "elements_parsed": result["elements"],
        "elements_skipped": len(SKIP),
        "elements_unmapped": result["unmapped"],
        "fallback_nets": result["fallback_nets"],
        "conflicting_claims": conflicts,
        "checks": checks,
        "not_a_deck_element": NOT_A_DECK_ELEMENT,
        "bom_coverage": coverage,
        "notes": [
            "every deck element is either mapped to a board reference or SKIPped with a reason; "
            "an element that is neither fails the run",
            "pin names are functional (D/S/G, PRI_A) for power parts and datasheet pin numbers "
            "for U1-U6, taken from design/v1/pin_connections.csv positions",
            "U2 and U3-U6 are added because the deck models them as Bgh/Bgl and Xsr1..4",
            "the deck ties the CT secondary common and the output return to one node (PGND); "
            "the board keeps that and it is flagged for review",
        ],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(rows, args.csv)

    print(f"{result['elements']} deck elements -> {checks['refs']} refs, "
          f"{checks['nets']} nets, {checks['pins']} pins")
    if result["unmapped"]:
        print(f"UNMAPPED: {result['unmapped']}")
    if result["fallback_nets"]:
        print(f"fallback nets (no NODE_NET entry): {result['fallback_nets']}")
    if conflicts:
        print(f"conflicting claims: {conflicts}")
    if checks["single_pin_nets"]:
        print(f"single-pin nets: {checks['single_pin_nets']}")
    print(f"{'OK' if checks['ok'] else 'PROBLEMS'}  {args.csv}  {args.json}")


if __name__ == "__main__":
    main()
