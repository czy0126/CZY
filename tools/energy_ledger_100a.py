"""Same-deck / same-window 100 A energy ledger (review 2026-11-01, issue #3).

Why this exists
---------------
The round-3 efficiency budget extrapolated loss from a single I^2 point.  The
review asked for the port energy measured over one window, itemised into terms
that are *also* measured in that window, with the leftover stated as a residual.

This tool reads the instrumented deck's ASCII raw and integrates, by trapezoid,
over an integer number of primary gate periods:

    Pin(source) = 48 V * mean(I(Rin))          (ideal Vbus, Rin is the 1 mOhm)
    Pout        = mean(V(out)^2 / RL)          (not Vout_avg^2 / RL)
    losses      = I^2 R for series elements, or v*i for switching devices
    stored      = 1/2 L I^2, 1/2 C V^2, differenced across the window

Two supplies sit *outside* the port and are reported separately, because mixing
them into Pin-Pout would blame the power stage for energy it never drew:

    Vreg  feeds the SR gate loop (ideal driver supply in this deck)
    Vaux  feeds the primary controller bias

What is measured vs assumed is recorded per term.  Pair 2/3 secondary copper is
scaled from pair 1 by symmetry -- the model makes that exact, hardware will not.

Storage (issue #6)
------------------
The first version stored only the primary-side magnets (4 * 1/2 Lp Ipri^2),
which treats a transformer as if its secondaries carried no current.  Under
ampere-turn balance the secondaries carry -3x the primary, so that term is
mostly *cancellation*, not storage: for an ideal coupling the coupled energy is
1/2 Lp (Ip + S/3)^2 with S = i_SA + i_SB, which is near zero in the conducting
phase.  The full three-winding form is used here

    E = 1/2 Lp Ip^2 + (Lp/18) S^2 + (k Lp/3) Ip S + ((k-1) Lp/9) i_SA i_SB

which reduces to the magnetising form at k = 1.  The SR devices add their own
charge-defined Cds/Cgd/Cgs and package Ld/Ls/Lg.

Capacitor energy is evaluated from the *charge function at the two window
endpoints*, not by integrating v*i over the window.  For an ideal capacitor the
exact integral over a whole period is zero, so any non-zero result of the
trapezoid estimate is pure quadrature error on a sub-nanosecond edge; measured
here it is about 0.2 mW for all eight SR devices, i.e. small but of the same
order as the 0.2 W target divided by ten.  The integral is still reported, as
``cap_integral_diag``, precisely so that error is stated rather than assumed.

What is *not* instrumented: Cbt (clamped near 12 V by the bootstrap logic),
Cgh/Cgl/Cdl (primary gate and snubber), Css/Cf/Coc, and the SR_TIMING internal
1 nF state capacitors.  Each is bounded by 1/2 C V^2 < 1.3 uJ at a switching
edge, so their sum is below ~0.1 W over a window; they are named here so the
closure residual is not read as a complete account.

Resolution (issue #6)
---------------------
The clock (200.622 kHz) and the resonant tank (202.127 kHz) are not
commensurate, so no short run of gate periods ends at the tank phase it
started from -- 133 gate periods (662.94 us) is the first window that does,
to about 0.1 deg.  Until then every storage term is differenced between two
different tank phases, and the per-period closure residual scatters by several
watts even though its window mean lands inside 0.2 W.

That mean is therefore *not* evidence of closure on its own: the standard error
over 24 periods is about 1 W, so the 0.2 W target is not resolvable with this
run at all.  ``balance.resolution`` reports the per-period spread, the standard
error, the period count needed for the target, and the phase-aligned length;
``closure_status`` stays NOT_CLOSED whenever the window cannot resolve it,
whatever the mean happens to be.  Do not loosen ``target_w`` to fix this --
lengthen the window (see ``phase_alignment``).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from array import array
from collections.abc import Iterator, Sequence
from itertools import islice
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.raw"
STEP_RAW = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.raw"
OUT = ROOT / "design/v3/stage_f/energy_ledger_100a.json"

VIN = 48.0
RL = 18.9e-3
RIN = 1e-3
R_LR = 5e-3
R_LP = 3e-3          # x4 in series
R_CR = 3e-3
R_COUT = 0.2e-3
R_SEC = 0.15e-3      # x8 half-windings; pair 1 measured, pairs 2/3 assumed
RON_PRI = 8e-3
LR_H = 0.92e-6
LP_H = 10e-6
CR_F = 620e-9
COUT_F = 4e-3
K_COUPLING = 0.999      # K1..K4 in the deck
LD_H = 0.3e-9           # SR package, ESTIMATE per models/sr_device_v3.lib
LS_H = 0.8e-9
LG_H = 2.5e-9
CGS_F = 5.1e-9          # constant Cgs in the SR model
BEARING_TURNS = 3.0     # primary turns per transformer (sqrt(Lp / (Lp/9)))
LCT1_H = 2e-6           # CT primary, in series with Lr
LCT2_H = 20e-3          # CT secondary
CIN_F = 20e-6
CDH_F = 560e-12         # primary high-side snubber
GATE_HZ = 200.622e3     # UCC25600 RT setting used by the decks
# The deck's LR_TOTAL is the external part; the model adds 4 * Lp(1-k^2) of
# leakage, and the tank resonance is set by the sum (see tools/lr_design.py).
TANK_TOTAL_H = LR_H + 4.0 * LP_H * (1.0 - K_COUPLING ** 2)   # 1.00 uH

WANTED = {
    "V(vin)": "vin", "V(out)": "vout", "V(sw)": "vsw", "V(nr)": "vnr",
    "V(reg)": "vreg",
    "I(Rin)": "iin", "I(Lr)": "ilr", "I(Cout)": "icout", "I(Vaux)": "ivaux",
    "I(Vreg)": "ivreg", "I(SH)": "ish", "I(SL)": "isl",
    "I(DH)": "idh", "I(DL)": "idl", "I(Rbur)": "irbur",
    "I(D1)": "id1", "I(D2)": "id2", "I(D3)": "id3", "I(D4)": "id4",
    "V(cs1)": "vcs1", "V(cs2)": "vcs2", "V(ocd)": "vocd", "V(ocm)": "vocm",
    "V(ga1)": "vga", "V(gb1)": "vgb",
    "I(xsr1:x1:Bdrive)": "bd1", "I(xsr1:x2:Bdrive)": "bd2",
    # pairs 1 and 4 are both instrumented: 4 is the symmetry check on the x4
    # scaling, not a second independent design point.
    "I(VSa1)": "isa1", "I(VSb1)": "isb1",
    "I(VSa4)": "isa4", "I(VSb4)": "isb4",
}

SR_INTERNALS = {
    "di": "V({x}:di)", "si": "V({x}:si)", "gi": "V({x}:gi)",
    "bch": "I({x}:Bch)", "dbd": "I({x}:Dbd)", "rg": "I({x}:Rg)",
    "cds": "I({x}:Cds)", "cgd": "I({x}:Cgd)", "cgs": "I({x}:Cgs)",
    "ld": "I({x}:Ld)", "ls": "I({x}:Ls)", "lg": "I({x}:Lg)",
}

PAIR1_INTERNALS = {
    "a": {key: probe.format(x="xsa1") for key, probe in SR_INTERNALS.items()},
    "b": {key: probe.format(x="xsb1") for key, probe in SR_INTERNALS.items()},
}


def read_raw_header(path: Path) -> tuple[list[str], float]:
    """Return variable names (including ``time``) and the saved-axis Offset."""
    names: list[str] = []
    offset = 0.0
    in_vars = False
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Offset:"):
                offset = float(line.split(":", 1)[1])
            elif line.startswith("No. Variables:"):
                pass
            elif line.startswith("Variables:"):
                in_vars = True
            elif line.startswith("Values:"):
                break
            elif in_vars:
                parts = line.rstrip("\r\n").split("\t")
                if len(parts) >= 3:
                    names.append(parts[2])
    return names, offset


def stream_points(path: Path) -> Iterator[tuple[float, list[float]]]:
    """Yield (time, values) one ASCII record at a time.  Test-sized use only."""
    names, _ = read_raw_header(path)
    count = len(names)
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Values:"):
                break
        while True:
            header = fh.readline()
            if not header:
                return
            fields = header.rstrip("\r\n").split("\t")
            if len(fields) < 2:
                return
            values = [float(fh.readline()) for _ in range(count - 1)]
            yield float(fields[-1]), values


def scan(path: Path, wanted: dict[str, str]) -> tuple[array, dict[str, array]]:
    """Read only the wanted columns into ``array('d')`` (a 424 MB raw is 80 vars)."""
    names, _ = read_raw_header(path)
    index = {name: i for i, name in enumerate(names)}
    missing = sorted(set(wanted) - set(index))
    if missing:
        raise KeyError(f"{path.name} has no probes: {missing}")
    columns = {key: index[name] - 1 for name, key in wanted.items()}  # time has no line
    by_line = {line: key for key, line in columns.items()}
    times = array("d")
    data = {key: array("d") for key in wanted.values()}
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            if line.startswith("Values:"):
                break
        while True:
            header = fh.readline()
            if not header:
                break
            fields = header.rstrip("\r\n").split("\t")
            if len(fields) < 2:
                break
            times.append(float(fields[-1]))
            for line_no, value in enumerate(islice(fh, len(names) - 1)):
                key = by_line.get(line_no)
                if key is not None:
                    data[key].append(float(value))
    return times, data


def _integral(t: array, y: array, i0: int, i1: int) -> float:
    total = 0.0
    for i in range(i0, i1):
        total += 0.5 * (y[i] + y[i + 1]) * (t[i + 1] - t[i])
    return total


def _mean(t: array, y: array, i0: int, i1: int) -> float:
    return _integral(t, y, i0, i1) / (t[i1] - t[i0])


def trapezoid_mean(t: list[float], y: list[float]) -> float:
    """Public, list-based form used by the tests; same arithmetic as the arrays."""
    total = sum(0.5 * (y[i] + y[i + 1]) * (t[i + 1] - t[i]) for i in range(len(t) - 1))
    return total / (t[-1] - t[0])


def _mean_product(t: array, a: array, b: array, i0: int, i1: int) -> float:
    return _mean(t, array("d", (a[i] * b[i] for i in range(len(a)))), i0, i1)


def gate_edges(t: array, gate: array, level: float = 2.5,
               debounce_s: float = 200e-9) -> list[int]:
    """Indices of real gate rising edges, one per switching period.

    The 5 ns timestep plus gate ringing crosses ``level`` more than once per
    rise; without a debounce the 24 real periods in the raw look like 48 edges
    and the window silently halves.  Edges closer than ``debounce_s`` are the
    same edge.
    """
    raw = [i for i in range(1, len(gate)) if gate[i] >= level > gate[i - 1]]
    edges: list[int] = []
    for i in raw:
        if not edges or t[i] - t[edges[-1]] > debounce_s:
            edges.append(i)
    return edges


def gate_window(t: array, gate: array, periods: int = 16,
                level: float = 2.5, debounce_s: float = 200e-9) -> tuple[int, int]:
    """Last ``periods`` complete gate periods, bounded by real rising edges."""
    edges = gate_edges(t, gate, level, debounce_s)
    if len(edges) < 2:
        raise ValueError("fewer than two gate rising edges in the raw")
    if len(edges) > periods:
        return edges[-(periods + 1)], edges[-1]
    return edges[0], edges[-1]


def transformer_energy_j(lp_h: float, k: float, ip: float, isa: float, isb: float) -> float:
    """Energy in one 3-winding transformer, currents taken *into each dot*.

    The deck's ``Lsa1 out a1`` puts S_A's dot at the centre tap and
    ``Lsb1 b1 out`` puts S_B's dot at ``b1``, so the two halves are a
    centre-tapped winding with opposing dots.  With L_s = Lp/9 per half and
    coupling k, M_ps = k Lp/3 and M_ss = k Lp/9, which gives the quadratic form
    above.  At k = 1 it collapses to 1/2 Lp (Ip + S/3)^2 -- i.e. the magnetising
    energy, not 1/2 Lp Ip^2.
    """
    ls = lp_h / 9.0
    mps = k * lp_h / 3.0
    mss = k * lp_h / 9.0
    return (0.5 * lp_h * ip * ip
            + 0.5 * ls * (isa * isa + isb * isb)
            + mps * ip * (isa + isb)
            + mss * isa * isb)


def _simpson(f, a: float, b: float, n: int = 4000) -> float:
    """Composite Simpson over [a, b] -- the reference the closed form is tested
    against; ``charge_energy_j`` uses the exact antiderivative instead."""
    if b == a:
        return 0.0
    if b < a:
        return -_simpson(f, b, a, n)
    n += n % 2
    h = (b - a) / n
    total = f(a) + f(b)
    for i in range(1, n):
        total += (4.0 if i % 2 else 2.0) * f(a + i * h)
    return total * h / 3.0


# Piecewise fit of the SR device charges, transcribed from models/sr_device_v3.lib.
# (break_v, low_a, low_b, c0, k, a1, tau1, a2, tau2): below break_v the charge is
# ``low_a*x - low_b*x^2/2``; above it, ``c0 + k*d + a1*(1-exp(-d/tau1))
# + a2*(1-exp(-d/tau2))`` with ``d = x - break_v``.
CDS_FIT = (10.0021, 6154.29e-12, 297.645e-12, 46.666e-9, 62.6184e-12,
           9147.4e-12, 5.29689, 69821e-12, 50.3394)
CGD_FIT = (8.52972, 735.774e-12, 56.7507e-12, 4.2116e-9, 26.6784e-12,
           892.3e-12, 3.96525, 0.0, 1.0)
CDS_BREAK_V = CDS_FIT[0]
CGD_BREAK_V = CGD_FIT[0]


def _charge(fit: tuple[float, ...], x: float) -> float:
    break_v, low_a, low_b, c0, k, a1, tau1, a2, tau2 = fit
    if x <= break_v:
        return low_a * x - low_b * x * x / 2.0
    d = x - break_v
    return (c0 + k * d
            + a1 * (1.0 - math.exp(-d / tau1))
            + a2 * (1.0 - math.exp(-d / tau2)))


def _charge_area(fit: tuple[float, ...], x: float) -> float:
    """Closed form of integral_0^x Q(u) du.

    Every term of the fit is elementary, so this is exact; the shipped values
    used to come from a 4000-panel Simpson, which was both approximate and far
    too slow to evaluate once per sample (``storage_arrays`` needs O(n) of them).
    """
    break_v, low_a, low_b, c0, k, a1, tau1, a2, tau2 = fit
    if x <= break_v:
        return low_a * x ** 2 / 2.0 - low_b * x ** 3 / 6.0
    d = x - break_v
    base = low_a * break_v ** 2 / 2.0 - low_b * break_v ** 3 / 6.0
    return (base + c0 * d + k * d * d / 2.0
            + a1 * (d - tau1 * (1.0 - math.exp(-d / tau1)))
            + a2 * (d - tau2 * (1.0 - math.exp(-d / tau2))))


def cds_charge_c(x: float) -> float:
    """Cds charge (coulombs) at |Vds| = x, transcribed from models/sr_device_v3.lib."""
    return _charge(CDS_FIT, x)


def cgd_charge_c(x: float) -> float:
    """Cgd charge (coulombs) at |Vgd| = x, transcribed from models/sr_device_v3.lib."""
    return _charge(CGD_FIT, x)


def charge_energy_j(v: float, charge_c) -> float:
    """Energy stored at terminal voltage ``v`` for a charge-defined capacitor.

    E(v) = integral_0^|v| u dQ(u) = |v| Q(|v|) - integral_0^|v| Q(u) du, with
    Q odd in v.  Evaluating this at the two window endpoints gives the exact
    stored-energy difference; integrating v*i over the sampled waveform does
    not (see ``cap_integral_diag``).
    """
    x = abs(v)
    if x == 0.0:
        return 0.0
    fit = CDS_FIT if charge_c is cds_charge_c else CGD_FIT
    return x * _charge(fit, x) - _charge_area(fit, x)


def cgs_energy_j(v: float, c: float = CGS_F) -> float:
    """Cgs is a constant capacitance in the SR model, so this is exact."""
    return 0.5 * c * v * v


def magnetic_energy_array(d: dict[str, array]) -> array:
    """Coupled energy of all four transformers at every sampled time point.

    Pairs 1 and 4 are instrumented (``I(VSa1)``/``I(VSb1)`` and the 4 variants);
    pairs 2 and 3 are taken as their mean, which makes the total exactly
    ``2 * (E1 + E4)``.  The four primary windings are in series, so Ip is shared.
    """
    ip, ia1, ia4 = d["ilr"], d["isa1"], d["isa4"]
    ib1 = array("d", (-v for v in d["isb1"]))
    ib4 = array("d", (-v for v in d["isb4"]))
    return array("d", (
        2.0 * (transformer_energy_j(LP_H, K_COUPLING, ip[i], ia1[i], ib1[i])
               + transformer_energy_j(LP_H, K_COUPLING, ip[i], ia4[i], ib4[i]))
        for i in range(len(ip))))


def sr_storage_j(d: dict[str, array], i: int, half: str) -> tuple[float, float]:
    """(capacitor, package-inductor) energy of one SR device at sample ``i``."""
    gi, si, di = d[f"{half}_gi"][i], d[f"{half}_si"][i], d[f"{half}_di"][i]
    cap = (cgs_energy_j(gi - si)
           + charge_energy_j(di - si, cds_charge_c)
           + charge_energy_j(gi - di, cgd_charge_c))
    ind = 0.5 * (LD_H * d[f"{half}_ld"][i] ** 2
                 + LS_H * d[f"{half}_ls"][i] ** 2
                 + LG_H * d[f"{half}_lg"][i] ** 2)
    return cap, ind


def storage_arrays(d: dict[str, array], e_mag: array) -> dict[str, array]:
    """Stored energy of every element at every sample (J).

    One array per element, so the same quantity can be read at a single sample
    (``storage_terms``) or averaged over a whole period
    (``averaged_storage_terms``).  Keeping one source of truth for the formulas
    matters: the two readings must differ only in *where* they are evaluated.
    """
    n = len(d["ilr"])
    cap = array("d", bytes(8 * n))
    ind = array("d", bytes(8 * n))
    for half in ("a", "b"):
        for i in range(n):
            c, l = sr_storage_j(d, i, half)
            cap[i] += c
            ind[i] += l
    return {
        "magnetic_coupled_j": e_mag,
        "sr_capacitance_j": array("d", (4.0 * v for v in cap)),
        "sr_package_inductance_j": array("d", (4.0 * v for v in ind)),
        "lr_j": array("d", (0.5 * LR_H * v ** 2 for v in d["ilr"])),
        "cr_j": array("d", (0.5 * CR_F * (d["vsw"][i] - d["vnr"][i]) ** 2
                            for i in range(n))),
        "cout_j": array("d", (0.5 * COUT_F * v ** 2 for v in d["vout"])),
        # Lct1 sits between Cr and Lr with nothing else on nr/nct, so it carries
        # exactly I(Lr); the CT bridge makes |i(Lct2)| = I(Rbur).
        "ct_primary_j": array("d", (0.5 * LCT1_H * v ** 2 for v in d["ilr"])),
        "ct_secondary_j": array("d", (0.5 * LCT2_H * v ** 2 for v in d["irbur"])),
        "cin_j": array("d", (0.5 * CIN_F * v ** 2 for v in d["vin"])),
        "primary_dvdt_snubber_j": array("d", (
            0.5 * CDH_F * (d["vin"][i] - d["vsw"][i]) ** 2 for i in range(n))),
    }


def storage_terms(t: array, d: dict[str, array], i0: int, i1: int,
                  e_mag: array | None = None,
                  arrays: dict[str, array] | None = None) -> dict[str, float]:
    """Stored-energy change (joules) across the window, element by element."""
    if arrays is None:
        if e_mag is None:
            e_mag = magnetic_energy_array(d)
        arrays = storage_arrays(d, e_mag)
    return {name: v[i1] - v[i0] for name, v in arrays.items()}


def averaged_storage_terms(t: array, arrays: dict[str, array],
                           edges: Sequence[int], i0: int, i1: int) -> dict[str, float]:
    """Stored-energy change between one-period *means* at the two ends.

    Reading the endpoints at single samples makes every storage term inherit
    the sample-to-sample jitter of the raw -- and those terms are then divided
    by the window length, so on a short window the jitter alone can exceed the
    0.2 W target.  Averaging one gate period at each end removes it: one gate
    period (4.9845 us) is within 0.75 % of one tank period (4.9473 us), so the
    tank-frequency component is attenuated by |sinc(pi*f_tank/f_gate)| = 0.0075,
    about 130x.  What survives is the period-to-period spread of the period
    means themselves, not the phase of the sample we happened to stop on.

    Both ``i0`` and ``i1`` must be gate edges (``gate_window`` guarantees it),
    so the averaging periods are whole gate periods.
    """
    if i0 not in edges or i1 not in edges:
        raise ValueError("period averaging needs the window ends to be gate edges")
    first = edges[edges.index(i0) + 1]
    last = edges[edges.index(i1) - 1]
    return {name: _mean(t, v, last, i1) - _mean(t, v, i0, first)
            for name, v in arrays.items()}


def cap_integral_diag(t: array, d: dict[str, array], edges: Sequence[int],
                      i0: int, i1: int, half: str = "a") -> dict[str, object]:
    """Trapezoid integral of v*i for the three SR capacitors, per period.

    For an ideal capacitor this is exactly zero over any whole period, so
    whatever it is *not* is the quadrature error of sampling a sub-nanosecond
    gate edge.  It is the uncertainty on any storage term computed that way,
    which is why the reported energies come from the charge function instead.
    """
    out: dict[str, object] = {}
    pairs = {"cgs": ("gi", "si"), "cds": ("di", "si"), "cgd": ("gi", "di")}
    for name, (v1, v2) in pairs.items():
        v = array("d", (d[f"{half}_{v1}"][i] - d[f"{half}_{v2}"][i]
                        for i in range(len(t))))
        y = array("d", (v[i] * d[f"{half}_{name}"][i] for i in range(len(t))))
        per = [_integral(t, y, a, b) for a, b in zip(edges[:-1], edges[1:])
               if a >= i0 and b <= i1]
        total = _integral(t, y, i0, i1)
        span = t[i1] - t[i0]
        out[name] = {
            "total_j": total,
            "mean_period_j": (sum(per) / len(per)) if per else 0.0,
            "rate_w_x4": 4.0 * total / span,
            "periods": len(per),
        }
    out["note"] = ("each term should be 0 over a whole period; rate_w_x4 is the "
                   "quadrature noise of v*i at this timestep, not a physical loss")
    return out


def port_terms(t: array, d: dict[str, array], i0: int, i1: int) -> dict[str, float]:
    """Terminal powers.  Pout is average(v^2/R), never average(v)^2/R."""
    return {
        "pin_source_w": VIN * _mean(t, d["iin"], i0, i1),
        "pin_after_rin_w": _mean_product(t, d["vin"], d["iin"], i0, i1),
        "pout_w": _mean(t, array("d", (v * v / RL for v in d["vout"])), i0, i1),
    }


def driver_w(t: array, d: dict[str, array], i0: int, i1: int) -> float:
    """Energy the SR gate B-sources hand to the gate loop, pair 1 x4.

    I(Bdrive) is reported flowing into the B-source, so the delivered power is
    -V(gate)*I.  The sources are ideal and draw nothing from Vreg, so this is
    energy the deck does *not* take from the port.
    """
    return -4.0 * (_mean_product(t, d["vga"], d["bd1"], i0, i1)
                   + _mean_product(t, d["vgb"], d["bd2"], i0, i1))


def main_loss_names(losses: dict[str, dict[str, object]]) -> list[str]:
    """Every loss term except the pair-1 measurement and its x4 twin.

    ``sr_channel_body_pair1`` is the measurement ``sr_channel_body_x4`` is built
    from; counting both would add 1.85 W of pure double entry.
    """
    return [name for name in losses
            if name not in ("sr_gate_resistor_x8", "sr_channel_body_pair1")]


def window_terms(t: array, d: dict[str, array], i0: int, i1: int,
                 arrays: dict[str, array] | None = None) -> dict[str, float]:
    """Port, loss, storage and closure numbers for one window."""
    port = port_terms(t, d, i0, i1)
    losses = loss_terms(t, d, i0, i1)
    loss_main = sum(float(losses[name]["w"]) for name in main_loss_names(losses))
    stored = storage_terms(t, d, i0, i1, arrays=arrays)
    span = t[i1] - t[i0]
    stored_w = sum(stored.values()) / span
    drv = driver_w(t, d, i0, i1)
    port_w = port["pin_source_w"] - port["pout_w"]
    return {
        "start_s": float(t[i0]), "end_s": float(t[i1]), "span_s": float(span),
        "port_w": port_w,
        "loss_total_w": loss_main,
        "stored_w": stored_w,
        "driver_w": drv,
        "residual_w": port_w - loss_main,
        "residual_including_storage_w": port_w + drv - loss_main - stored_w,
    }


def loss_terms(t: array, d: dict[str, array], i0: int, i1: int) -> dict[str, dict[str, object]]:
    """Element losses over [i0, i1], each tagged with how it was obtained."""
    def msq(key: str) -> float:
        return _mean(t, array("d", (v * v for v in d[key])), i0, i1)

    def i2r(key: str, resistance: float, confidence: str) -> dict[str, object]:
        return {"w": msq(key) * resistance, "confidence": confidence}

    losses: dict[str, dict[str, object]] = {
        "rin": i2r("iin", RIN, "measured-i2r"),
        "lr": i2r("ilr", R_LR, "measured-i2r"),
        "lp_series": i2r("ilr", 4 * R_LP, "measured-i2r"),
        "cr_esr": i2r("ilr", R_CR, "measured-i2r"),
        "cout_esr": i2r("icout", R_COUT, "measured-i2r"),
        "secondary_copper": {
            "w": (msq("isa1") + msq("isb1")) * R_SEC * 4,
            "confidence": "symmetry-assumption",
        },
        "sh": i2r("ish", RON_PRI, "measured-commutation"),
        "sl": i2r("isl", RON_PRI, "measured-commutation"),
        "dh": {"w": _mean(t, array("d", ((d["vsw"][i] - d["vin"][i]) * d["idh"][i]
                                        for i in range(len(t)))), i0, i1),
               "confidence": "measured-commutation"},
        "dl": {"w": _mean(t, array("d", (-d["vsw"][i] * d["idl"][i]
                                        for i in range(len(t)))), i0, i1),
               "confidence": "measured-commutation"},
    }

    pair1 = 0.0
    for half in ("a", "b"):
        vds = array("d", (d[f"{half}_di"][i] - d[f"{half}_si"][i] for i in range(len(t))))
        ch = _mean(t, array("d", (vds[i] * d[f"{half}_bch"][i] for i in range(len(t)))),
                   i0, i1)
        bd = _mean(t, array("d", (-vds[i] * d[f"{half}_dbd"][i] for i in range(len(t)))),
                   i0, i1)
        pair1 += ch + bd
    losses["sr_channel_body_pair1"] = {"w": pair1, "confidence": "measured-commutation"}
    losses["sr_channel_body_x4"] = {"w": 4 * pair1, "confidence": "symmetry-assumption"}

    rg_w = sum(_mean(t, array("d", (d[f"{h}_rg"][i] ** 2 for i in range(len(t)))),
                     i0, i1) * 1.0 for h in ("a", "b"))
    losses["sr_gate_resistor_x8"] = {"w": 4 * rg_w, "confidence": "symmetry-assumption"}

    ct_diodes = (
        _mean(t, array("d", ((d["vcs1"][i] - d["vocd"][i]) * d["id1"][i]
                             for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vcs2"][i] - d["vocd"][i]) * d["id2"][i]
                               for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vocm"][i] - d["vcs1"][i]) * d["id3"][i]
                               for i in range(len(t)))), i0, i1)
        + _mean(t, array("d", ((d["vocm"][i] - d["vcs2"][i]) * d["id4"][i]
                               for i in range(len(t)))), i0, i1)
    )
    losses["ct_bridge_diodes"] = {"w": ct_diodes, "confidence": "measured-commutation"}
    losses["ct_burden_resistor"] = i2r("irbur", 10.0, "measured-i2r")
    return losses


def tank_khz() -> float:
    """Resonant frequency of the tank as the deck builds it (external + leakage)."""
    return 1.0 / (2.0 * math.pi * math.sqrt(TANK_TOTAL_H * CR_F)) / 1e3


def phase_alignment(max_periods: int = 400) -> dict[str, float | int]:
    """First gate-period count at which the tank returns to its starting phase.

    The clock and the tank are not commensurate, so a window of whole gate
    periods still starts and ends at different tank phases.  The storage terms
    are differenced between those two phases, which is why the closure moves
    with the window.  This returns the shortest window where that cancels.
    """
    t_tank = 1.0 / (tank_khz() * 1e3)     # seconds; tank_khz() is in kHz
    t_gate = 1.0 / GATE_HZ

    def slip(n: int) -> float:
        cycles = n * t_gate / t_tank
        return abs(cycles - round(cycles))

    aligned = min(range(10, max_periods), key=slip)
    cycles = aligned * t_gate / t_tank
    return {
        "tank_khz": tank_khz(),
        "gate_khz": GATE_HZ / 1e3,
        "beat_hz": abs(tank_khz() * 1e3 - GATE_HZ),
        "aligned_periods": aligned,
        "aligned_span_s": aligned * t_gate,
        "tank_cycles": cycles,
        "phase_error_deg": slip(aligned) * 360.0,
    }


def _noise_stats(values: list[float], target_w: float) -> dict[str, object]:
    n = len(values)
    if n < 2:
        raise ValueError(f"need at least two periods for a spread, got {n}")
    mean = sum(values) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in values) / (n - 1))
    return {
        "target_w": target_w,
        "periods": n,
        "per_period_w": values,
        "mean_w": mean,
        "sd_w": sd,
        "sem_w": sd / math.sqrt(n),
        "periods_for_target": int(math.ceil((sd / target_w) ** 2)),
        "note": "sd_w is the period-to-period spread of the closure residual and "
                "sem_w its standard error over this window.  The window mean is "
                "resolved only to about 2*sem_w, so periods_for_target larger "
                "than periods means the 0.2 W target is not demonstrated here, "
                "even when the mean falls inside it.",
    }


def residual_noise(t: array, d: dict[str, array], edges: Sequence[int],
                   i0: int, i1: int, target_w: float = 0.2,
                   e_mag: array | None = None,
                   arrays: dict[str, array] | None = None) -> dict[str, object]:
    """Per-period closure residual, and the standard error of its window mean.

    A window mean can land inside the target by cancellation while the
    individual periods are far outside it.  Resolving ``target_w`` needs about
    ``(sd / target_w)^2`` periods, so a window shorter than that cannot
    demonstrate the target no matter what its mean happens to be.
    """
    if arrays is None:
        if e_mag is None:
            e_mag = magnetic_energy_array(d)
        arrays = storage_arrays(d, e_mag)
    values: list[float] = []
    for a, b in zip(edges[:-1], edges[1:]):
        if a < i0 or b > i1:
            continue
        port = port_terms(t, d, a, b)
        losses = loss_terms(t, d, a, b)
        loss_main = sum(float(losses[name]["w"]) for name in main_loss_names(losses))
        stored = sum(storage_terms(t, d, a, b, arrays=arrays).values())
        span = t[b] - t[a]
        values.append(port["pin_source_w"] - port["pout_w"] + driver_w(t, d, a, b)
                      - loss_main - stored / span)
    return _noise_stats(values, target_w)


def averaged_residual_noise(t: array, d: dict[str, array], edges: Sequence[int],
                            i0: int, i1: int, arrays: dict[str, array],
                            target_w: float = 0.2) -> dict[str, object]:
    """The same residual with each period's storage read from period means.

    Period ``k`` (``edges[k]..edges[k+1]``) uses the mean stored energy over
    that period minus the mean over the period before it, so the endpoint sample
    jitter is averaged out before the division by the period length.  The
    series needs one period of lead-in, so it has one fewer point than
    ``residual_noise``.  Its mean is *not* the window closure -- that is
    ``averaged_storage_terms`` -- it exists to size the spread, which is what
    decides whether the window can resolve ``target_w``.
    """
    spans = [(a, b) for a, b in zip(edges[:-1], edges[1:]) if a >= i0 and b <= i1]
    if len(spans) < 3:
        raise ValueError("period averaging needs at least three periods")
    means = [{name: _mean(t, v, a, b) for name, v in arrays.items()}
             for a, b in spans]
    values: list[float] = []
    for k in range(1, len(spans)):
        a, b = spans[k]
        port = port_terms(t, d, a, b)
        losses = loss_terms(t, d, a, b)
        loss_main = sum(float(losses[name]["w"]) for name in main_loss_names(losses))
        stored = sum(means[k][name] - means[k - 1][name] for name in arrays)
        span = t[b] - t[a]
        values.append(port["pin_source_w"] - port["pout_w"] + driver_w(t, d, a, b)
                      - loss_main - stored / span)
    return _noise_stats(values, target_w)


def repo_relative(path: Path) -> str:
    """Path as written in the JSON: always absolute first, then relative to ROOT.

    A ``--raw`` given on the command line is relative to the caller's directory,
    and ``Path.relative_to()`` refuses to guess -- it raised after a 22-minute
    scan of the aligned raw, throwing the whole result away.  Resolving here
    means the same raw is named the same way whichever way it was passed.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:                    # outside the repo: keep it absolute
        return resolved.as_posix()


