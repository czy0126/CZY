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

Refs named in ``MAGNETIC_GAPS`` are reported as not placed rather than as
failures -- the tool refuses to call the board complete while T1-T4 and CT
have no symbol.
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
        if ref in mbs.MAGNETIC_GAPS:
            continue
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

    unplaced = sorted(set(golden) - set(exported))
    return {
        "pads_checked": checked,
        "pads_bonded_by_design": bonded,
        "missing_or_wrong": missing,
        "unexpected_nets": extra,
        "not_placed": unplaced,
        # subset, not equality: the magnetics are permitted to be missing, but
        # placing one (which would mean the custom symbol exists) must never be
        # reported as a regression
        "ok": not missing and not extra and set(unplaced) <= set(mbs.MAGNETIC_GAPS),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--native", type=Path, default=NATIVE)
    ap.add_argument("--json", type=Path, default=OUT)
    args = ap.parse_args(argv)

    raw = json.loads(args.native.read_text(encoding="utf-8"))
    if not raw.get("ok"):
        raise SystemExit(f"netlist export failed: {raw.get('error')}")
    library = json.loads((HW / "library_pins.json").read_text(encoding="utf-8"))
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
    print(f"not placed: {result['not_placed']}")
    print(f"ok: {result['ok']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
