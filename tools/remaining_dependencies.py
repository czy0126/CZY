"""What still stands between the main board and a fabrication order.

``hardware/dcx_main/d1_fabrication_gate.json`` already says *which* checks
fail.  It does not say what would make each one pass, and that is the question
a reader with a calendar actually has: five of the six blockers are waiting on
something that is not another audit -- a vendor drawing, an MPN, a routed
board, a signed evidence file.

This tool is a **view** over two committed files.  It copies the gate's own
blocker list and the placeholder ECO's own counts; it does not re-derive either
and it cannot turn a blocker green.  Its only judgement is ``--check``: the
page and the JSON it renders must match what the sources say today.

Usage:
    python tools/remaining_dependencies.py --write    # rewrite json + md
    python tools/remaining_dependencies.py --check    # fail if either is stale
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text_identity import sha256_file

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "hardware/dcx_main/d1_fabrication_gate.json"
ECO = ROOT / "hardware/dcx_main/placeholder_eco.json"
OUT_JSON = ROOT / "hardware/dcx_main/remaining_dependencies.json"
OUT_MD = ROOT / "hardware/dcx_main/remaining_dependencies.md"

# Every exit is one of these.  The list is short on purpose: an exit that does
# not fit is a sign the item has not been reduced to something a person can do.
EXIT_KINDS = {
    "VENDOR_DRAWING": "a supplier returns a drawing",
    "PART_SELECTION": "an MPN is chosen and recorded against a requirement",
    "GUI_DEVICE_CHANGE": "a person swaps the device in the LCEDA editor",
    "ROUTING": "copper is drawn and passes DRC",
    "BENCH_MEASUREMENT": "a bench run produces data",
    "SIGNED_REVIEW": "a named reviewer signs an evidence file",
}


def _sha256(path: Path) -> str:
    """Canonical (LF) identity: the same file hashes the same on CI and here."""
    return sha256_file(path)


def _refs(rows: list[dict], pred) -> list[str]:
    return [row["ref"] for row in rows if pred(row)]


def build() -> dict:
    gate = json.loads(GATE.read_text(encoding="utf-8"))
    eco = json.loads(ECO.read_text(encoding="utf-8"))
    rows = eco["rows"]
    counts = gate["counts"]
    eco_counts = eco["counts"]

    missing_pads = list(counts["magnetics_missing_physical_pads"])
    # These three gate counts are lists of names, not counts of them.
    unselected = [row["ref"] for row in counts["bom_rows_not_selected"]]
    device_change = _refs(rows, lambda r: r["eco_class"] == "NATIVE_DEVICE_CHANGE")
    untraced = _refs(rows, lambda r: r.get("requirement") is None)

    exits = [
        {
            "id": "magnetics_physical_pads",
            "gate_check": "all_golden_refs_and_magnetic_physical_pads_verified",
            "blocked_by": (
                f"{len(missing_pads)} magnetics have a logical terminal name and no "
                f"vendor pad number: {', '.join(missing_pads)}.  The name matching a "
                "net is not the same as the terminal existing."),
            "refs": missing_pads,
            "exit_kind": "VENDOR_DRAWING",
            "exit": (
                "the vendor terminal drawing, answering vendor_terminal_request.json.  "
                "Then fill physical_pad/physical_pad_map_verified per terminal, "
                "re-export the native netlist, and re-run the gate."),
            "next_command": "python tools/d1_fabrication_gate.py --write",
        },
        {
            "id": "part_selection",
            "gate_check": "no_electrical_placeholders_or_unselected_bom",
            "blocked_by": (
                f"{eco_counts['placeholders']} refs carry PLACEHOLDER and "
                f"{len(unselected)} BOM rows are TO SELECT; "
                f"{eco_counts['with_verified_mpn']} have an MPN traced to a datasheet "
                f"in this repository.  {eco_counts['traced_requirements']} of the "
                f"{eco_counts['placeholders']} have a requirement a candidate can be "
                f"checked against; {eco_counts['untraced_requirements']} do not."),
            "refs_without_a_requirement": untraced,
            "bom_rows_not_selected": unselected,
            "exit_kind": "PART_SELECTION",
            "exit": (
                "one MPN per row, recorded with a datasheet in "
                "references/datasheets/ (the same rule the bench boards follow).  "
                "For the " + str(len(untraced)) + " untraced refs the first step is "
                "defining the requirement, not choosing a part: there is nothing to "
                "check a candidate against."),
            "next_command": "python tools/placeholder_eco.py --write",
        },
        {
            "id": "native_device_change",
            "gate_check": "no_electrical_placeholders_or_unselected_bom",
            "blocked_by": (
                f"{len(device_change)} refs cannot be fixed by editing a value: "
                f"{', '.join(device_change)}.  Their devices or packages are wrong, "
                "and the editor API cannot swap a device -- the value ECO can."),
            "refs": device_change,
            "exit_kind": "GUI_DEVICE_CHANGE",
            "exit": (
                "a GUI session that deletes and replaces those twelve devices in the "
                "one native project, then a re-export of the native netlist.  "
                "native_value_eco.py already reports them as ALREADY_CONFORMS for "
                "value; nothing in this repository can perform the swap."),
            "next_command": "python tools/native_value_eco.py --check",
        },
        {
            "id": "native_erc",
            "gate_check": "native_erc_evidence",
            "blocked_by": "native_erc_approved.json is absent (manual_evidence.native_erc)",
            "evidence_file": gate["manual_evidence"]["native_erc"]["path"],
            "exit_kind": "SIGNED_REVIEW",
            "exit": (
                "run ERC on the native project with --severity-all and zero violations, "
                "write the evidence file with the report path, its sha256 and the "
                "reviewer.  An ERC report nobody signed is the same as no report."),
            "next_command": None,
        },
        {
            "id": "routed_pcb",
            "gate_check": "routed_pcb_to_schematic_evidence",
            "blocked_by": (
                "the main board has no copper: the repository holds a schematic, a "
                "netlist and a placement plan, and no PCB"),
            "evidence_file": gate["manual_evidence"]["pcb_to_schematic"]["path"],
            "exit_kind": "ROUTING",
            "exit": (
                "a routed board whose DRC reports zero unconnected items, then "
                "pcb_to_schematic_verified.json binding board hash, netlist hash and "
                "the DRC report.  Unconnected items live in the DRC's second top-level "
                "array, not in violations."),
            "next_command": None,
        },
        {
            "id": "fab_package",
            "gate_check": "manufacturing_package_evidence",
            "blocked_by": "no gerbers, drill, position file or package manifest exist "
                          "for the main board",
            "evidence_file": gate["manual_evidence"]["fab_approval"]["path"],
            "exit_kind": "SIGNED_REVIEW",
            "exit": (
                "the package exported from the routed board (the two bench boards show "
                "the shape), then fabrication_approval.json.  A package that can be "
                "ordered is exactly the artefact mistaken for an approved one."),
            "next_command": None,
        },
        {
            "id": "protection_signoff",
            "gate_check": "independent_fault_shutdown_design_evidence",
            "blocked_by": "the protection channel has SPICE evidence and two bench "
                          "boards, but no measured first-article result for the main "
                          "board",
            "evidence_file": gate["manual_evidence"]["protection_design"]["path"],
            "exit_kind": "BENCH_MEASUREMENT",
            "exit": (
                "build and run the D0 and fast-OC bench boards (pcb/manufacturing/), "
                "record the measured stop time, then protection_design_approved.json "
                "from protection_design_approval_TEMPLATE.json.  The SPICE number is a "
                "floor, not a worst case: D0's common logic is not modelled."),
            "next_command": None,
        },
    ]

    blocking = list(gate["blockers"])
    declared = {row["gate_check"] for row in exits}
    return {
        "status": "MAIN_BOARD_REMAINING_DEPENDENCIES",
        "generated_by": "tools/remaining_dependencies.py",
        "note": (
            "A view over d1_fabrication_gate.json and placeholder_eco.json: every "
            "count below is copied from those two files, not re-derived.  release_"
            "approved stays false; this page cannot make it true."),
        "source": {
            "gate": {"path": "hardware/dcx_main/d1_fabrication_gate.json",
                     "sha256": _sha256(GATE),
                     "status": gate["status"],
                     "release_approved": gate["release_approved"]},
            "eco": {"path": "hardware/dcx_main/placeholder_eco.json",
                    "sha256": _sha256(ECO)},
        },
        "summary": {
            "blocking_checks": len(blocking),
            "checks_total": len(gate["checks"]),
            "exits": len(exits),
            "magnetics_without_a_physical_pad": len(missing_pads),
            "placeholders": eco_counts["placeholders"],
            "bom_rows_not_selected": len(unselected),
            "refs_needing_a_device_swap": len(device_change),
            "refs_without_a_requirement": len(untraced),
            "refs_with_a_verified_mpn": eco_counts["with_verified_mpn"],
        },
        "exit_kinds": EXIT_KINDS,
        "exits": exits,
        "blocking_checks": blocking,
        "not_here": (
            "the bench boards are in pcb/manufacturing/README.md; the placeholder-by-"
            "placeholder next actions are in hardware/dcx_main/placeholder_eco.csv"),
        "uncovered_blockers": sorted(set(blocking) - declared),
    }


def _md_cell(value: object) -> str:
    return str(value if value is not None else "-").replace("|", "\\|")


def render(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "# Main board: what still blocks a fabrication order",
        "",
        "Generated by `python tools/remaining_dependencies.py --write`.  Do not edit",
        "by hand: `--check` compares this file and the JSON byte for byte.",
        "",
        f"The gate is **{data['source']['gate']['status']}** "
        f"(release_approved = {str(data['source']['gate']['release_approved']).lower()}): "
        f"**{summary['blocking_checks']} of {summary['checks_total']}** checks fail.  "
        "Each one is listed below with the concrete artefact that would close it.",
        "",
        "| exit | closes | kind | refs |",
        "|---|---|---|---|",
    ]
    for row in data["exits"]:
        refs = ", ".join(row.get("refs") or row.get("refs_without_a_requirement") or []) or "-"
        lines.append(f"| `{row['id']}` | `{row['gate_check']}` | {row['exit_kind']} | "
                     f"{_md_cell(refs)} |")
    lines += [
        "",
        "## The exits, one at a time",
        "",
    ]
    for row in data["exits"]:
        lines += [f"### `{row['id']}` -> `{row['gate_check']}`", "",
                  f"**Blocked by:** {row['blocked_by']}", "",
                  f"**Exit ({row['exit_kind']}):** {row['exit']}", ""]
        if row.get("evidence_file"):
            lines += [f"Evidence file the gate reads: `{row['evidence_file']}`", ""]
        if row.get("next_command"):
            lines += [f"Command that moves it: `{row['next_command']}`", ""]
    lines += [
        "## What each exit kind means",
        "",
        *[f"- **{kind}** -- {text}" for kind, text in data["exit_kinds"].items()],
        "",
        "## What this page is not",
        "",
        "- **Not an approval.**  `release_approved` is false and this page cannot set",
        "  it; the gate that can is `tools/d1_fabrication_gate.py`.",
        "- **Not a schedule.**  No dates and no owners: the placeholder register",
        "  records zero decision owners, and inventing one here would read as an",
        "  assignment nobody accepted.",
        "- **Not the bench boards.**  Their packages are in `pcb/manufacturing/`.",
        "",
    ]
    if data["uncovered_blockers"]:
        lines += ["## Blockers this page does not reduce", "",
                  *[f"- `{c}`" for c in data["uncovered_blockers"]], "",
                  "That is a defect in this tool's table, not in the gate.", ""]
    return "\n".join(lines)


def write(data: dict | None = None) -> list[tuple[Path, str]]:
    data = data or build()
    return [(OUT_JSON, json.dumps(data, ensure_ascii=False, indent=2) + "\n"),
            (OUT_MD, render(data))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="rewrite the json and md")
    group.add_argument("--check", action="store_true", help="fail if either is stale")
    args = ap.parse_args(argv)
    rendered = write()
    if args.write:
        for path, text in rendered:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)}")
        return 0
    stale = [path for path, text in rendered
             if not path.is_file() or path.read_text(encoding="utf-8") != text]
    if stale:
        raise SystemExit("stale: " + ", ".join(str(p.relative_to(ROOT)) for p in stale)
                         + " -- run --write")
    data = build()
    print(f"dependencies current: {data['summary']['blocking_checks']} blocking checks, "
          f"{data['summary']['exits']} exits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