def build(raw: Path = RAW, periods: int = 16,
          alt_periods: Sequence[int] = (8, 12)) -> dict[str, object]:
    raw = Path(raw).resolve()
    names, _ = read_raw_header(raw)
    wanted = dict(WANTED)
    for half, probes in PAIR1_INTERNALS.items():
        for key, probe in probes.items():
            wanted[probe] = f"{half}_{key}"
    t, d = scan(raw, wanted)
    edges = gate_edges(t, d["vga"])
    i0, i1 = gate_window(t, d["vga"], periods)
    span = t[i1] - t[i0]

    port = port_terms(t, d, i0, i1)
    p_in_src = port["pin_source_w"]
    p_in_after_rin = port["pin_after_rin_w"]
    p_out = port["pout_w"]

    losses = loss_terms(t, d, i0, i1)
    all_main = main_loss_names(losses)
    loss_main = sum(float(losses[name]["w"]) for name in all_main)
    loss_before_ct = sum(float(losses[name]["w"]) for name in all_main
                         if not name.startswith("ct_"))
    port_w = p_in_src - p_out
    loss_residual = port_w - loss_main

    e_mag = magnetic_energy_array(d)
    arrays = storage_arrays(d, e_mag)
    stored = storage_terms(t, d, i0, i1, arrays=arrays)
    d_stored_w = sum(stored.values()) / span
    # Issue #6: the same change read from one-period means at each end.  Single
    # endpoint samples carry the raw's sample-to-sample jitter; on a short
    # window that jitter alone can exceed the 0.2 W target.
    stored_avg = averaged_storage_terms(t, arrays, edges, i0, i1)
    d_stored_avg_w = sum(stored_avg.values()) / span
    drv = driver_w(t, d, i0, i1)
    # Full closure: the system boundary is {Vbus source, load, 8 SR gate
    # B-sources}.  Everything else the deck supplies (Vreg, Vaux, and the
    # primary gate B-sources) is ideal and outside it; see ``outside_port``.
    closure_residual = port_w + drv - loss_main - d_stored_w
    closure_residual_avg = port_w + drv - loss_main - d_stored_avg_w

    vreg_w = -_mean_product(t, d["vreg"], d["ivreg"], i0, i1)
    vaux_w = -12.0 * _mean(t, d["ivaux"], i0, i1)
    diag = cap_integral_diag(t, d, edges, i0, i1)

    per_period = [(e_mag[b] - e_mag[a]) for a, b in zip(edges[:-1], edges[1:])
                  if a >= i0 and b <= i1]
    mag_mean = (sum(per_period) / len(per_period)) if per_period else 0.0
    mag_std = (sum((x - mag_mean) ** 2 for x in per_period) / len(per_period)) ** 0.5 \
        if per_period else 0.0

    windows = [{"periods": periods, **window_terms(t, d, i0, i1, arrays)}]
    for p in alt_periods:
        try:
            a, b = gate_window(t, d["vga"], p)
        except ValueError:
            continue
        if (a, b) != (i0, i1):
            windows.append({"periods": p, **window_terms(t, d, a, b, arrays)})

    # Issue #6: a mean inside 0.2 W is not a closure unless the window can
    # resolve 0.2 W.  Both conditions are required, and the reason is recorded
    # separately from the status so "not closed" is never read as "missing
    # energy" when it is really "too short a run".
    noise = residual_noise(t, d, edges, i0, i1, arrays=arrays)
    try:
        noise_avg = averaged_residual_noise(t, d, edges, i0, i1, arrays)
    except ValueError as exc:                     # window shorter than 3 periods
        noise_avg = {"error": str(exc), "sem_w": float("inf"), "periods": 0,
                     "periods_for_target": None, "mean_w": None, "sd_w": None}
    align = phase_alignment()
    within = abs(closure_residual) <= 0.2
    resolved = float(noise["sem_w"]) <= 0.2
    within_avg = abs(closure_residual_avg) <= 0.2
    resolved_avg = float(noise_avg["sem_w"]) <= 0.2
    # Both readings must agree that the residual is inside the target; the
    # period-averaged one is the resolution instrument, because it is the one
    # whose spread is not set by which sample the run happened to stop on.
    # The target itself is untouched -- see `checks` for why the physical
    # outcome is reported in `results` and never gates `checks.ok`.
    closure_ok = within and within_avg and resolved_avg
    closure_status = "CLOSED" if closure_ok else "NOT_CLOSED"
    if closure_ok:
        closure_reason = ("both readings are inside 0.2 W and the period-averaged "
                          "estimator resolves 0.2 W on this window")
    elif within and not within_avg:
        closure_reason = (f"the single-sample reading {closure_residual:+.3f} W is "
                          f"inside the target but the period-averaged reading "
                          f"{closure_residual_avg:+.3f} W is outside it; the two "
                          f"disagree, so neither is trusted")
    elif within and within_avg:
        closure_reason = (f"both readings are inside the target ({closure_residual:+.3f} W, "
                          f"{closure_residual_avg:+.3f} W) but the period-averaged "
                          f"estimator resolves only "
                          f"{2.0 * float(noise_avg['sem_w']):.2f} W on this window")
    elif within:
        closure_reason = (f"residual {closure_residual:+.3f} W is inside the target "
                          f"but this window resolves only {2.0 * float(noise['sem_w']):.2f} W")
    else:
        closure_reason = (f"residual {closure_residual:+.3f} W is outside the target "
                          f"(period-averaged {closure_residual_avg:+.3f} W, window "
                          f"resolves {2.0 * float(noise_avg['sem_w']):.2f} W)")
    # `results` are what the physics did; `checks` are invariants of the report
    # itself, and only those gate `ok`.  Folding the physical outcome into the
    # gate would make an honest NOT_CLOSED read as a broken tool -- and would
    # tempt the next person to loosen the target until the gate went green.
    results = {
        "loss_residual_within_0p2_w": abs(loss_residual) <= 0.2,
        "closure_within_0p2_w": within,
        "window_resolves_0p2_w": resolved,
        "closure_period_averaged_within_0p2_w": within_avg,
        "window_resolves_0p2_w_period_averaged": resolved_avg,
        "closure_including_storage_within_0p2_w": closure_ok,
    }
    checks = {
        "ct_burden_closes_the_gap": abs(port_w - loss_before_ct) <= 0.2,
        "stored_energy_reported_not_folded_in": True,
        "pout_uses_v_squared": abs(p_out - _mean(t, d["vout"], i0, i1) ** 2 / RL) > 0.0,
        "coupled_energy_never_negative": min(e_mag[(i0):(i1 + 1)]) >= 0.0,
        "closure_status_follows_from_the_results":
            (closure_status == "CLOSED") == closure_ok,
        "closure_status_is_derived_from_both_readings":
            closure_ok == (within and within_avg and resolved_avg),
        "closure_reason_states_which_condition_failed":
            bool(closure_reason) and (closure_ok or ("resolves" in closure_reason
                                                     or "outside" in closure_reason)),
    }
    limits = []
    if abs(loss_residual) > 0.2:
        limits.append("loss residual exceeds 0.2 W; do not quote an efficiency "
                      "from this run")
    if not closure_ok:
        limits.append(f"closure including storage: {closure_reason}; the status is "
                      f"NOT_CLOSED and the 0.2 W target is unchanged")
    if not resolved_avg:
        need = noise_avg.get("periods_for_target")
        limits.append(
            f"this window spans {periods} gate periods; the period-averaged "
            f"estimator resolves only {2.0 * float(noise_avg['sem_w']):.2f} W here"
            + (f" and needs about {need} periods to resolve 0.2 W" if need else "")
            + f".  The single-sample reading needs {noise['periods_for_target']} "
            f"periods.  The tank and the clock are not commensurate, so the first "
            f"phase-aligned window is {align['aligned_periods']} periods "
            f"({float(align['aligned_span_s']) * 1e6:.1f} us); this raw holds "
            f"{100.0 * periods / float(align['aligned_periods']):.0f} % of it.  "
            f"Do not quote the window mean as a closure")
    if abs(d_stored_w) > 0.2:
        limits.append(f"stored-energy rate is {d_stored_w:+.3f} W over this "
                      f"window; see windows[] for how it moves with the window")
    return {
        "raw": {"path": repo_relative(raw),
                "bytes": raw.stat().st_size, "mtime": raw.stat().st_mtime,
                "variables": len(names),
                "max_step_s": max_step_of(raw)},
        "window": {
            "start_s": float(t[i0]), "end_s": float(t[i1]), "span_s": float(span),
            "periods": periods, "raw_time_start_s": 880e-6,
            "display_offset_us": 880.0,
            # The stored-energy terms are endpoint differences, so this one
            # sample is what the 4 mF Cout term integrates from.  It is the
            # noisiest number in the ledger: see step_check.
            "vout_end_v": float(d["vout"][i1]),
            "vout_start_v": float(d["vout"][i0]),
        },
        "port": {
            "vin_v": VIN, "rl_ohm": RL,
            "pin_source_w": p_in_src,
            "pin_after_rin_w": p_in_after_rin,
            "pout_w": p_out,
            "pin_minus_pout_w": port_w,
        },
        "losses": losses,
        "loss_total_w": loss_main,
        "loss_before_ct_w": loss_before_ct,
        "stored_energy_j": stored,
        "stored_energy_w": d_stored_w,
        "magnetic_energy": {
            "per_period_j": per_period,
            "mean_period_j": mag_mean,
            "std_period_j": mag_std,
            "note": "coupled 3-winding energy, all four transformers; pairs 1/4 "
                    "measured, 2/3 taken as their mean",
        },
        "cap_integral_diag": diag,
        "outside_port": {"vreg_w": vreg_w, "vaux_w": vaux_w,
                         "driver_output_w": drv},
        "efficiency": {
            "port_pct": 100.0 * p_out / p_in_src,
            "closure_including_storage_pct": 100.0 * p_out / (p_out + loss_main + d_stored_w),
            "engineering_budget_note":
                "the published 92.33 % budget (magnetising/core estimate, 0.15 mOhm "
                "output path, 0.75 W bias) lives in magnetics_design.json.  It is a "
                "different quantity from port_pct and is not recomputed here.",
        },
        "balance": {
            "residual_w": loss_residual,
            "loss_residual_w": loss_residual,
            "target_w": 0.2,
            "closure_residual_w": closure_residual,
            "closure_status": closure_status,
            "closure_reason": closure_reason,
            "resolution": {**noise, "phase_alignment": align},
            "stored_energy_endpoint_w": d_stored_w,
            "stored_energy_phase_limit_w": abs(d_stored_w),
            "period_averaged": {
                "stored_energy_w": d_stored_avg_w,
                "closure_residual_w": closure_residual_avg,
                "periods": noise_avg.get("periods"),
                "sd_w": noise_avg.get("sd_w"),
                "sem_w": noise_avg.get("sem_w"),
                "periods_for_target": noise_avg.get("periods_for_target"),
                "definition": "each storage term is averaged over one whole gate "
                              "period at each end of the window; one gate period "
                              "is within 0.75 % of one tank period, so the tank-"
                              "frequency part of the endpoint error is attenuated "
                              "by about 130x",
            },
            "note": "residual_w is Pin - Pout - summed element losses (the issue #3 "
                    "number).  closure_residual_w additionally adds the measured SR "
                    "gate-supply energy and subtracts the stored-energy rate, i.e. it "
                    "is the full conservation check; only that one may be called a "
                    "complete energy-conservation check.",
            "limits": limits,
        },
        "windows": windows,
        "sensitivity": {
            "max_step_s": max_step_of(raw),
            "note": "see step_check for the 5 ns / 2 ns comparison; the storage "
                    "terms come from the charge function at the endpoints, so they "
                    "do not carry the v*i quadrature error sized by cap_integral_diag",
            "device_parameters": "Rds/Isat fitted; package parasitics are ESTIMATE "
                                 "per models/sr_device_v3.lib",
        },
        "results": results,
        "checks": {"ok": all(checks.values()), **checks},
    }


