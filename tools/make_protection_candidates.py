"""Derive PROT-02 independent-latch candidates from the 48 V eight-SR probe deck.

The parent deck already reached 320 us on the saved axis and saves all eight
SR gate, drain and sense-current nodes.  Each candidate appends *only*:

* a dedicated 12 V bias for the protection logic (``Vddp``);
* an UVLO detector on that bias (default inhibit when it is missing);
* a set-dominant latch that clears on an UVLO power cycle;
* ten active pull-downs (0.05 ohm) on both primary gates and all eight SR gates.

Candidate A triggers on the existing filtered ``V(oc) > 1 V`` (the documented
Level-1 OC decision) and therefore isolates the *actuation* path.  Candidate B
adds a 10 us low-pass on the CT burden node and triggers at 1.8 V, so it tests
an independent faster detection path.  The filter is a behavioural integrator
(``B`` current source into a capacitor), not a passive RC: ``V(ocd)`` sits on
the 10 ohm CT burden, so a 1 k series resistor there would give a ~100 ns time
constant, not 10 us.  The 1.8 V level is a measured choice: the 121.67 A
pre-fault record has a 10 us-filtered peak of 1.0498 V, so the threshold keeps
a 0.75 V margin instead of false-tripping on CT ripple.

Neither deck is hardware evidence.  The clamps are idealized switches; no SOA,
thermal, comparator noise, gate-loop inductance or restart sequencing exists.

Usage:
    python tools/make_protection_candidates.py --write
    python tools/make_protection_candidates.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir"
SAVE_ANCHOR = "+ I(VSa2) I(VSb2) I(VSa3) I(VSb3)\n"
TRIGGER_A = "V(oc)"
TRIGGER_B = "V(ocdf,ocm)"
CANDIDATES = {
    "prot_a_oc1v": {
        "trigger": TRIGGER_A,
        "threshold": "1",
        "extra_save": "",
        "fast_filter": "",
        "arming": True,
        "note": "existing V(oc)>1 V OC decision; independent actuation only",
    },
    "prot_b_fast10u_1p8v": {
        "trigger": TRIGGER_B,
        "threshold": "1.8",
        "extra_save": " V(ocdf)",
        "fast_filter": (
            "* independent fast path: 10 us low-pass driven by a high-impedance\n"
            "* behavioural buffer, so the 10 ohm CT burden is not loaded.\n"
            "Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k\n"
            "Cocdf ocdf ocm 10n\n"
            "Rocdf ocdf ocm 1G\n"
        ),
        "arming": True,
        "note": "10 us-filtered V(ocd)>1.8 V; trips before the 47 us OC filter",
    },
    # Negative control: the same fast path with no soft-start blanking.  The
    # first PROT-B run was this deck and it was dead over the whole saved
    # window; keeping it reproducible stops the arming latch from looking like
    # an optional refinement.
    "prot_b_unarmed": {
        "trigger": TRIGGER_B,
        "threshold": "1.8",
        "extra_save": " V(ocdf)",
        "fast_filter": (
            "* independent fast path: 10 us low-pass driven by a high-impedance\n"
            "* behavioural buffer, so the 10 ohm CT burden is not loaded.\n"
            "Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k\n"
            "Cocdf ocdf ocm 10n\n"
            "Rocdf ocdf ocm 1G\n"
        ),
        "arming": False,
        "note": "negative control: 1.8 V fast path with no soft-start blanking",
    },
}
# 100 ns set/reset is a modelling choice (1 nF, 10 V/us), not a datasheet number.
TAU_PROT = "100n"
CLAMP_OHM = ".05"
# Soft-start blanking: the arming latch closes once V(ss) is 0.25 V below its
# 5.05 V steady value.  Without it the 1.8 V CT threshold latches during the
# startup inrush -- measured on the first PROT-B raw, where V(prot) was already
# 0.998 at the first saved sample and V(out) was 1.5e-8.
ARM_SS_V = 4.8
GATES = (
    ("gh", "sw"), ("gl", "0"),
    ("ga1", "sgnd"), ("gb1", "sgnd"),
    ("ga2", "sgnd"), ("gb2", "sgnd"),
    ("ga3", "sgnd"), ("gb3", "sgnd"),
    ("ga4", "sgnd"), ("gb4", "sgnd"),
)


def destination(case: str) -> Path:
    if case not in CANDIDATES:
        raise ValueError(f"unknown protection candidate: {case}")
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe_{case}.cir"


def uvlo_destination() -> Path:
    return ROOT / "sim/v3/prot_latch_uvlo_check.cir"


def header(case: str) -> str:
    note = CANDIDATES[case]["note"]
    return (
        "* UNRUN PROT-02 candidate: independent latched gate inhibit (NOT hardware).\n"
        f"* Trigger: {note}.\n"
        "* Only the protection block, its save nodes and the header are added;\n"
        "* the parent power circuit, fault branch and .tran are byte-identical.\n"
        "* No SOA, thermal, comparator-noise, gate-loop or restart sequencing model.\n"
    )


def latch_terms() -> str:
    """Two one-way latches: arm on soft-start completion, then set the inhibit."""
    return (
        "Carm arm 0 1n IC=0\n"
        "Rarm arm 0 1G\n"
        f"Barm arm 0 I=if(V(ss)>{ARM_SS_V},-(1-V(arm))*(1n/{TAU_PROT}),0)\n"
    )


def protection_block(case: str) -> str:
    spec = CANDIDATES[case]
    clamps = "".join(f"S{node} {node} {ref} inhib 0 PROT_KILL\n" for node, ref in GATES)
    set_term = (f"if({spec['trigger']}>{spec['threshold']},"
                f"-(1-V(prot))*(1n/{TAU_PROT}),0)")
    if spec["arming"]:
        blanking = (
            "* The latch is blanked until soft start completes (V(ss) > 4.8 V): an\n"
            "* unarmed 1.8 V CT threshold latches on the startup inrush.\n"
            "* In hardware the latch would clear on an UVLO power cycle; this\n"
            "* model never clears, so restart sequencing is not tested.\n"
        )
        set_term = f"if(V(arm)>.5,{set_term},0)"
    else:
        blanking = (
            "* NEGATIVE CONTROL: no soft-start blanking.  This deck is expected to\n"
            "* latch during the 2 ms pre-history and to be dead over the window.\n"
        )
    return (
        "* ---- PROT-02 candidate: independent latched gate inhibit ---------------\n"
        "* Default-off at undervoltage: Vddp below 8 V asserts inhibit directly.\n"
        f"{blanking}"
        "* 0.05 ohm active pull-downs stand in for external gate-kill devices.\n"
        f"{spec['fast_filter']}"
        "Vddp vddp 0 12\n"
        "Buvlo uvlo 0 V=if(V(vddp)<8,1,0)\n"
        f"{latch_terms() if spec['arming'] else ''}"
        "Cprot prot 0 1n IC=0\n"
        "Rprot prot 0 1G\n"
        f"Bprot prot 0 I=if(V(uvlo)>.5,-V(prot)*(1n/{TAU_PROT}),{set_term})\n"
        "Binhib inhib 0 V=if(V(uvlo)>.5,1,if(V(prot)>.5,1,0))\n"
        f"{clamps}"
        f".model PROT_KILL SW(Ron={CLAMP_OHM} Roff=1G Vt=.5)\n"
    )


def save_line(case: str) -> str:
    spec = CANDIDATES[case]
    arm = " V(arm)" if spec["arming"] else ""
    return f"+ V(prot) V(inhib) V(uvlo) V(vddp){arm} V(gh) V(gl){spec['extra_save']}\n"


def build(base: str, case: str) -> str:
    """Append the protection block; every other byte of ``base`` is unchanged."""
    if case not in CANDIDATES:
        raise ValueError(f"unknown protection candidate: {case}")
    if base.count(SAVE_ANCHOR) != 1:
        raise ValueError("parent save block anchor is not unique")
    if base.count("\n.end\n") != 1:
        raise ValueError("parent deck must have exactly one final .end")
    if "PROT-02 candidate" in base or "PROT_KILL" in base:
        raise ValueError("parent deck already carries a protection block")
    for node, _ in GATES:
        if f" {node} " not in base:
            raise ValueError(f"parent deck lacks gate node {node}")
    body = base.replace(SAVE_ANCHOR, SAVE_ANCHOR + save_line(case), 1)
    body = body.replace("\n.end\n", "\n" + protection_block(case) + ".end\n", 1)
    return header(case) + body


def uvlo_deck() -> str:
    """Small sub-circuit proof that a missing Vddp forces the dummy gate low."""
    clamps = "Sg g 0 inhib 0 PROT_KILL\n"
    return (
        "* UVLO default-off sub-circuit check for the PROT-02 latch (NOT hardware).\n"
        "* The dummy gate is driven through 3.2 ohm and clamped by the same switch;\n"
        "* Vddp falls at 100 us, so the gate must fall without any fault trigger.\n"
        "Vddp vddp 0 PWL(0 12 100u 12 100.1u 0 200u 0)\n"
        "Vss ss 0 5\n"
        "Vdrv drv 0 10\n"
        "Rdrv drv g 3.2\n"
        "Cg g 0 10n\n"
        "Buvlo uvlo 0 V=if(V(vddp)<8,1,0)\n"
        f"{latch_terms()}"
        "Cprot prot 0 1n IC=0\n"
        "Rprot prot 0 1G\n"
        # Same arming guard as the candidates, but no fault trigger at all.
        "Bprot prot 0 I=if(V(uvlo)>.5,-V(prot)*(1n/100n),0)\n"
        "Binhib inhib 0 V=if(V(uvlo)>.5,1,if(V(prot)>.5,1,0))\n"
        f"{clamps}"
        ".model PROT_KILL SW(Ron=.05 Roff=1G Vt=.5)\n"
        ".tran 0 200u 0 10n\n"
        ".save V(vddp) V(ss) V(uvlo) V(arm) V(prot) V(inhib) V(g)\n"
        ".meas tran ARM_AFTER AVG V(arm) FROM=150u TO=199u\n"
        ".meas tran G_BEFORE AVG V(g) FROM=90u TO=99u\n"
        ".meas tran G_AFTER AVG V(g) FROM=150u TO=199u\n"
        ".meas tran INHIB_AFTER AVG V(inhib) FROM=150u TO=199u\n"
        ".end\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not BASE.is_file():
        raise SystemExit(f"missing parent deck: {BASE}")
    base = BASE.read_text(encoding="utf-8")
    outputs = [(destination(case), build(base, case)) for case in CANDIDATES]
    outputs.append((uvlo_destination(), uvlo_deck()))
    for path, text in outputs:
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            raise SystemExit(f"stale protection deck: {path}; rerun with --write")
        print(path.name, "UNRUN protection candidate; not hardware evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
