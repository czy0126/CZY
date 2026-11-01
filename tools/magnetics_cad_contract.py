"""Generate a DOT-checked CAD *logical* pin contract for missing T1-T4 + CT.

This is NOT an EasyEDA native symbol and does not assign physical footprint pads.
Import it only after the winding vendor confirms terminal drawings. It prevents
an apparent netlist subset pass from hiding reversed CTAP winding polarity.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
POLARITY = ROOT / "design/v3/magnetics/winding_polarity.json"
OUT = ROOT / "hardware/dcx_main/magnetics_symbol_contract.json"
PINS_T = ("PRI_A", "PRI_B", "SEC_A", "SEC_B", "CTAP")
PINS_CT = ("PRI_A", "PRI_B", "SEC_A", "SEC_B")


def build() -> dict:
    refs = {x: {} for x in ("CT", "T1", "T2", "T3", "T4")}
    with GOLDEN.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["ref"] in refs:
                refs[row["ref"]][row["pin"]] = row["net"]
    pol = json.loads(POLARITY.read_text(encoding="utf-8"))
    symbols = []
    for ref, pin_map in sorted(refs.items()):
        required = set(PINS_CT if ref == "CT" else PINS_T)
        if set(pin_map) != required:
            raise ValueError(f"{ref}: missing or unexpected logical pins {sorted(required ^ set(pin_map))}")
        if ref == "CT":
            dots = {p: "UNVERIFIED_FROM_CT_VENDOR" for p in pin_map}
        else:
            t = pol["transformers"][ref]
            dots = {
                "PRI_A": "DOT",
                "PRI_B": "NON_DOT",
                "SEC_A": "NON_DOT",
                "SEC_B": "DOT",
                "CTAP": "S_A_DOT_AND_S_B_NON_DOT",
            }
            for winding in ("primary", "secondary_a", "secondary_b"):
                w = t[winding]
                if w["dot_pin"] not in dots or w["non_dot_pin"] not in dots:
                    raise ValueError(f"{ref}: polarity references missing CAD pin")
                if w["dot_pin"] == w["non_dot_pin"]:
                    raise ValueError(f"{ref}: invalid identical dot and non-dot")
        symbols.append({
            "ref": ref,
            "winding_type": "CURRENT_TRANSFORMER_4PIN" if ref == "CT" else "CENTER_TAPPED_3_1_1_5PIN",
            "pins": [
                {"logical_pin": pin, "golden_net": pin_map[pin],
                 "polarity": dots[pin], "physical_pad": None}
                for pin in (PINS_CT if ref == "CT" else PINS_T)
            ],
            "native_symbol_present": False,
            "physical_pad_map_verified": False,
        })
    return {
        "status": "LOGICAL_CONTRACT_ONLY_NOT_NATIVE_CAD_OR_FAB",
        "physical_terminal_mapping_required": True,
        "sources": [GOLDEN.relative_to(ROOT).as_posix(),
                    POLARITY.relative_to(ROOT).as_posix()],
        "symbols": symbols,
        "next_gate": "Create native EasyEDA symbols and real numbered pads; export and check all five magnetics and DOT before COMPLETE_PASS",
    }


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--write", action="store_true")
    args = a.parse_args()
    expected = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.write:
        OUT.write_text(expected, encoding="utf-8", newline="\n")
    elif OUT.read_text(encoding="utf-8") != expected:
        raise SystemExit(f"stale contract: {OUT}; run --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
