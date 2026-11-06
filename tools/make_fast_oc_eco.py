"""Generate the TLV3501 fast-overcurrent ECO module for D0.

Why a module and not a BOM edit
-------------------------------
D0's "fast" channel is U3B (LM393) fed from OC_FILT.  That node sits behind
three cascaded poles:

    OCD --[1k/47nF, 47 us]--> OCF --[10k/24k + 10nF, 70.6 us]--> OC
        --[10k/1nF, 10 us]--> OC_FILT --[LM393]--> FAST_TRIP (legacy D0)

so the comparator is not the problem; the ~128 us in front of it is.  Swapping
LM393 for a 4.5 ns part changes nothing measurable.  This module taps the CT
burden node (OCD) through a single 1 us pole, compares against a 2.5 V shunt
reference, and pulls FAST_EXT_N low through an open-drain NMOS.

It is a separate 4-pin board so D0's tests are untouched and the module can be
characterised on its own, then wired onto D0 at OCD / FAST_EXT_N / V5 / PGND.

Output polarity and wiring
--------------------------
J1.4 is FAST_EXT_N, active LOW. Connect only to D0 J10.4 (new receiver).
D0 inverts it with U11F, then ORs it with its separate high-active FAST_TRIP.
NEVER connect J1.4 to D0 TP8/FAST_TRIP: doing so suppresses faults.
The module is supplied from the same D0 V5 domain. The receiver's 100k
pull-down makes an open signal wire a fault while armed.

Rail isolation
--------------
D2 (IN+ clamp) is also a supply: with J1.1 open it turns the OCD divider into
a trickle charger for the module rail, and no datasheet number governs the
comparator below its 2.7 V minimum -- so a rail fed from OCD could sit in an
unspecified band with the output in an unspecified state.  D3 therefore feeds
the internal rail V5I from J1.1, and the only pull-up on FAST_EXT_N (R7) stays
on the connector net: losing J1.1 holds the line low whatever D2 does to V5I.
The available backfeed current is computed and reported, but the state is
proved only by the bench matrix, which is UNEXECUTED here.

Arithmetic the report carries (recomputed by the test)
------------------------------------------------------
* Trip at 75.0 A nominal (76.6 A with the hysteresis offset): 2.5 V reference,
  30k/15k divider, 0.1 V/A burden.  That is 5.4x the 13.88 A rated peak and
  above both UCC25600 levels (1 V / 24 A, 2 V / 48 A), so it does not disturb
  normal protection coordination.  It also sits above the 73.68 A peak of the
  frozen short-circuit deck -- a deliberate boundary, recorded as such.
* 3.2 A hysteresis through a 470k feedback resistor.
* 1.0 us input pole + 12 ns comparator worst case over temperature (5 mV
  overdrive) + ~50 ns gate network: about 1.06 us, versus ~128.9 us today.

SHDN is tied to PGND.  On the TLV3501 a HIGH shutdown pin *disables* the part
(within 0.9 V of V+); it is enabled only when SHDN is more than 1.7 V below V+.
Tying it to V+ is the single easiest way to build a fast comparator that never
switches, so a test pins the net to PGND.

Usage:
    python tools/make_fast_oc_eco.py
    python tools/make_fast_oc_eco.py --check
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import uuid
from dataclasses import replace
from pathlib import Path

from main_board_mechanical import find_kicad_cli

# Shared plumbing.  The SR board is the first generator to need it; importing
# keeps a single definition of pin parsing instead of a third copy.  Only the
# generic helpers are taken -- the part tables and the UUID namespace are local
# so the two boards cannot collide.
from make_sr_fault_board import (
    Part,
    Pin,
    custom_symbol,
    erc_violations,
    extract_symbol,
    pin_tips,
    validate,
    validate_no_coincident_tips,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "fast_oc"
NS = uuid.UUID("c41b7e08-5f2d-4a63-b9d1-0e8a6c3f2d75")


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def snap(part: Part) -> Part:
    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def kicad_cli() -> Path | None:
    return find_kicad_cli()


def symbol_libs() -> Path:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found; set KICAD_CLI to regenerate symbols")
    return cli.parent.parent / "share" / "kicad" / "symbols"


# ------------------------------------------------------------------ constants
CMP = "references/datasheets/tlv3501.txt"

# D1/D2 were written "BAT54" on a SOD-123 land, which is not a part number:
# Nexperia's BAT54 is SOT-23 and its BAT54W is SOT323.  Vishay's BAT54W is
# SOD-123 and its ordering table is in references/, so that is the code written
# to the BOM.  Selection is not qualification -- see d12_selection().
D12_MPN = "BAT54W-E3-08"
D12_MPN_SOURCE = "references/datasheets/bat54w.txt"
D12_FP = "Diode_SMD:D_SOD-123"
D12_FP_FILE = "hardware/stock_footprints/Diode_SMD.pretty/D_SOD-123.kicad_mod"
# Vishay's own land recommendation, from the drawing on p.4 (0.85 x 0.85 pads,
# 2.5 mm between the pads).  The vendored land is parsed from its file so the
# two can be compared instead of asserted.
D12_VENDOR_PAD_W = 0.85
D12_VENDOR_PAD_H = 0.85
D12_VENDOR_GAP = 2.5

VREF = 2.5                 # V, TI LM4040D25IDBZR
R_TOP = 30e3               # ohm, OCD -> IN+
R_BOT = 15e3               # ohm, IN+ -> PGND
C_IN = 100e-12             # F, IN+ to PGND
R_HYST = 470e3             # ohm, OUT -> IN+
R_GATE = 100.0             # ohm, comparator OUT -> Q1 gate
C_GATE = 100e-12           # F, 2N7002 gate capacitance (datasheet typical)
R_BIAS = 2.4e3             # ohm, V5I -> REF
V5 = 5.0                   # V, module supply at the connector (J1.1)
# D3 isolates the module rail from the connector.  The same clamp diode that
# keeps IN+ from running above V+ (D2) is also a power supply when the rail is
# dead, so the rail is fed through a diode and the healthy pull-up R7 is
# referenced to the connector instead.  VF is the Vishay maximum at the
# module's own load current (400 mV at IF = 10 mA, Doc 86408 p.2).
VF_D3 = 0.40               # V, BAT54W forward drop at the rail current
V5I = V5 - VF_D3           # V, worst-case internal rail (4.60 V)
BURDEN_V_PER_A = 0.1       # V/A, R_burden / CT ratio = 10 ohm / 100

# TLV3501, SBOS321E.  Propagation delay is quoted at two overdrives; the
# worst case over temperature is the 5 mV, 12 ns number, and that is what the
# budget uses (the roadmap forbids quoting the typical 4.5 ns).
TPD_TYP_20MV = 4.5e-9
TPD_MAX_20MV_25C = 6.4e-9
TPD_TYP_5MV_25C = 7.5e-9
TPD_MAX_5MV_25C = 10e-9
TPD_MAX_5MV_OVER_TEMP = 12e-9
CM_LOW = -0.2              # V relative to V- (absolute maximum is -0.3 V)
CM_HIGH_MARGIN = 0.2       # V below V+
ABS_MAX_MARGIN = 0.3       # V beyond either rail
RAIL_MIN_V = 2.7           # V, lowest V+ at which the datasheet specifies anything
IQ_MAX = 5e-3              # A
SHDN_ENABLE_BELOW = V5I - 1.7   # < 2.9 V enables; > 3.7 V disables (vs V+ = V5I)

# The status quo on D0 (make_d0_protection_board.ct_parts).
EXISTING_TAUS = (
    ("rf_cf", 1e3 * 47e-9),
    ("rd1_rd2_coc", 10e3 * 24e3 / (10e3 + 24e3) * 10e-9),
    ("r12_c13", 10e3 * 1e-9),
)
LM393_TPD_TYP = 1.3e-6

# Fault peaks already published in this repository, for the threshold table.
KNOWN_PEAKS_A = {
    "steady_state_rated": 13.88,
    "ucc25600_level1": 24.2,
    "frozen_short_circuit_deck": 73.68,
    "cold_start_fault": 84.83,
    "hotfault_48v": 97.44,
    "hotfault_50v_prefix": 101.26,
}


# ------------------------------------------------------------------ symbols
STANDARD = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:C": ("Device.kicad_sym", "C"),
    "Device:D_Schottky": ("Device.kicad_sym", "D_Schottky"),
    "Comparator:TLV3501AIDBV": ("Comparator.kicad_sym", "TLV3501AIDBV"),
    "Transistor_FET:Q_NMOS_GSD": ("Transistor_FET.kicad_sym", "Q_NMOS_GSD"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def build_symbols() -> dict[str, str]:
    # Offline tests validate frozen embedded symbols, not current OEM KiCad
    # symbol libraries. Real ERC and footprint checks still need kicad-cli.
    cli = kicad_cli()
    libs = symbol_libs() if cli is not None else None
    source_schematic = OUT / "fast_oc.kicad_sch"
    if libs is None and not source_schematic.is_file():
        raise SystemExit("KiCad symbols unavailable: supply kicad-cli or a committed schematic")
    symbols: dict[str, str] = {}
    for lib_id, (lib, name) in STANDARD.items():
        if libs is None:
            block = extract_symbol(source_schematic, lib_id)
        else:
            block = extract_symbol(libs / lib, name)
            block = block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
        symbols[lib_id] = block
    # LM4040 DBZ pin 3 is marked '*' by TI and can float or connect to
    # the anode (preferred in noisy environments); it is NOT a guaranteed NC.
    # A two-pin symbol leaves physical SOT-23 pad 3 intentionally floating.
    symbols["FASTOC:LM4040"] = custom_symbol(
        "FASTOC:LM4040",
        [Pin("1", "K", 2.54, 0, 180, "power_out"),
         Pin("2", "A", -2.54, 0, 0, "power_in")],
        5.08, 5.08, footprint="Package_TO_SOT_SMD:SOT-23")
    return symbols


# ------------------------------------------------------------------ parts
# SOT-23 has 3 pads; the LM4040D25IDBZR pin 3 is intentionally floated (NOT NC)
# and the 2N7002.  The TLV3501AIDBV is the six-pin DBV package and must NOT
# share this constant -- a shared constant is how a six-pin part ended up with
# a three-pad land while ERC (which ignores footprints) stayed green.
SMD = "Package_TO_SOT_SMD:SOT-23"


def parts() -> list[Part]:
    ps = [
        Part("J1", "Connector_Generic:Conn_01x04", "5V/OCD/FAST_EXT_N",
             "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 30, 60,
             {"1": "V5", "2": "PGND", "3": "OCD", "4": "FAST_EXT_N"},
             rating="5 V",
             note="wire to D0: V5, PGND, OCD (R8 node), FAST_EXT_N (J10.4 ONLY)"),
        Part("D3", "Device:D_Schottky", "BAT54W", D12_FP, 46, 60,
             {"1": "V5I", "2": "V5"}, rating="30 V",
             note="rail isolation: feeds V5I from J1.1 and blocks any backfeed from "
                  "reaching the connector", mpn=D12_MPN, mpn_source=D12_MPN_SOURCE),
        Part("C1", "Device:C", "1uF/16V", "Capacitor_SMD:C_0603_1608Metric", 62, 48,
             {"1": "V5I", "2": "PGND"}, rating="16 V X7R", note="supply bulk, module side of D3"),
        Part("C2", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 74, 48,
             {"1": "V5I", "2": "PGND"}, rating="16 V X7R", note="at U1 pin 4"),
        Part("U1", "Comparator:TLV3501AIDBV", "TLV3501AIDBVR",
             "Package_TO_SOT_SMD:SOT-23-6", 90, 80,
             {"1": "REF", "2": "PGND", "3": "INP", "4": "V5I",
              "5": "OUT", "6": "SHDN"},
             rating="2.7-5.5 V",
             note="pin 1 = IN-, pin 3 = IN+, pin 6 = SHDN tied LOW to enable"),
        Part("U2", "FASTOC:LM4040", "LM4040D25IDBZR", SMD, 62, 100,
             {"1": "REF", "2": "PGND"}, rating="2.5 V",
             note="TI DBZ pin3: float or connect to anode; for EMI prefer anode"),
        Part("R1", "Device:R", "2.4k", "Resistor_SMD:R_0603_1608Metric", 50, 92,
             {"1": "V5I", "2": "REF"},
             note="reference bias, (4.6-2.5)/2.4k = 0.88 mA"),
        Part("C3", "Device:C", "100nF/16V", "Capacitor_SMD:C_0603_1608Metric", 62, 112,
             {"1": "REF", "2": "PGND"}, rating="16 V X7R", note="reference bypass"),
        Part("R2", "Device:R", "30k 1%", "Resistor_SMD:R_0603_1608Metric", 70, 74,
             {"1": "OCD", "2": "INP"}, note="divider top; 1/3 of the burden voltage"),
        Part("R3", "Device:R", "15k 1%", "Resistor_SMD:R_0603_1608Metric", 70, 90,
             {"1": "INP", "2": "PGND"}, note="divider bottom"),
        Part("C4", "Device:C", "100pF/50V", "Capacitor_SMD:C_0603_1608Metric", 70, 102,
             {"1": "INP", "2": "PGND"}, rating="50 V C0G",
             note="1 us with the 10k divider Thevenin"),
        Part("R4", "Device:R", "470k 1%", "Resistor_SMD:R_0603_1608Metric", 96, 64,
             {"1": "INP", "2": "OUT"}, note="positive feedback: 3.2 A hysteresis"),
        Part("D1", "Device:D_Schottky", "BAT54W", D12_FP, 58, 66,
             {"1": "INP", "2": "PGND"}, rating="30 V",
             note="cathode at IN+: holds the pin above -0.3 V; SOD-123, not the "
                  "SOT-23 BAT54", mpn=D12_MPN, mpn_source=D12_MPN_SOURCE),
        Part("D2", "Device:D_Schottky", "BAT54W", D12_FP, 58, 56,
             {"1": "V5I", "2": "INP"}, rating="30 V",
             note="cathode at V5I: clamps IN+ above the module rail; with the rail "
                  "dead this path would otherwise power it, which is why D3 exists",
             mpn=D12_MPN, mpn_source=D12_MPN_SOURCE),
        Part("R5", "Device:R", "100R", "Resistor_SMD:R_0603_1608Metric", 108, 80,
             {"1": "OUT", "2": "Q1G"}, note="gate series"),
        Part("R6", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 120, 92,
             {"1": "Q1G", "2": "PGND"},
             note="Q1 off while the comparator is unpowered"),
        Part("Q1", "Transistor_FET:Q_NMOS_GSD", "2N7002", SMD, 120, 74,
             {"1": "Q1G", "2": "PGND", "3": "FAST_EXT_N"}, rating="60 V",
             note="open-drain output; overcurrent pulls FAST_EXT_N low"),
        Part("R7", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 134, 62,
             {"1": "V5", "2": "FAST_EXT_N"},
             note="pull-up from the connector rail, not V5I: losing J1.1 must leave "
                  "FAST_EXT_N low; D0 J10.4 has 100k pull-down, NOT R15"),
        Part("R8", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric", 104, 96,
             {"1": "PGND", "2": "SHDN"},
             note="SHDN low enables the comparator; 2 pA bias -> 20 nV across 10k"),
        Part("#FLG1", "power:PWR_FLAG", "PWR_FLAG", "", 40, 36, {"1": "V5"}, "",
             "ERC: bench supply is the source"),
        Part("#FLG2", "power:PWR_FLAG", "PWR_FLAG", "", 52, 36, {"1": "PGND"}, "",
             "ERC: return is a source"),
        Part("#FLG3", "power:PWR_FLAG", "PWR_FLAG", "", 64, 36, {"1": "V5I"}, "",
             "ERC: D3 is the only element between the connector rail and V5I, and a "
             "passive cannot drive a power_in pin"),
    ]
    ps += [
        Part(ref, "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
             30 + 14 * i, 130, {"1": net}, "1 mm pad", "scope probe")
        for i, (ref, net) in enumerate([
            ("TP1", "OCD"), ("TP2", "INP"), ("TP3", "REF"), ("TP4", "OUT"),
            ("TP5", "FAST_EXT_N"), ("TP6", "SHDN"), ("TP7", "V5"), ("TP8", "PGND"),
        ])
    ]
    return ps


# ------------------------------------------------------------------ physics
def divider() -> dict:
    """Trip and release currents through the real three-resistor network."""
    g = 1.0 / (1.0 / R_TOP + 1.0 / R_BOT + 1.0 / R_HYST)

    def ocd_for(out_v: float) -> float:
        return (VREF / g - out_v / R_HYST) * R_TOP

    # OUT high is V5I, not the connector: D3 sits between them.
    up, down = ocd_for(0.0), ocd_for(V5I)
    rth = 1.0 / (1.0 / R_TOP + 1.0 / R_BOT)
    return {
        "divider_ratio": R_BOT / (R_TOP + R_BOT),
        "nominal_trip_current_a": VREF * (R_TOP + R_BOT) / R_BOT / BURDEN_V_PER_A,
        "trip_burden_v": up,
        "release_burden_v": down,
        "trip_current_a": up / BURDEN_V_PER_A,
        "release_current_a": down / BURDEN_V_PER_A,
        "hysteresis_v": up - down,
        "hysteresis_a": (up - down) / BURDEN_V_PER_A,
        "thevenin_ohm": rth,
        "input_tau_s": C_IN * rth,
    }


def common_mode() -> dict:
    """Where the input pin sits for every published fault current."""
    rows = []
    for name, current in KNOWN_PEAKS_A.items():
        burden = current * BURDEN_V_PER_A
        inp = burden * R_BOT / (R_TOP + R_BOT)
        rows.append({
            "case": name,
            "primary_peak_a": current,
            "burden_v": burden,
            "in_plus_v": inp,
            "within_common_mode": CM_LOW <= inp <= V5I - CM_HIGH_MARGIN,
            "within_absolute_max": CM_LOW - ABS_MAX_MARGIN <= inp
                                   <= V5I + ABS_MAX_MARGIN,
        })
    return {
        "common_mode_range_v": [CM_LOW, V5I - CM_HIGH_MARGIN],
        "absolute_max_range_v": [CM_LOW - ABS_MAX_MARGIN, V5I + ABS_MAX_MARGIN],
        "current_at_common_mode_limit_a": (V5I - CM_HIGH_MARGIN) * 3 / BURDEN_V_PER_A,
        "current_at_clamp_conduction_a": (V5I + ABS_MAX_MARGIN) * 3 / BURDEN_V_PER_A,
        "rows": rows,
    }


def delay() -> dict:
    """Worst-case module delay, and the status quo it replaces."""
    d = divider()
    gate_tau = R_GATE * C_GATE
    module = d["input_tau_s"] + TPD_MAX_5MV_OVER_TEMP + 5 * gate_tau
    existing = sum(tau for _, tau in EXISTING_TAUS) + LM393_TPD_TYP
    return {
        "input_tau_s": d["input_tau_s"],
        "comparator_worst_s": TPD_MAX_5MV_OVER_TEMP,
        "comparator_typ_s": TPD_TYP_20MV,
        "gate_network_s": 5 * gate_tau,
        "module_total_s": module,
        "existing_path": [{"stage": name, "tau_s": tau} for name, tau in EXISTING_TAUS],
        "existing_path_comparator_s": LM393_TPD_TYP,
        "existing_path_total_s": existing,
        "improvement_factor": existing / module,
        "worst_case_basis": "5 mV overdrive, -40 to +125 C, 12 ns",
        "note": "the existing figure is a sum of cascaded time constants, not a "
                "propagation delay; it is an order-of-magnitude comparison only",
    }


SR_BOARD = ROOT / "pcb" / "sr_fault_validation" / "sr_fault_validation.json"
D0_BUDGET = ROOT / "design" / "v3" / "stage_f" / "d0_response_budget.json"


def d0_common_logic() -> dict:
    """D0's decode and latch: the stages between a trip signal and the branch.

    This module ends at J1.4.  Before the trip reaches the flip-flop's SET it
    crosses D0's decode (U11F, U19, U6.4 and the three U10 ORs) and then the
    CD4013.  Both figures are owned by ``tools/d0_response_budget.py``, so they
    are read from its record instead of being re-derived here -- the same rule
    the shutdown branches already follow.

    The two paths do not cross the same gates.  The legacy LM393 trip enters
    U19 directly, while this module's low-true output first crosses U11F, so the
    status quo must be charged the ``fast`` channel's 1.00 us and this module the
    ``external`` channel's 1.11 us.  Charging one figure to both would either
    hide the inverter or bill it to a path that does not contain it.
    """
    if not D0_BUDGET.is_file():
        raise SystemExit(f"{D0_BUDGET} is missing; run tools/d0_response_budget.py first")
    stages = json.loads(D0_BUDGET.read_text(encoding="utf-8"))["stages"]
    per_channel = stages["decode"]["per_channel"]
    for channel, first_gate in (("external", "U11.6"), ("fast", "U19.1")):
        if per_channel[channel]["gates"][:1] != [first_gate]:
            raise SystemExit(
                f"the {channel} decode starts at {per_channel[channel]['gates'][:1]}, "
                f"not {first_gate}: the receiver chain moved, so the module's term "
                "no longer applies")
    latch_us = stages["latch"]["us"]

    def path(channel: str) -> dict:
        decode = per_channel[channel]
        return {
            "decode_s": decode["priced_max_us"] * 1e-6,
            "latch_s": latch_us * 1e-6,
            "total_s": (decode["priced_max_us"] + latch_us) * 1e-6,
            "decode_gates": list(decode["gates"]),
            "unpriced_gates": list(decode["unpriced_gates"]),
            "complete": decode["complete"],
        }

    module_path, existing_path = path("external"), path("fast")
    return {
        "module_path": module_path,
        "existing_path": existing_path,
        "is_a_floor": not (module_path["complete"] and existing_path["complete"]),
        "why_a_floor": "U6.4 (CD4081B) publishes no propagation maximum, so it is "
                       "counted at zero and sits in unpriced_gates",
        "source": "design/v3/stage_f/d0_response_budget.json "
                  "(stages.decode.per_channel.external / .fast, stages.latch)",
    }


def system_delay() -> dict:
    """The roadmap's whole-machine t_stop, not just this module.

    ``t_stop = t_CT/rectifier/filter + t_cmp + t_common_logic + max(t_primary, t_SR)``

    The module only owns the first two terms.  The common logic is D0's decode
    and latch, read from the D0 budget.  The shutdown branches come from the
    single-pair SR board's ``delay_budget``, which is read rather than
    re-derived so the two documents cannot drift.  On this machine the SR
    branch wins by an order of magnitude: the UCC24624 does not let go of VG
    until REG has fallen through UVLO.

    The actual SR board input ladder is included in Q41 turn-on exactly once.
    The former 10 us standalone RC subtraction does not apply.
    """
    if not SR_BOARD.is_file():
        raise SystemExit(f"{SR_BOARD} is missing; run tools/make_sr_fault_board.py first")
    sr = json.loads(SR_BOARD.read_text(encoding="utf-8"))["delay_budget"]
    branch = sr["sr_branch"]
    sr_branch = (branch["crowbar_fet_turn_on_s"] + branch["reg_to_uvlo_s"]
                 + branch["vg_active_low_s"])
    primary_branch = sr["primary_branch_reference"]["total_s"]
    slowest = max(sr_branch, primary_branch)
    common = d0_common_logic()
    module = delay()["module_total_s"]
    existing = delay()["existing_path_total_s"]
    module_floor = module + common["module_path"]["total_s"] + slowest
    existing_floor = existing + common["existing_path"]["total_s"] + slowest
    return {
        "equation": "t_stop = t_CT/rectifier/filter + t_cmp + t_common_logic "
                    "+ max(t_primary, t_SR)",
        "detection_module_s": module,
        "common_logic_s": common["module_path"]["total_s"],
        "common_logic_terms": common["module_path"],
        "existing_common_logic_s": common["existing_path"]["total_s"],
        "existing_common_logic_terms": common["existing_path"],
        "common_logic_is_a_floor": common["is_a_floor"],
        "common_logic_note": "read from D0's own budget, not re-derived here; the two "
                             "paths differ by the U11F inverter, and the figure stays a "
                             "floor because U6.4 publishes no maximum",
        "d0_budget": common["source"],
        "sr_branch_s": sr_branch,
        "sr_branch_terms": {
            "crowbar_fet_turn_on_s": branch["crowbar_fet_turn_on_s"],
            "reg_to_uvlo_s": branch["reg_to_uvlo_s"],
            "vg_active_low_s": branch["vg_active_low_s"],
            "excluded_input_rc_s": branch["input_rc_s"],
            "excluded_input_rc_reason": "none excluded: actual C40/R40/R41 are included in Q41 turn-on",
        },
        "primary_branch_s": primary_branch,
        "slowest_branch": "sr" if sr_branch > primary_branch else "primary",
        "system_floor_s": module_floor,
        "existing_system_floor_s": existing_floor,
        "estimate_not_guaranteed_lower_bound": True,
        "model_scope": "Legacy floor field names retained; Q41 uses typical nonlinear-device "
                       "approximations. These totals are neither measured nor guaranteed bounds. "
                       "Applies to the actual SR validation input ladder; another harness needs a new budget.",
        "system_improvement_factor": existing_floor / module_floor,
        "note": "the 121x module figure is a detection-only comparison; against the whole "
                "machine the comparator change is worth the ratio below, because the REG "
                "crowbar sets the stop time",
        "comparison_caveat": "the two detection terms are not of one kind: the module's "
                             "1.06 us is a worst case over -40..+125 C, while the filtered "
                             "path's 128.9 us is a sum of cascaded time constants plus the "
                             "LM393's typical delay. The decode and latch added to each are "
                             "maxima, so the existing total is still the optimistic side",
    }


def supply() -> dict:
    bias = (V5I - VREF) / R_BIAS
    return {
        "connector_rail_v": V5,
        "internal_rail_v": V5I,
        "isolation": f"D3 BAT54W between J1.1 V5 and V5I; VF <= {VF_D3:.2f} V "
                     f"at the module's load current",
        "bias_current_a": bias,
        "reference_holds_down_to_v": VREF,
        "shutdown_enable_threshold_v": SHDN_ENABLE_BELOW,
        "shutdown_logic": "SHDN low enables; within 0.9 V of V+ disables",
        "quiescent_current_max_a": IQ_MAX,
        "loss_of_5v": "D3 keeps the backfeed off the connector and R7 is the only "
                      "element that can raise FAST_EXT_N; with J1.1 at 0 V the "
                      "receiver's 100k holds the line low through Q1 or R7's open "
                      "top. The rail itself can still be backfed through D2, so "
                      "the state is proved by the bench matrix, not by this note",
        "minimum_reference_current": "UNVERIFIED - the LM4040D25IDBZR minimum "
                                     "operating current is not in this repository",
    }


def backfeed() -> dict:
    """What the D2 clamp can do to a dead rail, and why D3 exists.

    D2 keeps IN+ from running more than a diode drop above the module rail.
    When J1.1 is open that same path is a supply: the OCD divider feeds IN+,
    D2 conducts into V5I and charges C1.  The current available into the rail
    is the divider current left after the lower leg,

        I = OCD/R_TOP - (V_rail + VF_D2) * (1/R_TOP + 1/R_BOT),

    which peaks at V_rail = 0.  Compare that with the comparator's own
    maximum quiescent current only as a load sensitivity, NOT a minimum load.
    It cannot prove the rail stays below its 2.7 V minimum, and
    below that minimum no datasheet number governs the output.  "Not
    specified" is exactly the condition that must not be written as "healthy"
    or as "passed", so the rail is isolated and the healthy pull-up is
    referenced to the connector instead of the rail.
    """
    vf_d2 = VF_D3  # same part, same current
    divider = (R_TOP + R_BOT) / R_BOT
    cm_limit_a = (V5I - CM_HIGH_MARGIN) * divider / BURDEN_V_PER_A

    def available(ocd_v: float, rail_v: float) -> float:
        return max(ocd_v / R_TOP - (rail_v + vf_d2) * (1 / R_TOP + 1 / R_BOT), 0.0)

    ocd_at_cm_limit = cm_limit_a * BURDEN_V_PER_A
    available_at_cm = available(ocd_at_cm_limit, 0.0)
    # OCD needed to hold the rail at its own minimum while the comparator
    # draws its rated quiescent current.
    ocd_for_min_rail = ((IQ_MAX + (RAIL_MIN_V + vf_d2) * (1 / R_TOP + 1 / R_BOT))
                        * R_TOP / BURDEN_V_PER_A)
    return {
        "problem": "with J1.1 open, D2 turns the OCD divider into a supply for "
                   "the dead rail; R7 was referenced to that rail, so the "
                   "healthy level depended on the backfeed",
        "common_mode_current_a": cm_limit_a,
        "common_mode_burden_v": ocd_at_cm_limit,
        "available_current_at_design_max_a": available_at_cm,
        "available_current_basis": f"{cm_limit_a:.1f} A common-mode limit "
                                   f"({ocd_at_cm_limit:.1f} V burden), rail at 0 V",
        "comparator_quiescent_max_a": IQ_MAX,
        "max_iq_to_available_ratio_assumption": IQ_MAX / available_at_cm,
        "minimum_load_known": False,
        "rail_cannot_start_proven": False,
        "rail_minimum_v": RAIL_MIN_V,
        "ocd_for_rail_minimum_assuming_max_iq_a": ocd_for_min_rail,
        "load_sensitivity_note": "5 mA is a maximum, not a minimum; this is not a no-start threshold",
        "rail_state_below_minimum": "UNSPECIFIED - the TLV3501 datasheet stops at "
                                    "2.7 V, so neither the output level nor the "
                                    "supply current is bounded there",
        "mitigation": "D3 feeds V5I from J1.1 and blocks the connector from being "
                      "backfed; R7 stays on the connector net, so a lost J1.1 "
                      "leaves FAST_EXT_N low whatever D2 does to V5I",
        "structural_invariant": "FAST_EXT_N can only be raised by R7, and R7's top "
                                "is the V5 connector net; Q1 only pulls down",
        "residual": "an open D3, or a comparator whose supply pin is open while "
                    "J1.1 is live, still leaves R7 able to raise the line; a "
                    "pull-up cannot detect its own load disappearing",
    }


def verification() -> dict:
    """The bench matrix the review asks for: circuit, signals, cases, criteria.

    Nothing here has been executed.  Every case carries ``executed: false`` and
    a null ``result`` on purpose: the module is a schematic and a routed board,
    not a tested assembly, and a matrix filled with expected values that reads
    like measurements is the failure mode this file is trying to avoid.
    """
    cases = [
            {
                "id": "BF-01",
                "name": "healthy baseline",
                "setup": "J1.1 5.0 V, OCD 0 V, all wires intact",
                "stimulus": "none",
                "expected": "FAST_EXT_N = 5 V x 100k/110k = 4.55 V; FAST_COMBINED "
                            "low; PERMIT high; I(V5) = bias + quiescent + R7",
                "pass_criteria": "4.2 V <= FAST_EXT_N <= 4.8 V and PERMIT high",
            },
            {
                "id": "BF-02",
                "name": "trip baseline",
                "setup": "J1.1 5.0 V, OCD 7.5 V (75 A), all wires intact",
                "stimulus": "step OCD from 0 to 7.5 V",
                "expected": "FAST_EXT_N < 0.4 V; FAST_COMBINED high; PERMIT low",
                "pass_criteria": "Q1 pulls the line below 0.4 V within 1.1 us",
            },
            {
                "id": "BF-03",
                "name": "J1.1 open, OCD low",
                "setup": "J1.1 wire open, OCD 0 V",
                "stimulus": "none",
                "expected": "FAST_EXT_N <= 0.3 V (100k), FAST_COMBINED high, PERMIT "
                            "low, I(V5) = 0",
                "pass_criteria": "line <= 0.3 V and PERMIT low",
            },
            {
                "id": "BF-04",
                "name": "J1.1 open, OCD high (the backfeed case)",
                "setup": "J1.1 wire open, OCD 15 V (150 A), the design absolute "
                         "maximum; C1 discharged before the step",
                "stimulus": "step OCD 0 -> 15 V, hold 10 s",
                "expected": "FAST_EXT_N <= 0.3 V because R7's top is the connector "
                            "net; V5I may rise through D2 but must not reach the "
                            "connector (measure J1.1 = 0 V)",
                "pass_criteria": "line <= 0.3 V, PERMIT low, I into J1.1 = 0, and "
                                 "V(V5I) recorded (any value is a result, not a pass)",
            },
            {
                "id": "BF-05",
                "name": "signal wire open, module powered",
                "setup": "J1.4 open at the module end, J1.1 5.0 V",
                "stimulus": "OCD 0 V, then 7.5 V",
                "expected": "receiver input is pulled to 0 V by its 100k in both "
                            "states: FAST_COMBINED high, PERMIT low",
                "pass_criteria": "fault asserted for both OCD levels",
            },
            {
                "id": "BF-06",
                "name": "whole V5 domain slow decay",
                "setup": "J1.1 5.0 -> 0 V over 100 ms, wires intact",
                "stimulus": "linear decay at OCD 0 V, repeat at OCD 7.5 V",
                "expected": "FAST_EXT_N follows R7 down; the receiver must read "
                            "fault before V5I falls below 2.7 V; PERMIT releases",
                "pass_criteria": "no sample with FAST_EXT_N > 3.5 V while "
                                 "V(V5I) < 2.7 V; record the crossing and t(PERMIT)",
            },
            {
                "id": "BF-07",
                "name": "recovery",
                "setup": "J1.1 0 -> 5.0 V over 100 ms after BF-06",
                "stimulus": "same ramp, then hold 10 s",
                "expected": "FAST_EXT_N returns high only after V5I > 2.7 V; PERMIT "
                            "stays low until D0's latch is reset by the operator",
                "pass_criteria": "record t(FAST_EXT_N high), t(V5I > 2.7 V) and "
                                 "whether PERMIT re-arms without a reset (it must not)",
            },
            {
                "id": "BF-08",
                "name": "rail collapse with OCD live",
                "setup": "J1.1 falls 5.0 -> 0 V in < 1 ms while OCD = 15 V",
                "stimulus": "abrupt open, C1 hold-up is the only supply",
                "expected": "FAST_EXT_N stays low throughout; the module may latch "
                            "Q1 on or off but never high",
                "pass_criteria": "record the line at 100 us and 1 ms; any excursion "
                                 "above 0.4 V fails",
            },
    ]
    # The unexecuted state is applied here, not typed into every row: a case
    # that forgets the flag would otherwise read as a measurement.
    for case in cases:
        case["executed"] = False
        case["result"] = None
    return {
        "status": "UNEXECUTED",
        "hardware": "none - the module has no built board",
        "fixture": {
            "supply": "isolated, current-limited 5.0 V on J1.1 (limit <= 100 mA)",
            "ocd_source": "isolated, current-limited 0-15 V on J1.3; set the limit "
                          "to 20 mA (the divider draws at most OCD/30k)",
            "v5_open": "break the J1.1 wire at the module end; do not remove PGND",
            "signal_open": "break J1.4 at the module end; the receiver keeps its 100k",
            "receiver": "D0 J10.4 / U11F / U19 (or an equivalent 4000B inverter and "
                        "OR on the bench); D0 has a schematic but no PCB",
            "loads": "10k from FAST_EXT_N to PGND models the module's own R7 return "
                     "path; 100k to PGND models D0's pull-down (the receiver input)",
            "instruments": ">= 4 channels, 100 MHz; differential probe for VGS if the "
                           "SR path is connected; series ammeter on J1.1 (uA range for "
                           "the open-wire cases)",
        },
        "signals": ["FAST_EXT_N", "FAST_COMBINED", "PERMIT", "I(V5) module supply "
                    "current", "V(V5I)", "V(INP)", "V(OUT)"],
        "cases": cases,
        "notes": [
            "expected values are computed from the schematic, not measured; each "
            "case is a prediction until the raw trace is attached",
            "PERMIT and FAST_COMBINED are D0 nodes; D0 has no PCB, so BF-05/06/07 "
            "need either a D0 prototype or an equivalent receiver on the bench",
            "the V5 current in BF-04 must be measured with a uA meter: the whole "
            "point is that the connector carries nothing once D3 is in place",
        ],
    }


def observations() -> list[dict]:
    d, dl, cm = divider(), delay(), common_mode()
    sd = system_delay()
    return [
        {
            "id": "OC-01",
            "finding": "The LM393 is not the bottleneck: the three filters in "
                       "front of it total ~127.6 us of time constants.",
            "evidence": "D0 ct_parts Rf/Cf, Rd1/Rd2/Coc, R12/C13",
            "status": "DESIGN_FACT",
        },
        {
            "id": "OC-02",
            "finding": f"The module trips at {d['trip_current_a']:.1f} A peak "
                       f"({d['trip_burden_v']:.2f} V burden) and releases at "
                       f"{d['release_current_a']:.1f} A; the nominal divider "
                       f"crossing is {d['nominal_trip_current_a']:.1f} A.",
            "evidence": f"divider arithmetic against the {CMP} reference and "
                        "the project CT transfer 0.1 V/A",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-03",
            "finding": f"Total module delay is ~{dl['module_total_s'] * 1e6:.2f} us "
                       f"using the 12 ns over-temperature comparator number, "
                       f"about {dl['improvement_factor']:.0f}x faster than the "
                       "existing filtered path.",
            "evidence": f"{CMP} switching characteristics, overdrive 5 mV, "
                        "-40 to +125 C",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-03b",
            "finding": f"That 121x is detection only. With D0's decode and latch and the SR "
                       f"board's shutdown branch added, the whole-machine stop goes from "
                       f"~{sd['existing_system_floor_s'] * 1e6:.1f} us to "
                       f"~{sd['system_floor_s'] * 1e6:.1f} us -- "
                       f"{sd['system_improvement_factor']:.1f}x -- because the "
                       f"{sd['slowest_branch']} branch sets it. Both totals pay their own "
                       f"decode ({sd['common_logic_s'] * 1e6:.2f} us here, "
                       f"{sd['existing_common_logic_s'] * 1e6:.2f} us on the filtered path) "
                       "and both stay floors: U6.4 has no published maximum.",
            "evidence": "pcb/sr_fault_validation/sr_fault_validation.json:delay_budget; "
                        "design/v3/stage_f/d0_response_budget.json:stages",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "OC-04",
            "finding": "The input pin stays inside the common-mode range up to "
                       f"{cm['current_at_common_mode_limit_a']:.0f} A peak. "
                       "Above that the comparator is out of range but still "
                       "inside its absolute maximum, so it is already tripped "
                       "and the output state no longer matters.",
            "evidence": f"{CMP} common-mode range (V-)-0.2 V to (V+)-0.2 V, "
                        "absolute maximum (V-)-0.3 V to (V+)+0.3 V",
            "status": "BOUNDARY",
        },
        {
            "id": "OC-05",
            "finding": "The threshold sits above the 73.68 A peak of the frozen "
                       "short-circuit deck, so that case is left to the "
                       "controller's own overcurrent. The module is aimed at the "
                       "84-101 A severe faults.",
            "evidence": "design/v3/power_priority: lr_design.json PHYSICAL_PEAKS "
                        "and the hotfault prefixes",
            "status": "DESIGN_DECISION",
        },
        {
            "id": "OC-06",
            "finding": "SHDN tied high would disable the comparator; it is tied "
                       "to PGND through R8.",
            "evidence": f"{CMP} shutdown section: high (within 0.9 V of V+) "
                        "disables, more than 1.7 V below V+ enables",
            "status": "DESIGN_FACT",
        },
        {
            "id": "OC-07",
            "finding": "The module does not latch; the CD4013 on D0 does. Used "
                       "standalone, the output follows the current.",
            "evidence": "D0 J10/U11F/U19 -> FAST_COMBINED -> U6/U10 -> U12 SET",
            "status": "DESIGN_FACT",
        },
    ]


def _vendored_pads(path: Path) -> dict[str, dict[str, float]]:
    """Pad name -> (x, y, w, h) from a vendored ``.kicad_mod``.

    Parsed rather than transcribed so the report compares the land the board
    actually uses against the vendor recommendation; a hand-copied number would
    stay right while the library changed underneath it.
    """
    text = path.read_text(encoding="utf-8")
    pads: dict[str, dict[str, float]] = {}
    for chunk in text.split('(pad "')[1:]:
        name = chunk.split('"', 1)[0]
        at = chunk.split("(at ", 1)[1].split(")", 1)[0].split()
        size = chunk.split("(size ", 1)[1].split(")", 1)[0].split()
        pads[name] = {"x_mm": float(at[0]), "y_mm": float(at[1]),
                      "w_mm": float(size[0]), "h_mm": float(size[1])}
    return pads


def d12_selection() -> dict:
    """What D1/D2 are, which land they sit on, and what is still open.

    The review's point: "BAT54 + SOD-123" cannot be ordered, because the same
    short name is SOT-23 at one vendor and SOT323 at another.  Vishay's BAT54W
    is the SOD-123 part and its ordering table is in the repository, so the MPN
    is written; the land is then checked against the vendor drawing instead of
    assumed compatible.
    """
    pads = _vendored_pads(ROOT / D12_FP_FILE)
    left, right = pads["1"], pads["2"]
    centres = abs(right["x_mm"] - left["x_mm"])
    gap = centres - (left["w_mm"] + right["w_mm"]) / 2
    return {
        "refs": ["D1", "D2", "D3"],
        "mpn": D12_MPN,
        "mpn_source": D12_MPN_SOURCE,
        "package": "SOD-123",
        "footprint": D12_FP,
        "pins": {"1": "K", "2": "A"},
        "rail_isolation_ref": "D3, cathode on V5I / anode on J1.1 V5",
        "datasheet": {
            "vrr_v": 30.0,
            "if_ma": 200.0,
            "ifrm_ma": 300.0,
            "ifsm_a": 0.6,
            "ptot_mw": 230.0,
        },
        "land": {
            "vendored_pad_mm": [left["w_mm"], left["h_mm"]],
            "vendored_centre_spacing_mm": centres,
            "vendored_gap_mm": gap,
            "vendor_pad_mm": [D12_VENDOR_PAD_W, D12_VENDOR_PAD_H],
            "vendor_gap_mm": D12_VENDOR_GAP,
            "vendor_centre_spacing_mm": D12_VENDOR_GAP + D12_VENDOR_PAD_W,
            "centre_spacing_delta_mm": centres - (D12_VENDOR_GAP + D12_VENDOR_PAD_W),
            "pad_delta_mm": [left["w_mm"] - D12_VENDOR_PAD_W,
                             left["h_mm"] - D12_VENDOR_PAD_H],
            "verdict": "COMPATIBLE_WITHIN_0P1_MM_NOT_THE_VENDOR_LAND",
            "first_article_check": "measure the solder joint on the first built "
                                   "board; the pad is 0.35 mm taller and 0.05 mm "
                                   "wider than the recommendation",
        },
        "worst_case_current": {
            "path": "D2 from OCD via IN+ into the internal rail V5I while J1.1 is "
                    "open; D3 blocks the same current from reaching the connector",
            "ifsm_rating_a": 0.6,
            "note": "surge, not continuous; the continuous path is bounded by the "
                    "divider (~0.44 mA at the design maximum), so the diode "
                    "current is not the stress -- the rail state below 2.7 V is "
                    "(see backfeed)",
        },
        "qualified": False,
        "open_items": [
            "the SOD-123 vendor land is not the footprint in use; the difference "
            "is inside 0.1 mm on centres but the pads are larger",
            "the backfed rail V5I is not characterised in hardware: D3 keeps it "
            "away from the connector and from R7, but the state below 2.7 V is "
            "unspecified, so the bench matrix (BF-03..BF-08) is unexecuted",
            "no temperature derating is applied to the 230 mW total dissipation",
        ],
    }


def report(ps: list[Part]) -> dict:
    nets: dict[str, list[str]] = {}
    for part in ps:
        for num, net in part.nets.items():
            nets.setdefault(net, []).append(f"{part.ref}.{num}")
    return {
        "kind": "TLV3501_FAST_OVERCURRENT_ECO_MODULE",
        "evidence_level": "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE",
        "hardware_built": False,
        "fabrication_approved": False,
        "part_instances": len(ps),
        "physical_parts": len([p for p in ps if not p.ref.startswith("#")]),
        "nets": len(nets),
        "net_map": {k: sorted(v) for k, v in sorted(nets.items())},
        "threshold": divider(),
        "common_mode": common_mode(),
        "delay": delay(),
        "system_delay": system_delay(),
        "supply": supply(),
        "backfeed": backfeed(),
        "backfeed_verification": verification(),
        "d12_selection": d12_selection(),
        "d0_connection": [
            "J1.1 V5 -> D0 V5 (bench 5 V rail)",
            "J1.2 PGND -> D0 PGND",
            "J1.3 OCD -> D0 R8/OCD node (the burden, before R9)",
            "J1.4 FAST_EXT_N -> D0 J10.4 ONLY; U11F inverts before U19 OR with legacy FAST_TRIP",
        ],
        "observations": observations(),
        "limits": [
            "module only; the CT, rectifier and burden stay on D0",
            "the system stop is NOT set by this comparator: the SR branch waits for REG to "
            "fall through UVLO, so the whole-machine incomplete estimate is quoted in system_delay",
            "D0's CD4013 latch propagation is not modelled, so system_delay totals are floors",
            "the module rail is isolated by D3, but the isolated rail can still be "
            "backfed through D2; its state below 2.7 V is unspecified and the bench "
            "matrix that would pin it down is UNEXECUTED",
            "the LM4040D25IDBZR minimum operating current is unverified, so the "
            "low-supply corner is not characterised",
            "a clean ERC only says the drawing agrees with itself",
        ],
    }


# ------------------------------------------------------------------ driver
def instance(part: Part, symbols: dict[str, str], labels: list[str]) -> str:
    tips = pin_tips(symbols[part.lib])
    on_board = "no" if part.ref.startswith("#") else "yes"
    lines = [
        "\t(symbol",
        f'\t\t(lib_id "{part.lib}")',
        f"\t\t(at {part.x:g} {part.y:g} 0)",
        f"\t\t(unit {part.unit}) (body_style 1)",
        f"\t\t(exclude_from_sim no) (in_bom {on_board}) (on_board {on_board}) "
        f"(in_pos_files {on_board})",
        f'\t\t(dnp {"yes" if part.dnp else "no"})',
        f'\t\t(uuid "{uid(part.ref, "symbol")}")',
        f'\t\t(property "Reference" "{part.ref}" (at {part.x:g} {part.y - 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Value" "{part.value}" (at {part.x:g} {part.y + 12:g} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Footprint" "{part.footprint}" (at {part.x:g} {part.y:g} 0) '
        '(hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Datasheet" "" (at {part.x:g} {part.y:g} 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t(property "Description" "{part.note}" (at {part.x:g} {part.y:g} 0) '
        '(hide yes) (show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
    ]
    for num in sorted(part.nets, key=int):
        lines.append(f'\t\t(pin "{num}" (uuid "{uid(part.ref, num)}"))')
    lines.append("\t)")
    for num, net in part.nets.items():
        px, py = tips[num]
        labels.append(
            f'\t(label "{net}" (at {part.x + px:g} {part.y - py:g} 0) '
            f'(effects (font (size 1.016 1.016))) '
            f'(uuid "{uid(part.ref, num, "label")}"))')
    return "\n".join(lines)


def schematic(symbols: dict[str, str], parts_: list[Part]) -> str:
    labels: list[str] = []
    instances = [instance(part, symbols, labels) for part in parts_]
    kept: dict[tuple[str, float, float], str] = {}
    for text in labels:
        at = text.split("(at ", 1)[1].split(")", 1)[0]
        net = text.split('"')[1]
        key = (net, *[round(float(v), 3) for v in at.split()[:2]])
        kept.setdefault(key, text)
    body = "\n".join(symbols[k] for k in sorted(symbols))
    return f"""(kicad_sch
\t(version 20260101)
\t(generator "make_fast_oc_eco.py")
\t(generator_version "10.0")
\t(uuid "{uid("root")}")
\t(paper "A4")
\t(title_block
\t\t(title "TLV3501 fast-overcurrent ECO module")
\t\t(date "2026-11-04")
\t\t(rev "A")
\t\t(comment 1 "Taps the CT burden directly; replaces the ~128 us filtered LM393 path.")
\t\t(comment 2 "Active-low output to D0 J10.4 ONLY; receiver inverter plus OR.")
\t\t(comment 3 "Generated by tools/make_fast_oc_eco.py.")
\t)
\t(lib_symbols
{body}
\t)
{chr(10).join(instances)}
{chr(10).join(kept.values())}
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""


def write_libs(symbols: dict[str, str]) -> None:
    block = symbols["FASTOC:LM4040"].replace(
        '(symbol "FASTOC:LM4040"', '(symbol "LM4040"', 1)
    text = ('(kicad_symbol_lib (version 20241209) (generator "make_fast_oc_eco.py")\n'
            + block[block.index("("):] + "\n)\n")
    (OUT / "FASTOC.kicad_sym").write_text(text, encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        '(sym_lib_table\n\t(version 7)\n'
        '\t(lib (name "FASTOC")(type "KiCad")(uri "${KIPRJMOD}/FASTOC.kicad_sym")'
        '(options "")(descr ""))\n)\n', encoding="utf-8")


def bom(parts_: list[Part]) -> None:
    path = OUT / "BOM.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Reference", "Value", "Footprint", "Rating", "Note", "DNP",
                    "MPN", "MPN_Source", "LCSC", "Qty"])
        for part in parts_:
            if part.ref.startswith("#"):
                continue
            w.writerow([part.ref, part.value, part.footprint, part.rating, part.note,
                        "yes" if part.dnp else "", part.mpn, part.mpn_source, "", 1])
    print(f"wrote {path}")


