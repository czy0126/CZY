"""Build strictly parameter-only high-output LTspice variants from the physical 100 A deck.

Not run or rated. Real achieved current must be measured from the waveform;
the load resistance is a *candidate* chosen for the desired current.
Do not modify controller, SR behaviour, Lr/Cr, protection or startup model here.

Run: python tools/make_high_output_decks.py --write
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir"
PARAM = ".param VIN=48 RL=18.9m LP=10u LR_TOTAL=1u CR_TOTAL=620n"
CASES = {
    "vin48_i110": ("48", "16.9m"),
    "vin48_i120": ("48", "15.4m"),
    "vin50_i110": ("50", "17.8m"),
    "vin50_i120": ("50", "16.3m"),
}


def build(source: str, vin: str, rl: str) -> str:
    if source.count(PARAM) != 1:
        raise ValueError("base physical deck changed: parameter line is not unique")
    # Insert one audit header. Every SPICE instruction apart from VIN/RL stays exact.
    hdr = (
        "* HIGH OUTPUT SENSITIVITY ONLY - UNRUN, NOT HARDWARE RATED\n"
        f"* VIN={vin} V RL={rl}; actual Iout is an unknown simulation result\n"
        "* Source: sr_tank_dual_v33_ss_1ms_100a_phys.cir; only VIN and RL change.\n"
    )
    return hdr + source.replace(PARAM, f".param VIN={vin} RL={rl} LP=10u LR_TOTAL=1u CR_TOTAL=620n")


def filename(name: str) -> Path:
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_1ms_{name}.cir"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--write", action="store_true")
    args = a.parse_args()
    base = BASE.read_text(encoding="utf-8")
    for name, (vin, rl) in CASES.items():
        expected = build(base, vin, rl)
        dest = filename(name)
        if args.write:
            dest.write_text(expected, encoding="utf-8", newline="\n")
        else:
            if dest.read_text(encoding="utf-8") != expected:
                raise SystemExit(f"stale {dest.name} -- rerun --write")
        print(f"{dest.name}: VIN={vin}, RL={rl}; UNRUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
