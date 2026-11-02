"""Diff the editor's own netlist against the golden pin netlist.

This is the A4 acceptance check.  It compares *pads*, not just designator
counts: a schematic where every part is present but one FET source pad was
wired to the wrong net passes a count check and fails here.

Two directions are reported separately because they fail differently:

* missing/mismatched -- a golden pin whose pad carries the wrong net, or no
  net at all.  This is a wiring defect in the native schematic.
* extra -- a pad carrying a net the golden netlist does not mention.  On an
  unassigned pad this is the exposed-pad case and is expected; on an assigned
  one it is a short.

T1-T4 and CT are diffed like any other part: their native symbols carry the
logical terminal names as pin numbers, so a reversed winding or a swapped pair
shows up here as a wrong net.  Being wired correctly is still not being
verified -- see ``unchecked_magnetics`` below.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import main_board_schematic as mbs

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
NATIVE = HW / "gen/netlist_export_raw.json"
OUT = HW / "netlist_compare.json"


def compare(golden: dict[str, dict[str, str]],
            exported: dict[str, dict[str, str]],
            library: dict[str, dict]) -> dict[str, object]:
    missing: list[dict[str, str]] = []
    extra: list[dict[str, str]] = []
    bonded: list[dict[str, str]] = []
    checked = 0

    for ref, pins in golden.items():
        part = mbs.device_of(ref)
        symbol_pins = {p["num"] for p in library[part]["pins"]}
        expected: dict[str, str] = {}
        for pin, net in pins.items():
            for pad in mbs.pads_for(part, pin, symbol_pins):
                expected[pad] = net
        # package pads the deck cannot express (see BONDED_PADS) are expected
        # too, but they are counted separately so the report never implies the
        # golden netlist contained them
        for pad, net in mbs.BONDED_PADS.get(part, {}).items():
            expected[pad] = net
            bonded.append({"ref": ref, "pad": pad, "net": net})

        got = exported.get(ref)
        if got is None:
            missing.append({"ref": ref, "pad": "*", "want": "part present", "got": "absent"})
            continue

        for pad, net in expected.items():
            # the bonded pads are counted in their own bucket so the headline
            # number stays "pads the golden netlist asked for"
            if pad not in mbs.BONDED_PADS.get(part, {}):
                checked += 1
            actual = got.get(pad, "")
            if actual != net:
                missing.append({"ref": ref, "pad": pad, "want": net, "got": actual or "<empty>"})

        for pad, actual in got.items():
            if pad in expected or not actual:
                continue
            extra.append({"ref": ref, "pad": pad, "net": actual})

    # Real peripherals the deck cannot express (EN/RUN defaults, EN filter,
    # per-IC decoupling).  Counted separately so the headline "pads the golden
    # netlist asked for" keeps its exact meaning.
    peripheral_checked = 0
    for ref, spec in mbs.PERIPHERALS.items():
        expected_pads = dict(spec["pads"])  # type: ignore[arg-type]
        got = exported.get(ref)
        if got is None:
            missing.append({"ref": ref, "pad": "*", "want": "peripheral present", "got": "absent"})
            continue
        for pad, net in expected_pads.items():
            peripheral_checked += 1
            actual = got.get(pad, "")
            if actual != net:
                missing.append({"ref": ref, "pad": pad, "want": net,
                                "got": actual or "<empty>"})
        for pad, actual in got.items():
            if pad in expected_pads or not actual:
                continue
            extra.append({"ref": ref, "pad": pad, "net": actual})

    unplaced = sorted(set(golden) - set(exported))
    # A custom symbol is NOT validated merely because its reference appears.
    # Without explicit physical terminal->pad evidence a magnetic device could
    # reverse its winding DOT while all ordinary pad tests remain green.
    # Their pads are now diffed, but the pad numbers are logical terminal names.
    # A magnetic whose logical nets all match can still be built with a reversed
    # winding, so it never counts as verified.
    unchecked_magnetics = sorted(set(exported) & set(mbs.MAGNETIC_UNVERIFIED))
    extra_refs = sorted(set(exported) - set(golden) - set(mbs.PERIPHERALS))
    subset_ok = not missing and not extra and not extra_refs and not unplaced
    blockers = []
    if unplaced:
        blockers.append("not all golden references are placed")
    if unchecked_magnetics:
        blockers.append("placed magnetics have no verified terminal-to-pad and DOT mapping")
    if mbs.PLACEHOLDER:
        blockers.append("engineering value/MPN/footprint placeholders remain in the native schematic")
    blockers.append("native editor ERC report and routed PCB not yet supplied")
    return {
        "pads_checked": checked,
        "peripheral_pads_checked": peripheral_checked,
        "pads_bonded_by_design": bonded,
        "missing_or_wrong": missing,
        "unexpected_nets": extra,
        "not_placed": unplaced,
        "unchecked_magnetics": unchecked_magnetics,
        "unexpected_refs": extra_refs,
        "subset_ok": subset_ok,
        "readiness": "PARTIAL_PASS" if subset_ok else "FAIL",
        "manufacturing_ready": False,
        "manufacturing_blockers": blockers,
        # Backward-compatible subset check, NOT an A1 or manufacturing pass.
        "ok": subset_ok,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native", type=Path, default=NATIVE)
    ap.add_argument("--json", type=Path, default=OUT)
    ap.add_argument("--require-complete", action="store_true",
                    help="block when the schematic is incomplete or native ERC/PCB are missing")
    args = ap.parse_args(argv)

    raw = json.loads(args.native.read_text(encoding="utf-8"))
    if not raw.get("ok"):
        raise SystemExit(f"netlist export failed: {raw.get('error')}")
    library = mbs.load_library()
    result = compare(mbs.load_golden(), raw["value"]["refs"], library)

    args.json.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pads checked: {result['pads_checked']}")
    print(f"pads bonded by design (not in the golden netlist): {len(result['pads_bonded_by_design'])}")
    for item in result["pads_bonded_by_design"]:
        print("   ", item)
    print(f"missing or wrong: {len(result['missing_or_wrong'])}")
    for item in result["missing_or_wrong"][:20]:
        print("   ", item)
    print(f"unexpected nets: {len(result['unexpected_nets'])}")
    for item in result["unexpected_nets"][:20]:
        print("   ", item)
    print(f"not placed from SPICE basis: {result['not_placed']}")
    print(f"subset_ok (not a manufacturing pass): {result['subset_ok']}")
    print(f"readiness: {result['readiness']}; manufacturing_ready: {result['manufacturing_ready']}")
    for item in result["manufacturing_blockers"]:
        print(f"  BLOCKED: {item}")
    if args.require_complete:
        return 0 if result["manufacturing_ready"] else 2
    return 0 if result["subset_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
