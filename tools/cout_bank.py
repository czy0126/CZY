"""How many output capacitors, and which requirement decides the count.

Three independent requirements come out of the 100 A model point:

    capacitance  >= 4 mF      the value the model runs with
    bank ESR     <= 0.2 mohm  the value the model runs with (Rser=0.2m)
    RMS current  >= 52.48 A   rebuilt from the four SR currents (KCL)

They do not scale together, so the bank size is set by whichever needs the most
parts.  Part data below is a *candidate*, not a selection: the numbers were
taken from a vendor page summary and no datasheet was read, so every row must be
confirmed before it enters a purchase order.

Usage:
    python tools/cout_bank.py --json design/v3/bom/cout_bank.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REQUIREMENTS = {"capacitance_f": 4.0e-3, "esr_ohm": 0.2e-3, "irms_a": 52.4783}

# Candidate parts (network search summary, NOT datasheet-verified).
CANDIDATES = [
    {"mpn": "KEMET A720V477M2R5APE003", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 3e-3,
     "irms_a": 11.69, "case": "2917 (7.3 x 4.3 mm)", "height_mm": 2.1},
    {"mpn": "KEMET A798D477M2R5PTE006", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 6e-3,
     "irms_a": 6.46, "case": "SMD", "height_mm": 3.1},
    {"mpn": "Chemi-Con APSF2R5ELL471MF08S", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 5e-3,
     "irms_a": 5.9, "case": "radial 6.3 x 8 mm", "height_mm": 8.0},
]


def parts_needed(part: dict[str, float], requirements: dict[str, float] = REQUIREMENTS) -> dict[str, object]:
    """Smallest parallel count that meets each requirement, and the one that wins.

    The ceilings are strict on purpose: a ratio that lands a hair above an integer
    buys one extra part, never one fewer.  Do not "fix" that by rounding.
    """
    n_cap = math.ceil(requirements["capacitance_f"] / part["c_f"])
    n_esr = math.ceil(part["esr_ohm"] / requirements["esr_ohm"])
    n_rms = math.ceil(requirements["irms_a"] / part["irms_a"])
    counts = {"capacitance": n_cap, "esr": n_esr, "rms": n_rms}
    n = max(counts.values())
    governing = max(counts, key=lambda k: counts[k])
    return {
        "part": part["mpn"],
        "counts": counts,
        "n": n,
        "governed_by": governing,
        "bank_capacitance_f": n * part["c_f"],
        "bank_esr_ohm": part["esr_ohm"] / n,
        "bank_irms_a": n * part["irms_a"],
        "v_rated": part["v_rated"],
        "height_mm": part["height_mm"],
        "esr_margin_frac": requirements["esr_ohm"] / (part["esr_ohm"] / n),
    }


def report(requirements: dict[str, float] = REQUIREMENTS) -> dict[str, object]:
    banks = [parts_needed(part, requirements) for part in CANDIDATES]
    best = min(banks, key=lambda b: (b["n"], b["height_mm"]))
    return {
        "status": "sizing only; part data is search-sourced, not datasheet-verified",
        "requirements": {
            "capacitance_f": requirements["capacitance_f"],
            "esr_ohm": requirements["esr_ohm"],
            "irms_a": requirements["irms_a"],
            "note": "capacitance and ESR are the values the 100 A model runs with; "
                    "RMS is measured from the four SR currents",
        },
        "banks": banks,
        "fewest_parts": best["part"],
        "no_output_ripple_spec": True,
        "caveats": [
            "bank ESR = part ESR / N assumes zero interconnect resistance; at N>=15 the "
            "copper spreading resistance is not negligible and is not modelled here",
            "0.2 mohm is the value the simulation ran with, not a specified limit; "
            "at 0.1 mohm the count doubles",
            "part data is a vendor page summary; capacitance at 2 V bias, ESR at "
            "temperature and end of life are not included",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/cout_bank.json"))
    args = ap.parse_args()
    data = report()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)
    for bank in data["banks"]:
        print(f"{bank['part']}: N={bank['n']} ({bank['governed_by']}) "
              f"C={bank['bank_capacitance_f'] * 1e3:.2f} mF  ESR={bank['bank_esr_ohm'] * 1e3:.3f} mOhm  "
              f"RMS={bank['bank_irms_a']:.1f} A  h={bank['height_mm']} mm")


if __name__ == "__main__":
    main()