def project_file() -> str:
    """The one project file this directory has, shared by the schematic and the board.

    Both generators live beside one ``fast_oc.kicad_pro``; if each wrote its own
    version, whichever ran last would decide whether DRC enforces
    ``missing_courtyard`` (KiCad ignores that check by default, so a board with
    no courtyards at all would report "0 violations").  The board generator
    therefore reuses this function rather than emitting a second copy.
    """
    return json.dumps({
        "board": {"design_settings": {"rule_severities": {"missing_courtyard": "error"}}},
        "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "fast_oc.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def check() -> None:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: ERC and netlist export cannot be reproduced")
    sch = OUT / "fast_oc.kicad_sch"
    (OUT / "fast_oc.kicad_pro").write_text(project_file(), encoding="utf-8")
    subprocess.run([str(cli), "sch", "export", "netlist", str(sch),
                    "-o", str(OUT / "fast_oc.net")], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", str(sch),
                    "-o", str(OUT / "erc.rpt")], check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=True)
    violations = erc_violations(OUT / "erc.json", newer_than=sch)
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = build_symbols()
    ps = [snap(p) for p in parts()]
    validate(ps, symbols)
    validate_no_coincident_tips(ps, symbols)
    write_libs(symbols)
    path = OUT / "fast_oc.kicad_sch"
    path.write_text(schematic(symbols, ps), encoding="utf-8")
    print(f"wrote {path}")
    bom(ps)
    (OUT / "fast_oc.json").write_text(
        json.dumps(report(ps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'fast_oc.json'}")
    sd = system_delay()
    print(f"module delay {sd['detection_module_s'] * 1e6:.2f} us + decode/latch "
          f"{sd['common_logic_s'] * 1e6:.2f} us; whole-machine incomplete estimate "
          f"{sd['system_floor_s'] * 1e6:.1f} us (slowest branch: {sd['slowest_branch']}), "
          f"{sd['system_improvement_factor']:.1f}x vs the filtered path")
    if args.check:
        check()


if __name__ == "__main__":
    main()
