"""Read-only native inventory export for the ACTIVE G1 project.

``tools/native_inventory_bom_gate.py`` still audits
``hardware/dcx_main/gen/native_inventory_raw.json`` -- a Nov 6 capture of the
*previous* native project (83 designators).  That file is honest about itself
(``snapshot_age_note``: "A saved ECO on a COPY is not a modification of the
active .eprj2"), but the active deliverable board is now the reopened G1
candidate.  R8's BOM/PCB flags and every manufacturer id therefore have to be
re-read from G1 instead of quoted from that snapshot.

This runner opens the active board read-only, sets the two project-identity
globals the shared reader accepts, then runs the already-audited
``gen/read_native_inventory.js`` on the same render session (invoke bodies
share the render's global scope).  It never calls ``modify()``, ``save()`` or
an export API, and it fails the run if the board bytes change.

    python hardware/dcx_main/g1/export_native_inventory.py
    python hardware/dcx_main/g1/export_native_inventory.py --board <path> --out <path>

A successful capture is evidence of what the native project SAYS.  It is not
a manufacturing approval, an ERC/DRC pass or a fab release.
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
import apply_increment as A  # noqa: E402
import run_driver_drc as D  # noqa: E402

ACTIVE = HERE / "dcx_main_board_g1_lr_repack.eprj2"
READER = ROOT / "hardware/dcx_main/gen/read_native_inventory.js"
OUT = HERE / "g1_native_inventory_raw.json"
PREFIX = "g1_inventory"


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


def summarize(board_name: str, board_sha256: str, components: list[dict]) -> dict:
    """Report what the capture literally says; interpret nothing.

    ``docs/agent/EDA.md`` §装配排除 ECO: excluding a part from BOM/PCB makes the
    export renumber it, so designator ``R8`` can be absent while the pull-up is
    still there under another name.  Printing ``r8: null`` for that case read
    like a missing part.  The honest summary is two facts -- no row named R8,
    and the list of rows that are explicitly excluded from BOTH BOM and PCB --
    and ``tools/native_inventory_bom_gate.py`` is what decides which excluded
    row *is* R8 (registered device + both flags).
    """
    r8 = next((c for c in components if c.get("ref") == "R8"), None)
    double_dnp = sorted(
        str(c.get("ref")) for c in components
        if c.get("add_into_bom") is False and c.get("add_into_pcb") is False)
    return {
        "board": board_name,
        "board_sha256": board_sha256,
        "captured_components": len(components),
        "refs": sorted(str(c.get("ref")) for c in components),
        "r8_by_designator": None if r8 is None else {
            "add_into_bom": r8.get("add_into_bom"),
            "add_into_pcb": r8.get("add_into_pcb"),
            "value": r8.get("value"),
        },
        "double_dnp_refs": double_dnp,
        "interpretation": "tools/native_inventory_bom_gate.py",
        "manufacturing_approved": False,
    }


def run(board: Path, out: Path) -> int:
    before = sha256(board)
    session = A.open_and_ping(board, PREFIX, "session")
    if not session:
        return 1
    try:
        identity = A.invoke(session, identity_body(board.stem))
        A.dump(PREFIX, "identity", identity)
        if not identity.get("ok"):
            print(json.dumps({"ok": False, "why": "identity invoke failed",
                              "result": identity}, ensure_ascii=False))
            return 1
        captured = A.invoke(session, READER.read_text(encoding="utf-8"))
        A.dump(PREFIX, "read", captured)
    finally:
        A.dump(PREFIX, "close", D.call(D.build_close_args(session)))

    if sha256(board) != before:
        raise SystemExit("The read-only export changed the board bytes; STOP")
    value = captured.get("value") or {}
    if not captured.get("ok") or value.get("status") != "INVENTORY":
        print(json.dumps(captured, ensure_ascii=False)[:2000])
        raise SystemExit("Native inventory capture did not return INVENTORY")
    # The project was opened by --path, whose uuid is unstable, so the file
    # stem is the only identity available.  Refuse anything else.
    if value.get("opened_by") != "path" or value.get("project_name") != board.stem:
        raise SystemExit(
            "Inventory was read from a different project than " + board.name)

    out.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps(summarize(board.name, before, value["components"]),
                     ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=ACTIVE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    raise SystemExit(run(args.board, args.out))


if __name__ == "__main__":
    main()
