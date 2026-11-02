"""Generate a DOT-checked CAD pin contract for T1-T4 + CT.

Two facts are kept apart on purpose:

* ``native_symbol_present`` -- the symbol is drawn in the project library and
  placed on the sheet.  Read from ``project_symbols.json``, which records the
  device/symbol uuids that the headless CLI actually created.  It is not a flag
  someone sets: a hand-edited "true" is rejected by ``main()`` as stale, and a
  missing native record degrades it back to false.
* ``physical_pad_map_verified`` -- a vendor terminal drawing turns PRI_A /
  CTAP / SEC_A into numbered pads with a DOT.  Nothing in this repository can
  supply that, so it stays false and every ``physical_pad`` stays null.

Keeping them apart is what stops an apparent netlist subset pass from hiding a
reversed CTAP winding: correct logical nets plus unknown physical terminals is
not a verified magnetic.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
POLARITY = ROOT / "design/v3/magnetics/winding_polarity.json"
PROJECT_SYMBOLS = ROOT / "hardware/dcx_main/project_symbols.json"
OUT = ROOT / "hardware/dcx_main/magnetics_symbol_contract.json"
PINS_T = ("PRI_A", "PRI_B", "SEC_A", "SEC_B", "CTAP")
PINS_CT = ("PRI_A", "PRI_B", "SEC_A", "SEC_B")

PIN_NUMBERING_NOTE = (
    "pin number == logical terminal name (no vendor terminal drawing exists, "
    "so no '1..5' numbering was invented)")


def native_symbols() -> dict[str, dict]:
    """ref -> the recorded native device that carries it.

    Reading ``project_symbols.json`` rather than a hand-set flag is the whole
    mechanism: the file is written when the CLI creates the device, so the
    contract cannot claim a symbol that was never drawn.
    """
    if not PROJECT_SYMBOLS.is_file():
        return {}
    data = json.loads(PROJECT_SYMBOLS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for sym in data.get("symbols", {}).values():
        for ref in sym.get("used_by", []):
            out[ref] = {
                "native_device_uuid": sym["device_uuid"],
                "native_symbol_uuid": sym["symbol_uuid"],
                "placeholder_footprint": (sym.get("placeholder_footprint") or {}).get("name", ""),
            }
    return out


def build() -> dict:
    refs = {x: {} for x in ("CT", "T1", "T2", "T3", "T4")}
    with GOLDEN.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["ref"] in refs:
                refs[row["ref"]][row["pin"]] = row["net"]
    pol = json.loads(POLARITY.read_text(encoding="utf-8"))
    native = native_symbols()
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
        entry: dict[str, object] = {
            "ref": ref,
            "winding_type": "CURRENT_TRANSFORMER_4PIN" if ref == "CT" else "CENTER_TAPPED_3_1_1_5PIN",
            "pins": [
                {"logical_pin": pin, "golden_net": pin_map[pin],
                 "polarity": dots[pin], "physical_pad": None}
                for pin in (PINS_CT if ref == "CT" else PINS_T)
            ],
            "native_symbol_present": ref in native,
        }
        if ref in native:
            entry.update(native[ref])
        # No terminal drawing exists in this repository, so this stays false
        # even for a drawn symbol.  Nothing may set it from here.
        entry["physical_pad_map_verified"] = False
        symbols.append(entry)

    placed = sum(1 for s in symbols if s["native_symbol_present"])
    if placed == len(symbols):
        status = "NATIVE_SYMBOLS_PLACED_PHYSICAL_TERMINALS_UNVERIFIED"
    elif placed:
        status = "NATIVE_SYMBOLS_PARTIALLY_PLACED_PHYSICAL_TERMINALS_UNVERIFIED"
    else:
        status = "LOGICAL_CONTRACT_ONLY_NOT_NATIVE_CAD_OR_FAB"
    if placed == len(symbols):
        next_gate = ("The symbols are drawn and placed and the native export wires every logical "
                     "terminal; what is still missing is the vendor terminal drawing that turns "
                     "PRI_A/SEC_A/CTAP into numbered pads with a DOT. Until then every physical_pad "
                     "stays null.")
    elif placed:
        next_gate = (f"{placed} of {len(symbols)} symbols are drawn and placed; draw the rest, then "
                     "obtain the vendor terminal drawings that turn the logical terminal names into "
                     "numbered pads with a DOT. Until then every physical_pad stays null.")
    else:
        next_gate = ("Create native EasyEDA symbols and real numbered pads; export and check all five "
                     "magnetics and DOT before COMPLETE_PASS")

    result: dict[str, object] = {
        "status": status,
        "physical_terminal_mapping_required": True,
    }
    if placed:
        result["native_symbol_pin_numbering"] = PIN_NUMBERING_NOTE
        result["native_symbol_source"] = PROJECT_SYMBOLS.relative_to(ROOT).as_posix()
    result["sources"] = [GOLDEN.relative_to(ROOT).as_posix(),
                         POLARITY.relative_to(ROOT).as_posix()] + (
        [PROJECT_SYMBOLS.relative_to(ROOT).as_posix()] if placed else [])
    result["symbols"] = symbols
    result["next_gate"] = next_gate
    return result


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
