"""Regenerate safe OEM value-only native snapshots without a KiCad license.

This tool is a controlled metadata refresh, not a fresh ERC/DRC or Gerber plot.
Abort if the PCB changed in any way other than placed component Value.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS = {
    "fast_oc": {"U1": "TLV3501AIDBVR", "U2": "LM4040D25IDBZR",
                "D1": "BAT54ZFILM", "D2": "BAT54ZFILM"},
    "d0_protection": {f"D{n}": "BAT54ZFILM" for n in range(5, 19)},
    "sr_fault_validation": {"Q40": "2N7002", "Q41": "NMOS 30V IDM>=3A"},
}
BOARDS = ("fast_oc", "sr_fault_validation")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_geometry_changes(old: str, new: str) -> bool:
    pattern = re.compile(r'(\(property "Value" ")[^"]*(")')
    clean = lambda s: pattern.sub(r'\1__VALUE_ONLY__\2', s)
    return clean(old) == clean(new)


def update_netlist(path: Path, mapping: dict[str, str]) -> None:
    raw = path.read_text(encoding="utf-8")
    for ref, new_value in mapping.items():
        expr = re.compile(r'(\(ref "' + re.escape(ref) +
                          r'"\)\s*\(value ")[^"]*(")')
        raw, count = expr.subn(
            lambda m: m.group(1) + new_value + m.group(2), raw, count=1)
        if count != 1:
            raise RuntimeError(f"{path}: component {ref} not found")
    path.write_text(raw, encoding="utf-8", newline="\n")


def update_position(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    reader = csv.reader(lines)
    header = next(reader)
    ref_idx = header.index("Ref")
    value_idx = header.index("Val")
    seen = set()
    for n, row in enumerate(reader, start=1):
        ref = row[ref_idx]
        if ref not in values:
            continue
        if ref in seen:
            raise RuntimeError(f"{path}: duplicate {ref}")
        seen.add(ref)
        target = values[ref]
        old = row[value_idx]
        if old != target:
            # KiCad's quoted Val field must be replaced without affecting XY.
            needle = '"' + old + '"'
            substitute = '"' + target + '"'
            if lines[n].count(needle) != 1:
                raise RuntimeError(f"{path}: ambiguous {ref} Value")
            lines[n] = lines[n].replace(needle, substitute, 1)
    if seen != set(values):
        raise RuntimeError(f"{path}: missing PnP entries {set(values)-seen}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run() -> None:
    old_boards = {kind: (
        ROOT / "pcb" / kind / f"{kind}.kicad_pcb").read_text(encoding="utf-8")
        for kind in BOARDS}
    generators = [
        "make_fast_oc_eco.py",
        "make_sr_fault_board.py",
        "make_d0_protection_board.py",
        "make_fast_oc_pcb.py",
        # SR Q40/Q41 now have exact MPN fields but keep the same native
        # Value, footprints and nets. Regenerating its 71-part routed PCB
        # merely to repin a BOM would burn minutes and can change copper.
        # A fresh SR geometry generation belongs to a separate KiCad gate.
    ]
    for name in generators:
        print("Regenerate", name, flush=True)
        subprocess.run([sys.executable, str(ROOT / "tools" / name)],
                       cwd=ROOT, check=True)

    for kind in BOARDS:
        new_board = (ROOT / "pcb" / kind / f"{kind}.kicad_pcb").read_text(
            encoding="utf-8")
        if not no_geometry_changes(old_boards[kind], new_board):
            raise RuntimeError(
                f"{kind}: native board changed beyond component Value fields; "
                "fresh KiCad 10 ERC/DRC/plot required")
    for kind, mapping in MAPS.items():
        update_netlist(ROOT / "pcb" / kind / f"{kind}.net", mapping)

    import make_fast_oc_pcb as fast_pcb
    import make_sr_fault_board_pcb as sr_pcb
    import assembly_drawing
    fast_fab = ROOT / "pcb" / "fast_oc" / "fab"
    fast_fab.joinpath("assembly.svg").write_text(
        assembly_drawing.svg(
            fast_pcb.placement(), fast_pcb._table(),
            title="TLV3501 fast-overcurrent ECO module -- assembly drawing, 1:1 top side",
            doc_title="TLV3501 fast-overcurrent ECO module -- assembly drawing",
            board_mm=(fast_pcb.BOARD_W_MM, fast_pcb.BOARD_D_MM),
            footprint_note=("Footprints are vendored from hardware/stock_footprints "
                            "(sha256 in PROVENANCE.md). This module has no "
                            "datasheet-drawn land pattern."),
        ), encoding="utf-8", newline="\n")
    assembly_drawing.write(sr_pcb.FAB / "assembly.svg")
    for kind in BOARDS:
        fab = ROOT / "pcb" / kind / "fab"
        update_position(fab / f"{kind}-pos.csv", MAPS[kind])
        sr_pcb.normalise_fab_text_line_endings(fab)
        path = fab / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["board_sha256"] = digest(ROOT / "pcb" / kind / f"{kind}.kicad_pcb")
        manifest["fab_snapshot_basis"] = "CACHED_KICAD_10_PLOT_VALUE_ONLY_CHANGED"
        manifest["fresh_kicad_erc_drc_gerber_run"] = False
        manifest["flags"] = {"hardware_built": False,
                             "fabrication_approved": False}
        manifest["files"] = [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(fab.iterdir())
            if p.is_file() and p.name != "manifest.json"
        ]
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(ROOT / "tools/manufacturing_index.py"),
                    "--write"], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.write:
        raise SystemExit("Explicit --write required on an isolated branch")
    run()


if __name__ == "__main__":
    main()
