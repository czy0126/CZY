"""Derive PROT-02 independent-latch candidates from the eight-SR probe decks.

The 48 V parent and the 50 V ``cshunt=1 fF`` convergence variant both reached
the full saved window and save all eight SR gate, drain and sense-current
nodes.  Each candidate appends *only*:

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
constant, not 10 us.  The 1.8 V level is a measured choice: the 48 V record has
a 10 us-filtered pre-fault peak of 1.0814 V and the 50 V cshunt record 1.0603 V,
so the same threshold keeps a 0.72-0.74 V margin at both voltages instead of
false-tripping on CT ripple.

The 50 V candidates inherit the ``cshunt=1e-15`` solver option from their
parent: the 50 V base still stalls at 296.929 us, so this is the only 50 V
solve that reaches the declared window.  The caveat travels with the record.

Neither deck is hardware evidence.  The clamps are idealized switches; no SOA,
thermal, comparator noise or gate-loop inductance exists.  Restart sequencing is
exercised only in the sub-circuit ``prot_latch_restart_check.cir``, never in the
power stage: the frozen candidates keep a set-and-hold arming latch because
their committed raws hold Vddp at 12 V for the whole window, and rewriting them
would break the deck/raw pairing.

Usage:
    python tools/make_protection_candidates.py --write
    python tools/make_protection_candidates.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARENTS = {
    "48v": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir",
    # The 50 V base stalls at 296.929 us; this cshunt child is the only 50 V
    # solve that reaches the declared 320 us window.  It carries
    # `.options cshunt=1e-15`, which the derived decks inherit unchanged.
    "50v_cshunt": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe.cir",
}
# Backwards-compatible default: the 48 V parent is what the compare tool and
# the original test module assume when no deck is named explicitly.
BASE = PARENTS["48v"]
SAVE_ANCHOR = "+ I(VSa2) I(VSb2) I(VSa3) I(VSb3)\n"
TRIGGER_A = "V(oc)"
TRIGGER_B = "V(ocdf,ocm)"
FAST_FILTER = (
    "* independent fast path: 10 us low-pass driven by a high-impedance\n"
    "* behavioural buffer, so the 10 ohm CT burden is not loaded.\n"
    "Bocdf ocdf ocm I=(V(ocdf,ocm)-V(ocd,ocm))/1k\n"
    "Cocdf ocdf ocm 10n\n"
    "Rocdf ocdf ocm 1G\n"
)
CANDIDATES = {
    "prot_a_oc1v": {
        "parent": "48v",
        "suffix": "prot_a_oc1v",
        "trigger": TRIGGER_A,
        "threshold": "1",
        "extra_save": "",
        "fast_filter": "",
        "arming": True,
        "note": "existing V(oc)>1 V OC decision; independent actuation only",
    },
    "prot_b_fast10u_1p8v": {
        "parent": "48v",
        "suffix": "prot_b_fast10u_1p8v",
        "trigger": TRIGGER_B,
        "threshold": "1.8",
        "extra_save": " V(ocdf)",
        "fast_filter": FAST_FILTER,
        "arming": True,
        "note": "10 us-filtered V(ocd)>1.8 V; trips before the 47 us OC filter",
    },
    # Negative control: the same fast path with no soft-start blanking.  The
    # first PROT-B run was this deck and it was dead over the whole saved
    # window; keeping it reproducible stops the arming latch from looking like
    # an optional refinement.
    "prot_b_unarmed": {
        "parent": "48v",
        "suffix": "prot_b_unarmed",
        "trigger": TRIGGER_B,
        "threshold": "1.8",
        "extra_save": " V(ocdf)",
        "fast_filter": FAST_FILTER,
        "arming": False,
        "note": "negative control: 1.8 V fast path with no soft-start blanking",
    },
    # 50 V pair.  Same protection block, derived from the cshunt child because
    # the 50 V base still stalls at 296.929 us.  The solver option is inherited
    # unchanged, so the 50 V record is a cshunt record and must say so.
    "prot_a_oc1v_50v": {
        "parent": "50v_cshunt",
        "suffix": "prot_a_oc1v",
        "trigger": TRIGGER_A,
        "threshold": "1",
        "extra_save": "",
        "fast_filter": "",
        "arming": True,
        "note": "50 V cshunt parent: existing V(oc)>1 V OC decision; actuation only",
    },
    "prot_b_fast10u_1p8v_50v": {
        "parent": "50v_cshunt",
        "suffix": "prot_b_fast10u_1p8v",
        "trigger": TRIGGER_B,
        "threshold": "1.8",
        "extra_save": " V(ocdf)",
        "fast_filter": FAST_FILTER,
        "arming": True,
        "note": "50 V cshunt parent: 10 us-filtered V(ocd)>1.8 V fast path",
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
# Restart sub-circuit stimulus.  The soft-start slope is the UCC25600 model
# number (5 uA into 10 nF = 0.5 mV/us), so V(ss) crosses ARM_SS_V 9.6 ms after
# the bias returns; the ramp has to be that slow or the check would not show
# the blanked window at all.
POWER_CYCLE_S = 100e-6
POWER_RETURN_S = 120e-6
SS_RAMP_V_PER_S = 0.5e3
RESTART_PULSE_S = 2.0e-3
REARM_PULSE_S = 10.3e-3
RESTART_STOP_S = 10.6e-3
GATES = (
    ("gh", "sw"), ("gl", "0"),
    ("ga1", "sgnd"), ("gb1", "sgnd"),
    ("ga2", "sgnd"), ("gb2", "sgnd"),
    ("ga3", "sgnd"), ("gb3", "sgnd"),
    ("ga4", "sgnd"), ("gb4", "sgnd"),
)


def spec(case: str) -> dict[str, object]:
    if case not in CANDIDATES:
        raise ValueError(f"unknown protection candidate: {case}")
    return CANDIDATES[case]


def parent_deck(case: str) -> Path:
    return PARENTS[str(spec(case)["parent"])]


def destination(case: str) -> Path:
    parent = parent_deck(case)
    return parent.with_name(f"{parent.stem}_{spec(case)['suffix']}.cir")


def uvlo_destination() -> Path:
    return ROOT / "sim/v3/prot_latch_uvlo_check.cir"


def restart_destination() -> Path:
    return ROOT / "sim/v3/prot_latch_restart_check.cir"


def header(case: str) -> str:
    note = CANDIDATES[case]["note"]
    return (
        "* UNRUN PROT-02 candidate: independent latched gate inhibit (NOT hardware).\n"
        f"* Trigger: {note}.\n"
        "* Only the protection block, its save nodes and the header are added;\n"
        "* the parent power circuit, fault branch and .tran are byte-identical.\n"
        "* No SOA, thermal, comparator-noise, gate-loop or restart sequencing model.\n"
    )


def latch_terms(reset_on_uvlo: bool = False) -> str:
    """Two one-way latches: arm on soft-start completion, then set the inhibit.

    ``reset_on_uvlo`` adds the bias-cycle reset to the *arming* latch.  The
    frozen comparison decks deliberately do not carry it: their raws hold Vddp
    at 12 V for the whole window, so the branch would be inactive anyway, and
    rewriting the decks would break the deck/raw pairing.  The restart
    sub-circuit uses it, because an arming latch that survives a power cycle
    re-arms the fast path during the restart inrush -- the exact failure the
    unarmed negative control demonstrated.
    """
    if reset_on_uvlo:
        # The discharge term is +V(arm), not -V(arm): a B current source's
        # positive current leaves the node, so +V drains the 1 nF cap.  The
        # negative form is positive feedback and diverges (measured 1e86 on
        # the first restart deck); it stayed hidden because every other deck
        # holds Vddp at 12 V, where this branch is never selected.
        return (
            "Carm arm 0 1n IC=0\n"
            "Rarm arm 0 1G\n"
            f"Barm arm 0 I=if(V(uvlo)>.5,V(arm)*(1n/{TAU_PROT}),"
            f"if(V(ss)>{ARM_SS_V},-(1-V(arm))*(1n/{TAU_PROT}),0))\n"
        )
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
        # +V(prot) drains the latch; the negative form is positive feedback.
        # This branch is inactive in the committed power-stage runs (Vddp is a
        # constant 12 V, so V(uvlo) is 0 for the whole window).
        f"Bprot prot 0 I=if(V(uvlo)>.5,V(prot)*(1n/{TAU_PROT}),{set_term})\n"
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
        # +V(prot) drains the latch; the negative form diverges (this deck
        # never sets prot, so it would only show up in a restart run).
        "Bprot prot 0 I=if(V(uvlo)>.5,V(prot)*(1n/100n),0)\n"
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


def _us(seconds: float) -> str:
    return f"{seconds * 1e6:g}u"


def restart_deck() -> str:
    """Sub-circuit proof of the restart order, with the arming-latch reset.

    Sequence: armed -> a CT pulse latches -> a 20 us Vddp power cycle resets
    both latches and holds the gate low -> V(ss) restarts from 0 at 0.5 mV/us
    -> a pulse during that ramp must *not* latch (the fast path is blanked) ->
    once V(ss) passes 4.8 V the arming latch closes and a later pulse must
    latch.  This is logic-only evidence: no power stage, no controller OC and
    no gate driver.
    """
    ss_full_s = POWER_RETURN_S + 5.0 / SS_RAMP_V_PER_S
    pulse_us = 5.0e-6
    vddp = (
        f"PWL(0 12 {_us(POWER_CYCLE_S)} 12 {_us(POWER_CYCLE_S + 0.1e-6)} 0 "
        f"{_us(POWER_RETURN_S - 0.1e-6)} 0 {_us(POWER_RETURN_S)} 12 {_us(RESTART_STOP_S)} 12)"
    )
    ss = (
        f"PWL(0 5 {_us(POWER_CYCLE_S)} 5 {_us(POWER_CYCLE_S + 1e-6)} 0 "
        f"{_us(POWER_RETURN_S)} 0 {_us(ss_full_s)} 5)"
    )
    points = ["0 0"]
    for start, hold in ((60e-6, pulse_us), (RESTART_PULSE_S, pulse_us), (REARM_PULSE_S, pulse_us)):
        points.extend([f"{_us(start)} 0", f"{_us(start + 0.1e-6)} 2.5",
                       f"{_us(start + hold)} 2.5", f"{_us(start + hold + 0.1e-6)} 0"])
    points.append(f"{_us(RESTART_STOP_S)} 0")
    oc = "PWL(" + " ".join(points) + ")"
    return (
        "* Restart-sequencing sub-circuit check for the PROT-02 latch (NOT hardware).\n"
        "* Armed -> CT pulse latches -> 20 us Vddp power cycle resets both latches\n"
        "* and holds the gate low -> V(ss) restarts from 0 at 0.5 mV/us (5 uA into\n"
        "* 10 nF) -> a pulse during the ramp must NOT latch -> after V(ss) > 4.8 V\n"
        "* the arming latch closes and a later pulse MUST latch.\n"
        "* Logic only: no power stage, no controller OC, no gate driver.\n"
        f"Vddp vddp 0 {vddp}\n"
        f"Vss ss 0 {ss}\n"
        f"Voc oc 0 {oc}\n"
        "Vdrv drv 0 10\n"
        "Rdrv drv g 3.2\n"
        "Cg g 0 10n\n"
        "Buvlo uvlo 0 V=if(V(vddp)<8,1,0)\n"
        f"{latch_terms(reset_on_uvlo=True)}"
        "Cprot prot 0 1n IC=0\n"
        "Rprot prot 0 1G\n"
        f"Bprot prot 0 I=if(V(uvlo)>.5,V(prot)*(1n/{TAU_PROT}),"
        f"if(V(arm)>.5,if(V(oc)>1.8,-(1-V(prot))*(1n/{TAU_PROT}),0),0))\n"
        "Binhib inhib 0 V=if(V(uvlo)>.5,1,if(V(prot)>.5,1,0))\n"
        "Sg g 0 inhib 0 PROT_KILL\n"
        f".model PROT_KILL SW(Ron={CLAMP_OHM} Roff=1G Vt=.5)\n"
        # 10 ns, not 100 ns: the latch branches are explicit 100 nF/100 ns
        # integrators (tau = TAU_PROT); one step per tau diverges to 1e90.
        f".tran 0 {_us(RESTART_STOP_S)} 0 10n\n"
        ".save V(vddp) V(ss) V(uvlo) V(arm) V(prot) V(inhib) V(g) V(oc)\n"
        ".meas tran ARM_BEFORE AVG V(arm) FROM=60u TO=99u\n"
        ".meas tran PROT_LATCHED AVG V(prot) FROM=70u TO=99u\n"
        ".meas tran G_LATCHED AVG V(g) FROM=70u TO=99u\n"
        ".meas tran PROT_CLEARED FIND V(prot) AT=119.9u\n"
        ".meas tran ARM_CLEARED FIND V(arm) AT=119.9u\n"
        ".meas tran PROT_RESTART_MAX MAX V(prot) FROM=2000.2u TO=2100u\n"
        ".meas tran G_RESTART AVG V(g) FROM=130u TO=9700u\n"
        ".meas tran ARM_REARM_MAX MAX V(arm) FROM=9730u TO=10290u\n"
        ".meas tran PROT_REARM_MAX MAX V(prot) FROM=10310u TO=10590u\n"
        ".meas tran G_REARM_MIN MIN V(g) FROM=10310u TO=10590u\n"
        ".end\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    parents = {key: path for key, path in PARENTS.items() if any(
        spec(case)["parent"] == key for case in CANDIDATES)}
    missing = [path for path in parents.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"missing parent deck: {missing[0]}")
    texts = {key: path.read_text(encoding="utf-8") for key, path in parents.items()}
    outputs = [(destination(case), build(texts[str(spec(case)["parent"])], case))
               for case in CANDIDATES]
    outputs.append((uvlo_destination(), uvlo_deck()))
    outputs.append((restart_destination(), restart_deck()))
    for path, text in outputs:
        if args.write:
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != text:
            raise SystemExit(f"stale protection deck: {path}; rerun with --write")
        print(path.name, "UNRUN protection candidate; not hardware evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
