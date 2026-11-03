"""Build 120 A target true cold-start and severe overload decks from SAME cold models.

These are UNRUN stress candidates. The existing 48 V baseline uses RL=20m.
The 15.4m target was selected from the steady-state 121.67A simulation,
but a cold-start is NOT a 120A current test before output voltage rises.

The cold_oc deck also gets a ``_cshunt`` CONVERGENCE_DIAGNOSTIC child: the
base run stops advancing at 7.5714 ms of 8 ms, and cshunt is the aid that
completed the otherwise identical 50 V hot-fault stall.  It is not a result
on its own and must be compared over the common prefix first.

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
OPTIONS = ".options plotwinsize=0 method=gear"
# CONVERGENCE_DIAGNOSTIC: the unmodified cold_oc fault solve stops advancing
# at 7.5714 ms of its 8 ms window (1e-17 s steps, 11.55 GB written).  Every
# saved voltage is frozen there while the charge-defined SR internals move, the
# same signature the 50 V hot-fault stall showed, and that one completed after
# cshunt put a finite capacitance on nodes that were charge-only.  1 fF is
# 795 kOhm at 200 kHz, i.e. unmeasurable here; the run must still be compared
# with the base over the common prefix before its 8 ms numbers are quoted.
CSHUNT_OPTIONS = OPTIONS + " cshunt=1e-15"
CSHUNT_HEADER = (
    "* CONVERGENCE_DIAGNOSTIC: the 48V/120A cold-overload deck with ONLY\n"
    "* cshunt=1 fF added to .options; circuit, fault block, .tran window and\n"
    "* all .meas lines are byte-identical.  UNRUN, NOT HARDWARE RATED.\n"
    "* This deck is not a result by itself: compare the common pre-stall\n"
    "* prefix against the base record before quoting any 8 ms value.\n"
)


def dest(kind: str) -> Path:
    return ROOT / f"sim/v3/sr_tank_dual_v33_{kind}_vin48_i120_target.cir"


def cshunt_dest(kind: str) -> Path:
    base = dest(kind)
    return base.with_name(base.stem + "_cshunt" + base.suffix)


def cshunt_variant(generated: str) -> str:
    """Add one solver option; refuse if the base text is not what we expect."""
    if generated.count(OPTIONS) != 1:
        raise ValueError("base deck no longer has exactly one .options line")
    return CSHUNT_HEADER + generated.replace(OPTIONS, CSHUNT_OPTIONS)


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
    return note(kind) + source.replace(PARAM, NEW)


def note(kind: str) -> str:
    """Generated header; the fault variant corrects the parent's severity figure."""
    text = (
        "* HIGH-OUTPUT 48V/15.4mOHM TRUE-COLD START: UNRUN, NO HW RATING\n"
        f"* Variant={kind}; only load RL changes vs the parent cold model.\n"
        "* V(out) starts at zero; '120A' is only the eventual target.\n"
        "* NOT a fault-peak, short-circuit, thermal or hardware certification.\n"
    )
    if kind == "cold_oc":
        text += (
            "* The parent fault block quotes 1.818 mOhm / 11x for its 20 mOhm load;\n"
            "* with RL=15.4m the same Ron+Rflt branch is 1.770 mOhm = 8.7x.\n"
        )
    return text


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
    # Only the fault deck stalls; a cshunt control for the clean cold start
    # would answer a question nobody asked and add another GB-scale raw.
    base_oc = dest("cold_oc")
    expected = cshunt_variant(build(SOURCES["cold_oc"].read_text(encoding="utf-8"), "cold_oc"))
    variant = cshunt_dest("cold_oc")
    if args.write:
        variant.write_text(expected, encoding="utf-8", newline="\n")
    elif variant.read_text(encoding="utf-8") != expected:
        raise SystemExit(f"stale {variant.name}; regenerate with --write")
    print(f"{variant.relative_to(ROOT)}: CONVERGENCE_DIAGNOSTIC, cshunt=1 fF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
