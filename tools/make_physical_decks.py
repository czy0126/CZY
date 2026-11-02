"""Generate the deck variants issue #4 asks for.

The frozen v3 decks run `Lr=0.92 uH` (external) and `Cout=4 mF`.  The design
package specifies an external Lr of 1.0 uH nominal, a trimmed target of
1.0 uH - leakage, and a 15 x 470 uF = 7.05 mF bank.  Each variant below changes
exactly the named elements and nothing else, so the difference between two
results is the difference between those values.

    prod      0.92 uH external + 7.05 mF   the design tank with the physical bank
    untrimmed 1.0  uH external + 7.05 mF   the part wound to the nominal 1.0 uH
    lrmin     0.875 uH external + 7.05 mF  worst case: 0.125 uH leakage

The frozen decks themselves are never rewritten: `main()` only writes the
variants named on the command line (or all of them when none is named).  Do not
regenerate a deck whose raw is still being produced by a running LTspice.

Usage:
    python tools/make_physical_decks.py                # all variants
    python tools/make_physical_decks.py cout7m         # one variant
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SS_100A = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
SS_100A_LEDGER = "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir"
COLD = "sim/v2/sr_tank_dual_v33_cold.cir"
COLD_OC = "sim/v2/sr_tank_dual_v33_cold_oc.cir"

OLD_LR = "LR_TOTAL=.92u"
OLD_COUT = "Cout out sgnd 4m Rser=0.2m"

LR_RE = re.compile(r"LR_TOTAL=[0-9.]+u")
COUT_RE = re.compile(r"Cout out sgnd [0-9.]+m Rser=0\.2m")
TRAN_RE = re.compile(r"^\.tran ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) uic$", re.M)
LR_TOTAL_RE = re.compile(r"^Lr \S+ \S+ \{LR_TOTAL\} ", re.M)
# ELE-09: the four aligned step lengths are four operating points because the
# resistive load lets the output settle wherever the model's loss balance puts
# it.  They can only be compared at one operating point, so the load is
# replaced by a sink that fixes the *current* and lets V(out) land wherever the
# converter's own characteristic takes it.
#
# Why not a voltage source: the SR controller is load triggered -- it turns on
# when the body diode conducts -- so an ideal source clamps the centre tap from
# t=0 and the rectifier never starts.  Measured on the 5 ns trial: V(ga1) never
# passed 0.12 V, I(xsa1:Dbd) peaked at 3 mA, I(Lr) stayed inside +-0.77 A and
# I(Rin) averaged -0.05 A.
#
# A regulated sink failed a second way: I = max(1053 x (V - 1.889), 0) draws
# nothing until V(out) reaches 1.889 V, but an *unloaded* converter only reaches
# 1.794 V here -- the SR needs load current to start, so the rectifier is two
# body diodes.  The sink sat on its own knee: V(out) 1.7944 V, I(Bload) 0.0000 A,
# I(Lr) +-0.76 A for the whole run.
#
# A ramped current sink sidesteps both: zero until 500 us, so the cold start is
# the one the resistive deck had, then the same 100 A the resistor drew.
LOAD = "Rload out sgnd {RL}"
SINK_PWL = "PWL(0 0 500u 0 750u 100)"


def sink_load(source: str, pwl: str = SINK_PWL) -> str:
    """Replace the resistive load with a ramped constant-current sink.

    A strict count check, like the other swaps: a spent pattern would output a
    "sink" deck that is still the resistive one.
    """
    count = source.count(LOAD)
    if count != 1:
        raise ValueError(f"expected exactly one '{LOAD}' line, found {count}")
    return source.replace(LOAD, f"Iload out sgnd {pwl}")


def variant_text(source: str, lr: str | None = None, cout: str | None = None,
                 step: str | None = None, stop: str | None = None,
                 sink: bool = False) -> str:
    """Return the deck text with the requested values swapped in.

    ``None`` leaves an element untouched.  Each pattern must occur exactly once:
    a silent zero-match would produce a "variant" deck that is still the old one.
    """
    swaps = []
    if lr is not None:
        swaps.append((LR_RE, f"LR_TOTAL={lr}", "LR_TOTAL"))
    if cout is not None:
        swaps.append((COUT_RE, f"Cout out sgnd {cout} Rser=0.2m", "Cout"))
    for pattern, value, name in swaps:
        count = len(pattern.findall(source))
        if count != 1:
            raise ValueError(f"expected exactly one {name} pattern, found {count}")
        source = pattern.sub(value, source)
    if lr is not None and not LR_TOTAL_RE.search(source):
        raise ValueError("the Lr element does not use LR_TOTAL; the param swap would not reach it")
    if sink:
        source = sink_load(source)
    if step is not None or stop is not None:
        match = TRAN_RE.search(source)
        if not match:
            raise ValueError("no '.tran <Tstep> <Tstop> <Tstart> <Tmaxstep> uic' line to rewrite")
        # LTspice field order is Tstep Tstop Tstart Tmaxstep: the deck's
        # `.tran 0 1000u 880u 5n uic` saves nothing extra, stops at 1000 us,
        # starts writing at 880 us and steps at most 5 ns.
        source = source[:match.start()] + (
            f".tran {match.group(1)} {stop or match.group(2)} {match.group(3)} "
            f"{step or match.group(4)} uic"
        ) + source[match.end():]
    return source


# name -> (source, target, external Lr, Cout, max timestep, stop time)
VARIANTS: dict[str, tuple[str, str, str | None, str | None, str | None, str | None]] = {
    "phys": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir", "1u", "7.05m", None, None),
    "cout7m": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir", ".92u", "7.05m", None, None),
    "lrmin": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_lrmin.cir", ".875u", "7.05m", None, None),
    "cold_phys": (COLD, "sim/v3/sr_tank_dual_v33_cold_phys.cir", "1u", "7.05m", None, None),
    "cold_oc_phys": (COLD_OC, "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir", "1u", "7.05m", None, None),
    "cold_oc_lrmin": (COLD_OC, "sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir", ".875u", "7.05m", None, None),
    # Issue #6: the same instrumented deck at half the timestep, so the
    # port/branch integrals can be compared at 5 ns and 2 ns.
    "ledger2n": (SS_100A_LEDGER, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.cir",
                 None, None, "2n", None),
    # Issue #6: the same instrumented deck saved over the first *phase-aligned*
    # window (133 gate periods = 662.9 us, the length at which the 200.622 kHz
    # clock and the 202.131 kHz tank return to the same relative phase).  Only
    # the stop time changes, so the 880 us settle is untouched.
    "ledger_aligned": (SS_100A_LEDGER, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned.cir",
                       None, None, None, "1550u"),
    # Issue #6: the phase-aligned window at half the timestep.  On the 16-period
    # window the same 5 ns / 2 ns pair moves the *period-averaged* closure by
    # 0.38 W, so the aligned window -- which was only run at 5 ns -- needs the
    # same test before its +0.33 W can be quoted.
    "ledger_aligned2n": (SS_100A_LEDGER, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned2n.cir",
                         None, None, "2n", "1550u"),
    # Issue #6, task item 3 asks for 5 / 2 / 1 ns.  The 2 ns run took ~6 min, so
    # the third step is cheap; it is the one that shows whether the 0.625 W the
    # loss list moved between 5 ns and 2 ns is a step-size artifact or the start
    # of a plateau.
    "ledger_aligned1n": (SS_100A_LEDGER, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned1n.cir",
                         None, None, "1n", "1550u"),
    # Issue #6, task item 3's optional <=0.5 ns leg.  5/2/1 ns is not a
    # monotone sequence -- the loss list reads 10.73 / 11.36 / 9.98 W -- so a
    # third point cannot tell a plateau from a constant error.  Half a
    # nanosecond is the finest step the repository's raw budget allows; the
    # point is to see whether the last leg shrinks or reverses again, not to
    # declare the smallest number "the answer".
    "ledger_aligned0p5n": (SS_100A_LEDGER,
                           "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned0p5n.cir",
                           None, None, "0.5n", "1550u"),
    # ELE-09: the same-window companion at half the timestep for the 50 V/120 A
    # candidate.  Its 22-period ledger leaves 0.499 W in the loss residual
    # after the gate-drive boundary correction; the dominant unknown is the
    # 6.15 W SR body-diode forward term, whose 100 A counterpart moved 1.4 W
    # across 5/2/1 ns.  Only the max timestep changes, so VIN/RL and Tstart --
    # and therefore the window -- stay identical.
    "vin50_i120_cin_2n": ("sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
                          "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_2n.cir",
                          None, None, "2n", None),
    # ELE-09, decisive leg: the same 50 V/120 A deck over one phase-aligned
    # window (133 gate periods = 662.9 us).  The 22-period step pair moved the
    # port term by 0.41 W, so only this window can say whether the residual is
    # a physical gap or an endpoint/phase artefact.  Start stays 880 us, so the
    # settled state is the one the 22-period ledger already measured.
    "vin50_i120_cin_aligned": ("sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
                               "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin_aligned.cir",
                               None, None, None, "1550u"),
}


# ELE-09 follow-up: the four aligned step lengths are four operating points,
# not four discretisations of one.  These two decks replace the resistive load
# with the ramped current sink (see SINK_PWL) so I(out) is the same in both and
# V(out) is free to say what the converter's characteristic does.  Only the two
# extremes are generated: if the operating point is what moves the SR term, the
# end pair answers it and the middle steps are only confirmation.
# name -> (source, target, max timestep, stop time)
CSINK: dict[str, tuple[str, str, str | None, str | None]] = {
    "csink5n": (SS_100A_LEDGER,
                "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned_csink5n.cir",
                None, "1550u"),
    "csink0p5n": (SS_100A_LEDGER,
                  "sim/v3/sr_tank_dual_v33_ss_1ms_100a_aligned_csink0p5n.cir",
                  "0.5n", "1550u"),
}


def write(name: str) -> None:
    if name in VARIANTS:
        src, dst, lr, cout, step, stop = VARIANTS[name]
        kwargs = {"lr": lr, "cout": cout, "step": step, "stop": stop}
    elif name in CSINK:
        src, dst, step, stop = CSINK[name]
        kwargs = {"step": step, "stop": stop, "sink": True}
    else:
        raise KeyError(name)
    source = (ROOT / src).read_text(encoding="utf-8")
    (ROOT / dst).write_text(variant_text(source, **kwargs), encoding="utf-8")
    print(f"wrote {dst}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="variant names to write; default all")
    args = ap.parse_args(argv)
    known = [*VARIANTS, *CSINK]
    unknown = [n for n in args.names if n not in known]
    if unknown:
        ap.error(f"unknown variant(s) {unknown}; known: {sorted(known)}")
    for name in args.names or known:
        write(name)


if __name__ == "__main__":
    main()
