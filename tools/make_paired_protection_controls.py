"""Build 50 V topology-matched controls for PROT-A / PROT-B.

Two controls are generated per candidate because the first design measurably
failed its own pairing criterion:

* ``_noclamp_control.cir`` -- only ``Vt`` moves from .5 V to 10 V.  The clamps
  cannot close, but the switch model leaves the transition band around ``Vt``,
  so the solver takes a different pre-fault path.  Measured on the 50 V A pair:
  the control matches its own parent deck to 0.04 mV while the candidate sits
  13.2 mV above it, and the candidate uses 2.1x the pre-fault samples.  Raising
  ``Vt`` therefore changes both the clamp action *and* the numerical state.
* ``_thrmute_control.cir`` -- the ``PROT_KILL`` switch model is byte-identical;
  only the ``Bprot`` trigger threshold is raised to 100 V so the latch never
  sets.  Before the fault the comparison constant is false in both decks and
  the switch control node is 0 V in both, so the pre-fault path is preserved.
  This is the control the <=1 mV pairing criterion needs; the Vt=10 deck is
  kept as the negative control that demonstrates why.

Both controls are NON-FAB and never claim to provide protection.

Usage:
    python tools/make_paired_protection_controls.py --write
    python tools/make_paired_protection_controls.py
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    "prot_a_oc1v": "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir",
    "prot_b_fast10u_1p8v": "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir",
}
ACTIVE = ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)"
INACTIVE = ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=10)"
MUTED_THRESHOLD_V = 100
TRIGGER = re.compile(r"(if\(V\([^)]*\))>([0-9.]+)(,-\(1-V\(prot\)\))")
KINDS = ("noclamp", "thrmute")
HEADER = {
    "noclamp": (
        "* UNRUN 50V paired-control #1: gate-clamp switches intentionally NEVER close.\n"
        "* MODEL/NON-FAB ONLY; protection is intentionally inoperative in this control.\n"
        "* MEASURED LIMIT: raising Vt .5->10 V also leaves the switch transition band,\n"
        "* so this control matches the parent deck, not the candidate (pre-fault Vout\n"
        "* +13.2/+17.5 mV); it cannot satisfy the <=1 mV pairing criterion.\n"
    ),
    "thrmute": (
        "* UNRUN 50V paired-control #2: switch model byte-identical, trigger muted.\n"
        "* MODEL/NON-FAB ONLY; protection is intentionally inoperative in this control.\n"
        "* Only the Bprot threshold is raised to 100 V, so the latch never sets while\n"
        "* the pre-fault numerical path stays that of the candidate.\n"
        "* A pass requires LTspice completion and pre-fault Vout matching <=1mV.\n"
    ),
}


def source_path(case: str) -> Path:
    return ROOT / SPECS[case]


def destination(case: str, kind: str) -> Path:
    suffix = {"noclamp": "_noclamp_control.cir", "thrmute": "_thrmute_control.cir"}[kind]
    return source_path(case).with_name(source_path(case).stem + suffix)


def validate(source: str) -> None:
    if source.count(ACTIVE) != 1 or source.count("inhib 0 PROT_KILL") != 10:
        raise ValueError("source must contain exactly ten normal clamp switches and one active model")
    if ".options plotwinsize=0 method=gear cshunt=1e-15" not in source:
        raise ValueError("50V source must retain the convergent 1fF solver variant")
    if len(TRIGGER.findall(source)) != 1:
        raise ValueError("source must contain exactly one Bprot latch-set trigger")
    if f">{MUTED_THRESHOLD_V}," in source:
        raise ValueError(f"source already contains the muted {MUTED_THRESHOLD_V} V threshold")


def vt10_source(source: str) -> str:
    validate(source)
    return source.replace(ACTIVE, INACTIVE, 1)


def threshold_muted_source(source: str) -> str:
    validate(source)
    return TRIGGER.sub(rf"\g<1>>{MUTED_THRESHOLD_V}\g<3>", source, count=1)


BUILDERS = {"noclamp": vt10_source, "thrmute": threshold_muted_source}


def build(source: str, kind: str) -> str:
    return HEADER[kind] + BUILDERS[kind](source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    opts = parser.parse_args()
    for case in SPECS:
        source = source_path(case).read_text(encoding="utf-8")
        for kind in KINDS:
            expected = build(source, kind)
            out = destination(case, kind)
            if opts.write:
                out.write_text(expected, encoding="utf-8", newline="\n")
            elif not out.exists() or out.read_text(encoding="utf-8") != expected:
                raise SystemExit(f"stale unrun paired control: {out}")
            print(case, kind, "UNRUN paired-control only; no LTspice/hardware qualification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
