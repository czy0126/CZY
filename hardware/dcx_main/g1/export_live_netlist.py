"""Read the ACTIVE G1 board's live schematic netlist, with a proof that the
reader is right.

Every manufacturing export of a ``--path``-opened native project returns null,
so ``gen/netlist_export_raw.json`` is still the Nov 6 *pre-ECO* export and the
G1 board has no netlist of its own on record.  That gap is why
``tools/d1_fabrication_gate.py`` cannot re-point its R8 precheck at the G1
inventory: the inventory is post-ECO, the netlist is pre-ECO.

``gen/read_schematic_connectivity.js`` reads the editor's primitive database
instead (each wire carries its own net name), and
``tools/schematic_connectivity.py`` turns that into ``{ref: {pin: net}}``.

This runner first proves the reader on the reference board: run against
``hardware/dcx_main/dcx_main_board.eprj2`` it must reproduce the Nov 6 editor
export pin for pin, otherwise the run stops before it says anything about G1.

    python hardware/dcx_main/g1/export_live_netlist.py            # capture + report
    python hardware/dcx_main/g1/export_live_netlist.py --check    # rebuild from committed captures

A successful run is evidence of what the native schematic CONNECTS.  It is not
a netlist-versus-PCB match, not an ERC/DRC pass and not a fab release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))
import schematic_connectivity as S  # noqa: E402

# The editor helpers are imported inside ``capture()``: ``--check`` must run on a
# Linux CI runner that has no lceda-pro at all.

ACTIVE = HERE / "dcx_main_board_g1_lr_repack.eprj2"
G1_CAPTURE = HERE / "g1_schematic_connectivity_raw.json"
REFERENCE = ROOT / "hardware/dcx_main/dcx_main_board.eprj2"
REFERENCE_CAPTURE = ROOT / "hardware/dcx_main/gen/reference_schematic_connectivity.json"
HISTORICAL = ROOT / "hardware/dcx_main/gen/netlist_export_raw.json"
REPORT = HERE / "g1_live_netlist.json"
READER = ROOT / "hardware/dcx_main/gen/read_schematic_connectivity.js"
PREFIX = "g1_connectivity"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity_body(stem: str) -> str:
    """Set only the globals the shared reader reads; declare nothing new."""
    return (
        "return await (async () => {\n"
        f"  globalThis.CZY_EXPECTED_PROJECT = {json.dumps(stem)};\n"
        "  return {ok: true, expected_project: globalThis.CZY_EXPECTED_PROJECT};\n"
        "})();\n"
    )


def capture(board: Path, out: Path, prefix: str) -> dict:
    """Open ``board`` read-only, capture connectivity, refuse any byte change."""
    import apply_increment as A
    import run_driver_drc as D

    before = sha256(board)
    session = A.open_and_ping(board, prefix, "session")
    if not session:
        raise SystemExit("could not open " + board.name)
    try:
        identity = A.invoke(session, identity_body(board.stem))
        A.dump(prefix, "identity", identity)
        if not identity.get("ok"):
            raise SystemExit("identity invoke failed for " + board.name)
        captured = A.invoke(session, READER.read_text(encoding="utf-8"))
    finally:
        A.dump(prefix, "close", D.call(D.build_close_args(session)))

    if sha256(board) != before:
        raise SystemExit("The read-only export changed " + board.name + "; STOP")
    value = captured.get("value") or {}
    if not captured.get("ok") or value.get("status") != "CONNECTIVITY":
        raise SystemExit(json.dumps(captured, ensure_ascii=False)[:2000])
    if value.get("opened_by") != "path" or value.get("project_name") != board.stem:
        raise SystemExit("Connectivity came from a different project than " + board.name)
    out.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return captured


def build_report(reference: dict, g1: dict, historical: dict) -> dict:
    """Prove the reader on the reference board, then describe the G1 board."""
    rebuilt = S.reconstruct(reference)
    if rebuilt["refs"] != historical:
        raise SystemExit(
            "Connectivity reconstruction does not reproduce the Nov 6 editor export; "
            "it is not trustworthy for any other board")

    live = S.reconstruct(g1)
    r8_pins = historical.get("R8")
    ex_r8 = "R6" if "R6" in live["refs"] and "R8" not in live["refs"] else None
    return {
        "status": "G1_LIVE_SCHEMATIC_NETLIST_NOT_ERC_OR_FAB",
        "method": (
            "read the editor's primitives (sch_PrimitiveWire net name + pin "
            "coordinates); every manufacturing export returns null on a "
            "--path-opened project"),
        "method_validation": {
            "reference_board": REFERENCE.relative_to(ROOT).as_posix(),
            "reference_board_sha256": sha256(REFERENCE),
            "compared_to": HISTORICAL.relative_to(ROOT).as_posix(),
            "identical": True,
            "designators": len(rebuilt["refs"]),
            "pins": sum(len(p) for p in rebuilt["refs"].values()),
            "unconnected_pins": [
                [u["ref"], u["pin"]] for u in rebuilt["unmatched"]],
        },
        "board": ACTIVE.name,
        "board_sha256": sha256(ACTIVE),
        "page": (g1.get("value") or {}).get("page"),
        "wire_count": live["wire_count"],
        "designators": len(live["refs"]),
        "unconnected_pins": [[u["ref"], u["pin"]] for u in live["unmatched"]],
        "netlist": live["refs"],
        "diff": S.diff_netlists(historical, live["refs"]),
        "excluded_pullup": None if ex_r8 is None else {
            "capture_designator": ex_r8,
            "historical_designator": "R8",
            "pins": live["refs"][ex_r8],
            "same_wiring_as_historical_r8": live["refs"][ex_r8] == r8_pins,
        },
        "schematic_versus_pcb_netlist_match_proven": False,
        "native_cad_modified": False,
        "manufacturing_approved": False,
        "limitations": [
            "This is the schematic side only; the single EasyEDA 'Netlist Error' "
            "is a schematic-versus-PCB difference and is not resolved here.",
            "Unconnected pins are those the editor draws with no wire; the "
            "reconstruction does not invent a net for them.",
            "The method is validated on one reference board; a board drawn with "
            "wire-endpoint-less pins would be refused, not silently misread.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="rebuild from committed captures; do not open the editor")
    args = parser.parse_args()

    if args.check:
        reference = json.loads(REFERENCE_CAPTURE.read_text(encoding="utf-8"))
        g1 = json.loads(G1_CAPTURE.read_text(encoding="utf-8"))
    else:
        reference = capture(REFERENCE, REFERENCE_CAPTURE, "reference_connectivity")
        g1 = capture(ACTIVE, G1_CAPTURE, PREFIX)

    historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))["value"]["refs"]
    report = build_report(reference, g1, historical)

    if args.check:
        if json.loads(REPORT.read_text(encoding="utf-8")) != report:
            raise SystemExit("g1_live_netlist.json is stale; re-run without --check")
        print(json.dumps({"ok": True, "checked": REPORT.relative_to(ROOT).as_posix()}))
        return 0

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "designators", "unconnected_pins", "diff",
        "excluded_pullup", "manufacturing_approved")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