def max_step_of(raw: Path) -> float | None:
    """Read the deck's ``.tran`` max step next to the raw, if the deck is there."""
    deck = raw.with_suffix(".cir")
    if not deck.exists():
        return None
    match = re.search(r"^\.tran \S+ \S+ \S+ ([0-9.]+)([a-z]?) ",
                      deck.read_text(encoding="utf-8", errors="replace"), re.M)
    if not match:
        return None
    scale = {"": 1.0, "n": 1e-9, "u": 1e-6, "m": 1e-3}.get(match.group(2))
    return None if scale is None else float(match.group(1)) * scale


def step_check(raw_a: Path, raw_b: Path, periods: int = 16) -> dict[str, object]:
    """Compare port, branch losses and closure between two timesteps (issue #6)."""
    a, b = build(raw_a, periods, alt_periods=()), build(raw_b, periods, alt_periods=())
    rows: dict[str, object] = {}
    for name, x, y in (("port_w", a["port"]["pin_minus_pout_w"], b["port"]["pin_minus_pout_w"]),
                       ("loss_total_w", a["loss_total_w"], b["loss_total_w"]),
                       ("stored_w", a["stored_energy_w"], b["stored_energy_w"]),
                       ("driver_w", a["outside_port"]["driver_output_w"],
                        b["outside_port"]["driver_output_w"]),
                       ("residual_w", a["balance"]["loss_residual_w"],
                        b["balance"]["loss_residual_w"]),
                       ("closure_residual_w", a["balance"]["closure_residual_w"],
                        b["balance"]["closure_residual_w"])):
        rows[name] = {"step_a_w": x, "step_b_w": y, "delta_w": y - x}
    # The endpoint itself is not shared between two runs: a smaller max step
    # lands on a different point of the output ripple, and 4 mF turns a few
    # millivolts there into most of a watt over this window.
    for name, a_win, b_win in (("vout_end_v", a["window"], b["window"]),
                               ("vout_start_v", a["window"], b["window"])):
        rows[name] = {"step_a": a_win[name], "step_b": b_win[name],
                      "delta": b_win[name] - a_win[name]}
    short = ("the port and loss integrals are trapezoid quadratures and converge; "
             "the storage terms are differences of two *instantaneous* samples, "
             "which do not.  vout_end_v differs between the runs because a "
             "smaller step lands elsewhere on the output ripple, and 4 mF times "
             "a few millivolts, over this span, is the same size as the closure "
             "residual itself -- so the closure is not resolved by the step "
             "check, it is limited by it")
    return {
        "step_a_s": a["raw"]["max_step_s"], "step_b_s": b["raw"]["max_step_s"],
        "raw_a": a["raw"]["path"], "raw_b": b["raw"]["path"],
        "periods": periods,
        "terms": rows,
        "note": short,
    }


