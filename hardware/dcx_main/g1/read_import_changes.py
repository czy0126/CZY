"""Read the editor's own schematic-vs-PCB difference on a copy of the candidate.

The native DRC only says "PCB and schematic netlist does not match" and points
at the Import Changes dialog; it does not publish the per-object difference.
This script asks the editor's beta comparator (`sys_Tool.netlistComparison`)
for that list, read-only, on a throwaway copy of the accepted candidate:

  python hardware/dcx_main/g1/read_import_changes.py --capture

It never imports changes and never saves. The receipt is refused if it already
exists, and both the copy and the candidate must keep their SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import apply_increment as A
import run_driver_drc as D
import route_lr_signal_stubs as S

HERE = Path(__file__).resolve().parent
BOARD = (HERE / S.CANDIDATE).resolve()
PROBE = HERE / ".tmp_import_changes.eprj2"
PREFIX = "lr_signal_import_changes"
RAW = HERE / f"{PREFIX}.json"
JS = HERE / "read_import_changes.js"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(entries: list[dict] | None) -> list[dict]:
    """One stable row per editor difference, whichever field spelling it uses.

    The published signature names ``netlist1Name``/``netlist2Name`` while the
    documented example reads ``net1``/``net2``; accept both rather than trusting
    either. Fail closed: a string or object is not a difference list.
    """
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ValueError(f"netlist comparison returned {type(entries).__name__}, not a list")
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"difference entry is {type(entry).__name__}, not an object")
        rows.append({
            "type": entry.get("type"),
            "object": entry.get("object"),
            "schematic": entry.get("netlist1Name", entry.get("net1")) or [],
            "pcb": entry.get("netlist2Name", entry.get("net2")) or [],
        })
    return sorted(rows, key=lambda row: (str(row["type"]), str(row["object"])))


def run() -> int:
    if RAW.exists():
        raise SystemExit("Import-Changes receipt already exists; not overwriting evidence")
    candidate_sha = sha256(BOARD)
    shutil.copy2(BOARD, PROBE)
    probe_sha = sha256(PROBE)
    if probe_sha != candidate_sha:
        raise SystemExit("Probe copy is not byte-identical to the candidate")
    session = A.open_and_ping(PROBE, PREFIX, "open")
    if not session:
        raise SystemExit("Editor not available")
    try:
        raw = A.invoke(session, JS.read_text(encoding="utf-8"))
    finally:
        A.dump(PREFIX, "close", D.call(D.build_close_args(session)))
    value = raw.get("value") or {}
    try:
        normalized = normalize(value.get("diff"))
    except ValueError as exc:
        normalized = []
        value["normalize_error"] = str(exc)
    receipt = {
        "status": "NATIVE_IMPORT_CHANGES_DIFF_READBACK",
        "attempted": "read-only: opened a copy, compared schematic/PCB netlists, never saved",
        "candidate": BOARD.relative_to(S.ROOT).as_posix(),
        "candidate_sha256": candidate_sha,
        "probe_copy_sha256": probe_sha,
        "probe_copy_sha256_after": sha256(PROBE),
        "editor_ok": raw.get("ok"),
        "api": value.get("api"),
        "api_type": value.get("api_type"),
        "board": value.get("board"),
        "count": value.get("count"),
        "attempts": value.get("attempts"),
        "sch_netlist": value.get("sch_netlist"),
        "readback_error": value.get("error"),
        "normalize_error": value.get("normalize_error"),
        "normalized": normalized,
        "raw": raw,
        "not_erc_not_drc_not_fab": True,
    }
    RAW.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({"ok": raw.get("ok"), "count": receipt["count"],
                      "error": receipt["readback_error"],
                      "candidate_sha256": candidate_sha,
                      "probe_unchanged": candidate_sha == receipt["probe_copy_sha256_after"],
                      "normalized": receipt["normalized"][:10]}, ensure_ascii=False, indent=2))
    return 0 if raw.get("ok") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(run())
