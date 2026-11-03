"""Build 50V topology-matched non-clamping controls for PROT-A / PROT-B.

The existing cshunt=1fF 50V comparator and candidate simulations have 13-18mV
pre-fault Vout mismatch, so their reported percent relief is not a paired
causal comparison. These NON-FAB, UNRUN decks preserve comparator, filtered
fault path, latch, ten gate-kill *switches*, power circuit and solver settings.
Only PROT_KILL's threshold is changed from .5 to 10 V, so a 1V inhibit cannot
actually turn on a clamp. Even this control may shift the numerical path:
run, measure and reject if Vout mismatch >1mV before quoting causal benefit.

Usage:
    python tools/make_paired_protection_controls.py --write
    python tools/make_paired_protection_controls.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = {
    "prot_a_oc1v": "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir",
    "prot_b_fast10u_1p8v": "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir",
}
ACTIVE = ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)"
INACTIVE = ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=10)"
HEADER = (
    "* UNRUN 50V paired-control experiment: gate-clamp switches intentionally NEVER close.\n"
    "* MODEL/NON-FAB ONLY; protection is intentionally inoperative in this control.\n"
    "* A pass requires LTspice completion, pre-fault Vout matching <=1mV and full waveform review.\n"
)


def destination(case: str) -> Path:
    return (ROOT / SPECS[case]).with_name((ROOT / SPECS[case]).stem + "_noclamp_control.cir")


def build(source: str) -> str:
    if source.count(ACTIVE) != 1 or source.count("inhib 0 PROT_KILL") != 10:
        raise ValueError("source must contain exactly ten normal clamp switches and one active model")
    if ".options plotwinsize=0 method=gear cshunt=1e-15" not in source:
        raise ValueError("50V source must retain the convergent 1fF solver variant")
    return HEADER + source.replace(ACTIVE, INACTIVE, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    opts = parser.parse_args()
    for case, rel in SPECS.items():
        source = (ROOT / rel).read_text(encoding="utf-8")
        expected = build(source)
        out = destination(case)
        if opts.write:
            out.write_text(expected, encoding="utf-8", newline="\n")
        elif out.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"stale unrun paired control: {out}")
        print(case, "UNRUN paired-control only; no LTspice/hardware qualification")


if __name__ == "__main__":
    raise SystemExit(main())