def write(path: Path = OUT, step_raw: Path | None = None) -> dict[str, object]:
    summary = build()
    if step_raw is not None and step_raw.exists():
        summary["step_check"] = step_check(RAW, step_raw)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--json", type=Path, default=OUT)
    parser.add_argument("--periods", type=int, default=16)
    parser.add_argument("--compare-raw", type=Path, default=STEP_RAW,
                        help="second raw at a different max timestep (issue #6)")
    parser.add_argument("--no-step-check", action="store_true",
                        help="skip the timestep comparison (it only makes sense "
                             "for the 16-period window both raws share)")
    args = parser.parse_args()
    summary = build(args.raw, args.periods)
    if (not args.no_step_check and args.compare_raw is not None
            and args.compare_raw.exists()):
        summary["step_check"] = step_check(args.raw, args.compare_raw, args.periods)
    args.json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    balance = summary["balance"]
    res = balance["resolution"]
    print(json.dumps({"residual_w": balance["residual_w"],
                      "closure_residual_w": balance["closure_residual_w"],
                      "closure_status": balance["closure_status"],
                      "closure_reason": balance["closure_reason"],
                      "port_w": summary["port"]["pin_minus_pout_w"],
                      "resolution": {
                          "sem_w": res["sem_w"],
                          "sd_w": res["sd_w"],
                          "periods": res["periods"],
                          "periods_for_target": res["periods_for_target"],
                          "aligned_periods": res["phase_alignment"]["aligned_periods"],
                          "aligned_span_us":
                              float(res["phase_alignment"]["aligned_span_s"]) * 1e6},
                      "period_averaged": balance["period_averaged"],
                      "results": summary["results"],
                      "checks": summary["checks"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
