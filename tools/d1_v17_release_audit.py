"""Source-bound V17 engineering stop-line; a clean DRC is not a fab approval.

Pure stdlib: audit the saved KiCad candidate and archived native receipts.
Never edits PCB or upgrades the release flag. Use --check in CI and
--require-release only as an explicit fail-closed release probe.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
G2 = Path("hardware/dcx_main/g2")
FILENAMES = {
    "pcb": "dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb",
    "native_v15": "dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2",
    "drc": "g2_v17_KICAD_NATIVE_DRC_NOT_FOR_FAB.json",
    "build": "g2_v17_real_kicad_native_build_NOT_FOR_FAB.json",
    "parity": "g2_v17_integrated_native_pin_parity_NOT_FOR_FAB.json",
    "terminal": "g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json",
}
OUTPUT = G2 / "g2_v17_source_locked_release_stopline_NOT_FOR_FAB.json"
REQUIRED_MAGNETICS = {"CT", "T1", "T2", "T3", "T4"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_drc_digest(path: Path) -> str:
    """Match archived native KiCad DRC created with Windows CRLF only.

    Git checked this one JSON back out as LF, leaving its semantic content
    intact. This does NOT normalize the editable PCB or any other evidence.
    """
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def unconnected_by_net(drc: dict) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for item in drc.get("unconnected_items", []):
        nets = {
            match
            for endpoint in item.get("items", [])
            for match in re.findall(r"\[([^\]]+)\]", endpoint.get("description", ""))
        }
        counts[next(iter(nets)) if len(nets) == 1 else "UNKNOWN"] += 1
    return dict(sorted(counts.items()))


def audit(root: Path = ROOT) -> dict:
    paths = {key: root / G2 / file for key, file in FILENAMES.items()}
    meta = {key: load_json(paths[key]) for key in ("build", "drc", "parity", "terminal")}
    board_sha, drc_sha = digest(paths["pcb"]), digest(paths["drc"])
    build, drc, parity, terminal = (meta[k] for k in ("build", "drc", "parity", "terminal"))

    devices = terminal.get("devices", {})
    real_terminal_rows = [
        pin for ref in REQUIRED_MAGNETICS
        for pin in devices.get(ref, {}).get("design_logical_pins", [])
    ]
    vendor_signed = (
        len(real_terminal_rows) == 24
        and all(
            pin.get("vendor_physical_pin_number") is not None
            and pin.get("manufacturer_pinout_signed") is True
            and pin.get("winding_first_article_polarity_passed") is True
            for pin in real_terminal_rows
        )
        and terminal.get("vendor_mechanical_pin_numbers_confirmed") == 24
        and terminal.get("vendor_winding_DOT_confirmed") == 24
    )
    magnetic_refs_absent = set(parity.get("missing_real_physical_magnetics", []))
    lines = unconnected_by_net(drc)
    checks = {
        "pcb_sha_matches_native_build": board_sha == build.get("saved_board_sha256"),
        "v15_native_source_sha_matches": (
            digest(paths["native_v15"]) == build.get("pcb_source_native_Sha256")
            == parity.get("native_v15_sha256")
        ),
        "pcb_sha_matches_pin_parity": board_sha == parity.get("native_V17_kicad_sha256"),
        "drc_sha_matches_pin_parity": historical_drc_digest(paths["drc"]) == parity.get("native_V17_drc_sha256"),
        "drc_source_is_this_pcb": drc.get("source") == paths["pcb"].name,
        "drc_zero_rule_violations": len(drc.get("violations", [None])) == 0,
        "drc_zero_unconnected": len(drc.get("unconnected_items", [None])) == 0,
        "drc_no_ignored_checks": len(drc.get("ignored_checks", [None])) == 0,
        "pgnd_and_vout_continuity_recorded": (
            "PGND" not in lines and "VOUT" not in lines and "UNKNOWN" not in lines
            and parity.get("kicad_real_copper_layer_count") == 12
        ),
        "five_physical_magnetics_present": (
            not (magnetic_refs_absent & REQUIRED_MAGNETICS)
            and not any(
                "physical PCB winding footprints" in reason or "CT winding" in reason
                for reason in build.get("critical_missing", [])
            )
        ),
        "all_24_magnetics_vendor_pins_and_dot_signed": vendor_signed,
        "full_schematic_pcb_pin_parity": parity.get(
            "real_full_P1_SCH_to_PCB_netlist_parity_verified"
        ) is True,
        "oem_footprint_release": parity.get("OEM_manufacturing_footprints_signed") is True,
        "rated_100a_output_and_coldplate": (
            parity.get("8_contact_current_rating_and_coldplate_mount_verified") is True
            and build.get("output_interface_manufacturer_and_100A_qualified") is True
        ),
        "thermal_emi_and_100a_evidence": (
            parity.get("thermal_EMI_3D_and_100A_verified") is True
        ),
        "native_cad_release_flag": (
            parity.get("board_release") is True
            and build.get("real_fabrication_release") is True
        ),
    }
    return {
        "schema": "d1_v17_release_stopline/1",
        "basis": "V17 KiCad independent physical PCB candidate, NOT EasyEDA manufacturing release",
        "evidence_sha256": {
            "pcb": board_sha,
            "native_v15": digest(paths["native_v15"]),
            "drc_checkout_bytes": drc_sha,
            "drc_archived_crlf": historical_drc_digest(paths["drc"]),
            "build": digest(paths["build"]),
            "parity": digest(paths["parity"]),
            "magnetics_terminal_contract": digest(paths["terminal"]),
        },
        "observed": {
            "rule_violations": len(drc.get("violations", [])),
            "unconnected_total": len(drc.get("unconnected_items", [])),
            "unconnected_by_net": lines,
            "ignored_drc_checks": [item.get("key") for item in drc.get("ignored_checks", [])],
            "missing_magnetic_refs": sorted(magnetic_refs_absent),
            "design_logical_magnetic_terminals": len(real_terminal_rows),
            "vendor_terminals_signed": vendor_signed,
        },
        "checks": checks,
        "blocking_checks": [key for key, passed in checks.items() if not passed],
        "can_fabricate": all(checks.values()),
        "status": "RELEASE_CANDIDATE" if all(checks.values()) else "NOT_FOR_FAB",
    }


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-release", action="store_true")
    opts = parser.parse_args(argv)
    if opts.write and opts.check:
        parser.error("--write and --check are mutually exclusive")
    try:
        result = audit()
        expected = canonical_json(result)
        target = ROOT / OUTPUT
        if opts.write:
            target.write_text(expected, encoding="utf-8")
        if opts.check and target.read_text(encoding="utf-8") != expected:
            print("Release stopline stale: regenerate via --write", file=sys.stderr)
            return 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Release evidence invalid: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "status": result["status"],
        "blocking_checks": result["blocking_checks"],
        "observed": result["observed"],
    }, ensure_ascii=True))
    return 2 if opts.require_release and not result["can_fabricate"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
