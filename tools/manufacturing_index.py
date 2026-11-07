"""One directory that says what each bench board is and how to rebuild it.

Six declared bench designs live under ``pcb/``. Two have a fabrication package (a
routed board plus gerbers, drill, position file, assembly drawing and a
manifest); the other four are schematics with ERC evidence and no copper. A
reader who has the repository but not the history cannot tell which is which
from the directory listing -- ``fab/manifest.json`` is the only file that says
so, and its absence has to mean "not made yet" rather than "look harder".

This tool is a **view**, not an audit.  It copies what the committed manifests
and board files already say: hashes, file counts, flags, and the regeneration
command.  It computes nothing about whether a board is good, and it cannot make
a package appear -- ``--check`` fails when the index disagrees with the tree,
which is the only judgement it makes.

The main board is deliberately absent: it has no copper at all.  Its remaining
dependencies are in ``hardware/dcx_main/remaining_dependencies.md``.

Usage:
    python tools/manufacturing_index.py --write    # rewrite index.json + README.md
    python tools/manufacturing_index.py --check    # fail if either is stale
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text_identity import sha256_file

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb/manufacturing"
INDEX = OUT / "index.json"
README = OUT / "README.md"

# The table is declared here rather than discovered by walking ``pcb/``: a
# directory that appears without an entry should not silently acquire the
# standing of "known board", and a board that disappears must fail the check.
BOARDS: list[dict] = [
    {
        "id": "bias_cut_revision_b",
        "title": "Revision B SR bias-cut candidate: series diode and startup resistor",
        "what": "Candidate schematic only; replaces revision A power-path proposal. "
                "Behavioural power-path screens do not qualify REG hold energy, real control or hardware.",
        "generator": "python tools/bias_cut_revision_b.py",
        "schematic": "pcb/bias_cut_revision_b/bias_cut_revision_b.kicad_sch",
        "board": None,
        "fab": None,
    },
    {
        "id": "bias_cut_eco",
        "title": "Revision A SR bias-cut ECO: historical, failed stress review",
        "what": "Native schematic and behavioural simulation only. PMOS selection, "
                "startup, gate propagation and reverse-voltage sweep remain unqualified.",
        "generator": "python tools/make_bias_cut_eco.py --check",
        "schematic": "pcb/bias_cut_eco/bias_cut_eco.kicad_sch",
        "board": None,
        "fab": None,
    },
    {
        "id": "sr_fault_validation",
        "title": "Single-pair UCC24624 SR fault-shutdown validation board",
        "what": "Two BSC010N04LS6 driven by one real UCC24624, a fault interface and a "
                "REG crowbar.  Its purpose is to measure how one SR pair behaves when a "
                "fault command arrives, not to pass the converter's current.",
        "generator": "python tools/make_sr_fault_board_pcb.py --fab",
        "schematic": "pcb/sr_fault_validation/sr_fault_validation.kicad_sch",
        "board": "pcb/sr_fault_validation/sr_fault_validation.kicad_pcb",
        "fab": "pcb/sr_fault_validation/fab",
    },
    {
        "id": "fast_oc",
        "title": "TLV3501 fast-overcurrent ECO module",
        "what": "One TLV3501 comparator and a 2N7002 open-drain pull-down that make the "
                "overcurrent channel fast by replacing the three RC filters, not the "
                "comparator.  It does not latch.",
        "generator": "python tools/make_fast_oc_pcb.py --fab",
        "schematic": "pcb/fast_oc/fast_oc.kicad_sch",
        "board": "pcb/fast_oc/fast_oc.kicad_pcb",
        "fab": "pcb/fast_oc/fab",
    },
    {
        "id": "d0_protection",
        "title": "D0 ten-channel protection logic board",
        "what": "CD4013 fault latches, the ten-way gate-maximum detector (one Schottky "
                "per gate into a 22k/6.2k divider, replacing the ten-resistor sum) and "
                "the ACK token, with the POR folded into the latch.  Schematic and "
                "ERC only.",
        "generator": "python tools/make_d0_protection_board.py --check",
        "schematic": "pcb/d0_protection/d0_protection.kicad_sch",
        "board": None,
        "fab": None,
    },
    {
        "id": "control_validation",
        "title": "UCC25600 / UCC24624 control validation board",
        "what": "The controller and SR driver wired to their passives so the timing, "
                "RT/DT and dead-time assumptions can be measured before the power stage "
                "exists.  Schematic and ERC only.",
        "generator": "python tools/make_control_board.py --check",
        "schematic": "pcb/control_validation/control_validation.kicad_sch",
        "board": None,
        "fab": None,
    },
]


def _sha256(path: Path) -> str:
    """Canonical (LF) identity: the same file hashes the same on CI and here."""
    return sha256_file(path)


def _flags(manifest: dict) -> dict:
    """The two approval flags, defaulting to false when a manifest omits them.

    A missing flag must not read as a granted one: absence is exactly how an
    unapproved package would slip through as approved.
    """
    flags = manifest.get("flags") or {}
    return {"hardware_built": bool(flags.get("hardware_built", False)),
            "fabrication_approved": bool(flags.get("fabrication_approved", False))}


def entry(spec: dict) -> dict:
    """One board as the committed files describe it."""
    schematic = ROOT / spec["schematic"]
    row = {
        "id": spec["id"],
        "title": spec["title"],
        "what": spec["what"],
        "generator": spec["generator"],
        "schematic": spec["schematic"],
        "board": spec["board"],
        "fab": spec["fab"],
    }
    if not schematic.is_file():
        raise SystemExit(f"{spec['id']}: {spec['schematic']} is missing")
    row["schematic_sha256"] = _sha256(schematic)

    if spec["board"] is None:
        row["status"] = "SCHEMATIC_ONLY"
        row["not_fabricable_because"] = [
            "no PCB was generated for this board: the repository holds its schematic, "
            "netlist, ERC report and BOM, and no copper",
        ]
        return row

    board = ROOT / spec["board"]
    if not board.is_file():
        raise SystemExit(f"{spec['id']}: {spec['board']} is missing")
    row["board_sha256"] = _sha256(board)

    if spec["fab"] is None:
        # Copper that passes DRC is not a package: no gerber, no drill, no
        # position file, so there is nothing to send a fabricator.  Saying so
        # is the difference between "not made yet" and "look harder".
        row["status"] = "NO_FAB_PACKAGE"
        row["not_fabricable_because"] = [
            "this board has a routed, DRC-clean board file but no gerber/drill/"
            "position package has been exported for it",
        ]
        return row

    fab = ROOT / spec["fab"]
    manifest_path = fab / "manifest.json"
    if not manifest_path.is_file():
        row["status"] = "NO_FAB_PACKAGE"
        row["not_fabricable_because"] = [
            f"{spec['fab']}/manifest.json does not exist: run `{spec['generator']}`",
        ]
        return row

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    on_disk = {p.name for p in fab.iterdir() if p.is_file() and p.name != "manifest.json"}
    listed = {f["name"] for f in manifest.get("files") or []}
    row.update({
        "manifest": f"{spec['fab']}/manifest.json",
        "manifest_sha256": _sha256(manifest_path),
        "kicad_cli": manifest.get("kicad_cli"),
        "copper_weight_oz": manifest.get("copper_weight_oz"),
        "files": len(on_disk),
        "layers": manifest.get("plotted_layers"),
        "flags": _flags(manifest),
        "manifest_board_sha256": manifest.get("board_sha256"),
    })
    problems = []
    if manifest.get("board_sha256") != row["board_sha256"]:
        problems.append("the manifest hashes a different board than the committed one")
    if listed != on_disk:
        problems.append(f"the manifest lists {sorted(listed)} but the directory holds "
                        f"{sorted(on_disk)}")
    if manifest.get("plotted_layers") != manifest.get("layers"):
        problems.append("the plotted layers are not the requested layers")
    entries = manifest.get("files") or []
    if len(entries) != len(listed):
        problems.append("the manifest has duplicate fabrication filenames")
    # A file count and a board hash alone do NOT validate Gerbers. Two full
    # Windows exports were committed with CRLF->LF normalization; every
    # filename still existed and the index incorrectly displayed PRESENT.
    # Validate the *actual bytes in Git* before telling procurement a package
    # exists. This never grants electrical/fabrication approval.
    for item in entries:
        name = item.get("name")
        if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name:
            problems.append(f"invalid/untrusted file name in manifest: {name!r}")
            continue
        actual = fab / name
        if not actual.is_file():
            continue  # already caught by listed != on_disk
        if actual.stat().st_size != item.get("bytes"):
            problems.append(f"{name}: bytes differ from committed file")
        if _sha256(actual) != item.get("sha256"):
            problems.append(f"{name}: sha256 differs from committed file")
    row["status"] = "FAB_PACKAGE_STALE" if problems else "FAB_PACKAGE_PRESENT"
    if problems:
        row["not_fabricable_because"] = problems
    return row


def build() -> dict:
    return {
        "status": "BENCH_BOARD_MANUFACTURING_INDEX",
        "generated_by": "tools/manufacturing_index.py",
        "note": ("A view over committed artefacts, not an approval: it copies each "
                 "board's own hashes and flags and makes no judgement about the "
                 "design.  hardware_built and fabrication_approved stay false for "
                 "every board."),
        "boards": [entry(spec) for spec in BOARDS],
        "reproduce": [spec["generator"] for spec in BOARDS],
        "not_here": ("the main board has no copper; its remaining dependencies are in "
                     "hardware/dcx_main/remaining_dependencies.md"),
        "requires": ("The two `--fab` commands need KiCad's kicad-cli.  Without it the "
                     "committed packages can be inspected and hashed, but not rebuilt."),
    }


def _md_cell(value: object) -> str:
    return str(value if value is not None else "-").replace("|", "\\|")


def render(data: dict) -> str:
    lines = [
        "# Bench board manufacturing directory",
        "",
        "Generated by `python tools/manufacturing_index.py --write`.  Do not edit by",
        "hand: `--check` compares this file and `index.json` byte for byte.",
        "",
        "This page is a view over what the repository already holds.  Each board's",
        "own `fab/manifest.json` is the authority on what its package contains; the",
        "table below only says which packages exist and whether they still match the",
        "board they claim to describe.",
        "",
        "| board | status | files | copper | flags | rebuild |",
        "|---|---|---|---|---|---|",
    ]
    for row in data["boards"]:
        files = row.get("files", 0)
        copper = f"{row['copper_weight_oz']} oz" if row.get("copper_weight_oz") else "-"
        flags = row.get("flags")
        flag_text = ("built={hardware_built}, approved={fabrication_approved}"
                     .format(**flags)) if flags else "-"
        lines.append(f"| `{row['id']}` | {row['status']} | {files} | {_md_cell(copper)} | "
                     f"{_md_cell(flag_text)} | `{row['generator']}` |")
    lines += ["", "## What each board is", ""]
    for row in data["boards"]:
        lines += [f"### `{row['id']}` -- {row['title']}", "",
                  row["what"], ""]
        if row.get("not_fabricable_because"):
            lines.append("Not fabricable today:")
            lines += [f"- {reason}" for reason in row["not_fabricable_because"]]
            lines.append("")
        if row.get("manifest"):
            lines += [
                f"Package: `{row['fab']}/` (manifest `{row['manifest_sha256']}`)",
                f"Board: `{row['board']}` (`{row['board_sha256']}`)",
                f"Layers: {', '.join(row.get('layers') or [])}",
                "",
            ]
    lines += [
        "## Rebuilding a package",
        "",
        "```",
        *data["reproduce"],
        "```",
        "",
        data["requires"],
        "",
        "## What this directory is not",
        "",
        "- **Not an approval.**  `hardware_built` and `fabrication_approved` are false",
        "  on every board.  A package that can be ordered is exactly the artefact that",
        "  gets mistaken for an approved one.",
        "- **Not a bill of materials.**  Each board's `BOM.csv` is next to its",
        "  schematic; the main board's sourcing state is in",
        "  `hardware/dcx_main/placeholder_eco.json`.",
        "- **Not the main board.**  It has no copper; see",
        "  `hardware/dcx_main/remaining_dependencies.md`.",
        "",
    ]
    return "\n".join(lines)


def write(data: dict | None = None) -> list[tuple[Path, str]]:
    data = data or build()
    OUT.mkdir(parents=True, exist_ok=True)
    index = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    readme = render(data)
    return [(INDEX, index), (README, readme)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="rewrite index.json and README.md")
    group.add_argument("--check", action="store_true", help="fail if either file is stale")
    args = ap.parse_args(argv)
    data = build()
    rendered = write(data)
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
    counts: dict[str, int] = {}
    for row in data["boards"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("index current: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
