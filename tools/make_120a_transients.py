"""Build 120 A target true cold-start and severe overload decks from SAME cold models.

These are UNRUN stress candidates. The existing 48 V baseline uses RL=20m.
The 15.4m target was selected from the steady-state 121.67A simulation,
but a cold-start is NOT a 120A current test before output voltage rises.

Usage: python tools/make_120a_transients.py --write
"""
from __future__ import annotations
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "cold": ROOT / "sim/v3/sr_tank_dual_v33_cold_phys.cir",
    "cold_oc": ROOT / "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir",
}
PARAM = ".param VIN=48 RL=20m LP=10u LR_TOTAL=1u CR_TOTAL=620n"
NEW = ".param VIN=48 RL=15.4m LP=10u LR_TOTAL=1u CR_TOTAL=620n"


def dest(kind: str) -> Path:
    return ROOT / f"sim/v3/sr_tank_dual_v33_{kind}_vin48_i120_target.cir"


def build(source: str, kind: str) -> str:
    if kind not in SOURCES:
        raise ValueError(f"unsupported variant: {kind}")
    if source.count(PARAM) != 1 or ".ic " in "\n".join(
        x for x in source.splitlines() if not x.lstrip().startswith("*")
    ):
        raise ValueError("cold-start model is no longer unchanged and uninitialised")
    if kind == "cold_oc" and source.count("Sflt out flt ctl 0 SFLT") != 1:
        raise ValueError("the source fault switch must remain present")
    if kind == "cold" and "Sflt out flt ctl 0 SFLT" in source:
        raise ValueError("cold startup variant may not include a fault")
    note = (
        "* HIGH-OUTPUT 48V/15.4mOHM TRUE-COLD START: UNRUN, NO HW RATING\n"
        f"* Variant={kind}; only load RL changes vs the parent cold model.\n"
        "* V(out) starts at zero; '120A' is only the eventual target.\n"
        "* NOT a fault-peak, short-circuit, thermal or hardware certification.\n"
    )
    return note + source.replace(PARAM, NEW)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    for kind, source in SOURCES.items():
        expected = build(source.read_text(encoding="utf-8"), kind)
        path = dest(kind)
        if args.write:
            path.write_text(expected, encoding="utf-8", newline="\n")
        elif path.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"stale {path.name}; regenerate with --write")
        print(f"{path.relative_to(ROOT)}: UNRUN, 48V / RL=15.4m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
