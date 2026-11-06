"""Generate the single-pair UCC24624 SR fault-shutdown validation board.

Why this board exists
---------------------
The D0 ten-gate bench uses UCC27524 push-pull drivers into dummy gate
capacitors.  It validates logic, not the real SR controller.  The roadmap of
2026-11-04 therefore asks for one *real* pair -- a UCC24624, two real SR
MOSFETs and a fault interface -- before the four groups are copied.

The board is deliberately built to answer three questions with measurements,
not with a behavioural model:

1. When a fault asserts, who pulls VG down, and how fast?
   The UCC24624 has no enable pin.  Its gate outputs are only guaranteed low
   in standby (which needs 7.5 ms of detection) or after REG UVLO.  The board
   provides a REG crowbar as the primary shutdown and leaves the VG clamp as a
   DNP option so its contention can be measured instead of assumed.  The
   crowbar delay is quoted at the 3.63 V turn-off threshold (the slow end) and
   is labelled an estimate: the regulator keeps sourcing; AO3400A has been
   selected, but its 3 V gate drive and pulse capability remain unverified.

2. Is cutting VDD sufficient?
   JP1 removes VDD while the bias supply stays alive.  The board's JSON puts
   the resulting discharge time next to the crowbar time; the answer is
   arithmetic (11.1 uF at ~1.1 mA is >100 ms), not opinion.

3. Where does the SR gate current return?
   VSS is a separate net from PGND and is tied to SR_SRC by R1.  The gate loop
   is therefore measurable: REG -> VG -> Rg -> gate -> Rgs -> SR_SRC -> R1 ->
   PGND.  A clamp tied to PGND is on the driver's return, not the MOSFET's
   source, and the 10 mV shunt drop is visible between them.

What this board is NOT
----------------------
It is a low-energy validation board (<=10 A, <=5 V output).  It cannot carry
100 A and it has no thermal model.  ``hardware_built`` and
``fabrication_approved`` are false in the report.  A clean ERC only says the
drawing agrees with itself.

The schematic is net-label first, the same convention as the control board:
every pin gets a local label with its net name.  That is real KiCad
connectivity (checked with ``kicad-cli sch export netlist``) and keeps one
component table as the single source of truth for schematic, netlist and BOM.

Usage:
    python tools/make_sr_fault_board.py
    python tools/make_sr_fault_board.py --check   # netlist + ERC + report
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from main_board_mechanical import find_kicad_cli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "sr_fault_validation"
NS = uuid.UUID("8d3f5c21-7a4e-4b96-9e2d-1c5a7f0b3e64")


def kicad_cli() -> Path | None:
    """Locate ``kicad-cli`` without hardcoding a username (issue #11)."""
    return find_kicad_cli()


def symbol_libs() -> Path:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found; set KICAD_CLI to regenerate symbols")
    return cli.parent.parent / "share" / "kicad" / "symbols"


# ------------------------------------------------------------------ evidence
# Every number below is copied from a datasheet in ``references/datasheets``.
# The test recomputes the derived quantities from these constants, so a typo
# in one of them changes the report and fails the test rather than hiding.
UCC = "references/datasheets/ucc24624.txt"
BSC = "references/datasheets/bsc010n04ls6.txt"

# UCC24624, Electrical Characteristics (page 6) unless noted.
VREG_TYP = 11.0            # V, REG regulation level
VREG_MIN = 9.9
VREG_MAX = 11.9
# REG UVLO turn-off threshold: 3.63 / 4.0 / 4.25 V (min/typ/max).
# The design delay has to cover a part that lets go at the *lowest* threshold,
# which is the slowest discharge; using VREGOFF_MAX made the crowbar look
# ~1.5 us faster than a low-threshold device can deliver (2026-11-05 review).
VREGOFF_MIN = 3.63
VREGOFF_TYP = 4.0
VREGOFF_MAX = 4.25
VREGON_MAX = 4.8           # V, REG UVLO turn-on threshold (max)
# REG current limit: 41 / 60 / 95 mA at VVDD = 12 V, VREG = 8 V.  It is not a
# guaranteed upper bound over the whole discharge, so it is used only as a
# constant-current sensitivity, never as the design delay.
IREGLIM_MAX_A = 95e-3
RVG_PU_TYP = 6.5           # ohm, VG pull-up resistance
RVG_PD_TYP = 0.9           # ohm, VG pull-down resistance
IVG_SRC_TYP = 1.5          # A, VG maximum source current
IVG_SNK_TYP = 4.0          # A, VG maximum sink current
VGHI_TYP = 10.9            # V, VG high clamp level
IVDD_RUN_MAX = 1.5e-3      # A, VDD current in run mode (max)
IVDD_STBY_TYP = 180e-6     # A, VDD current in standby mode
TSTBY_DET_MIN_S = 5.5e-3   # s, standby detection (0.5 ms per the datasheet's
                           # 7.5 ms typ; min taken as the earliest)
VTHVGON_TYP = -0.265       # V, SR turn-on threshold
VTHVGOFF_TYP = 0.0105      # V, SR turn-off threshold
IVS_OFFSET_TYP = 330e-6    # A, VSS offset current for threshold adjustment
VGUV_TYP = 0.020           # V, VG low when VDD is low (at 25 mA)

# BSC010N04LS6, Infineon datasheet in references/datasheets.
# The land pattern is device-specific: tools/bsc010n04ls6_land.py digitises
# Fig. 2 of this sheet (drain fingers as pads 5-8 on a common base), and
# tools/make_sr_fault_board_pcb.py turns it into dcx.pretty/BSC010N04LS6.
# The vendored Package_SON footprint numbers all five drain lands "5", which
# leaves pins 6-8 of this symbol with no pad of their own.
BSC_FOOTPRINT = "dcx:BSC010N04LS6"
VGS_TH_MIN = 1.3           # V, gate threshold (min) -- the off guarantee
VGS_TH_MAX = 2.3
CISS_TYP = 4.6e-9          # F, input capacitance
CISS_MAX = 6.0e-9
QG_TYP_10V = 67e-9         # C, total gate charge 0..10 V
QG_TYP_4V5 = 32e-9
RG_INT = 1.0               # ohm, internal gate resistance

# Board choices that are design parameters, not datasheet facts.
R_GATE = 2.2               # ohm, same as the main board's external gate resistor
R_GS = 10e3                # ohm, gate-source pulldown
R_CROWBAR = 4.7            # ohm, series resistor in the REG crowbar
RDS_BOM_TARGET = 0.1       # ohm, the ceiling the Q41 BOM line quotes; selection beats it
C_REG_BYPASS = 2.2e-6      # F, C4
C_REG_HF = 100e-9          # F, C5
C1_F = 10e-6               # C1
C2_F = 1e-6                # C2
C3_F = 100e-9              # C3
C_VDD_TOTAL = C1_F + C2_F + C3_F
VDD_NOM = 15.0             # V, bench bias
RDS_ON_CROWBAR = 1.5       # ohm, placeholder for a 2N7002-class NMOS
RDS_SELECTED = 0.048       # ohm, AO3400A max at VGS=2.5 V / 25 C, datasheet p.2
R_CROWBAR_GATE = 100.0     # ohm, R43 between FAULT_G and the Q41 gate
RDS_CLAMP_TABLE = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 1.5)

# AO3400A (AOS, Rev 3.1) -- the part now named on the Q41 line.  Its datasheet
# is in references/, so the MPN is traceable; the numbers below are transcribed
# from it, not measured on this board.
Q41_MPN = "AO3400A"
Q41_MPN_SOURCE = "references/datasheets/ao3400a.txt"
Q41_RDS_MAX = {10.0: 0.0265, 4.5: 0.032, 2.5: 0.048}   # ohm, datasheet table
Q41_VGS_TH_MAX = 1.45      # V
Q41_ID_A = 5.7             # A, 25 C
Q41_IDM_A = 30.0           # A, pulsed
Q41_CISS_TYP = 630e-12     # F
Q41_QGD_TYP = 1.8e-9       # C
Q41_RG_MAX = 4.5           # ohm, internal gate resistance
R_FAULT_PULLDOWN = 10e3    # ohm, R41 from the fault gate to PGND
FAULT_RC_R = R_FAULT_PULLDOWN
FAULT_RC_C = 1e-9          # F, input filter (C40)
FAULT_RC_S = FAULT_RC_R * FAULT_RC_C
R_FAULT_SERIES = 1e3       # ohm, R40 into the clamp
R_STATUS_PULLDOWN = 100e3  # ohm, R42 on the open-drain status output
EXTERNAL_PULLUP_V = 3.3    # V, assumed status pull-up level on the harness

# A net tied to this is emitted as a no-connect marker, not a label.
NC = "#NC"


# ------------------------------------------------------------------ plumbing
@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    x: float
    y: float
    angle: int
    etype: str = "passive"


@dataclass(frozen=True)
class Part:
    ref: str
    lib: str
    value: str
    footprint: str
    x: float
    y: float
    nets: dict[str, str]
    rating: str = ""
    note: str = ""
    dnp: bool = False
    unit: int = 1
    source: str = "DESIGN_PROPOSAL"
    # An orderable code is only written when a datasheet this repository holds
    # carries it; ``mpn_source`` says which file.  Everything else stays
    # TO_SELECT, because a blank cell reads as "someone will fill it in" while
    # a fabricated MPN reads as a part that exists.
    mpn: str = ""
    mpn_source: str = "TO_SELECT"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def block_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    i = start
    while i < len(text):
        ch = text[i]
        if ch == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise SystemExit("unbalanced s-expression")


def extract_symbol(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    key = f'(symbol "{name}"'
    start = text.find(key)
    if start < 0:
        raise SystemExit(f"{name} not found in {path}")
    return text[start:block_end(text, start)]


def pin_numbers(block: str) -> list[str]:
    out: list[str] = []
    marker = '(number "'
    i = 0
    while True:
        i = block.find(marker, i)
        if i < 0:
            return out
        j = block.find('"', i + len(marker))
        out.append(block[i + len(marker):j])
        i = j + 1


def pin_tips(block: str) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    i = 0
    while True:
        i = block.find("(pin ", i)
        if i < 0:
            return out
        j = block.find('(number "', i)
        at = block.find("(at ", i)
        if j < 0 or at < 0:
            return out
        num = block[j + len('(number "'):block.find('"', j + len('(number "'))]
        nums = block[at + 4:block.find(")", at)].split()
        out[num] = (float(nums[0]), float(nums[1]))
        i = j + 1


def custom_symbol(name: str, pins: list[Pin], width: float, height: float,
                  reference: str = "U", footprint: str = "") -> str:
    lines = [
        f'\t\t(symbol "{name}"',
        '\t\t\t(pin_names (offset 0.508))',
        '\t\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
        f'\t\t\t(property "Reference" "{reference}" (at 0 {height / 2 + 2.54:.3f} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(property "Value" "{name.split(":")[-1]}" (at 0 {-height / 2 - 2.54:.3f} 0) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(property "Footprint" "{footprint}" (at 0 0 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        '\t\t\t(property "Datasheet" "" (at 0 0 0) (hide yes) (show_name no) '
        '(do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        '\t\t\t(property "Description" "" (at 0 0 0) (hide yes) (show_name no) '
        '(do_not_autoplace no) (effects (font (size 1.27 1.27))))',
        f'\t\t\t(symbol "{name.split(":")[-1]}_0_1"',
        f'\t\t\t\t(rectangle (start {-width / 2:.3f} {height / 2:.3f}) '
        f'(end {width / 2:.3f} {-height / 2:.3f}) '
        '(stroke (width 0.254) (type default)) (fill (type background)))',
        '\t\t\t)',
        f'\t\t\t(symbol "{name.split(":")[-1]}_1_1"',
    ]
    for p in pins:
        lines.append(
            f'\t\t\t\t(pin {p.etype} line (at {p.x:.3f} {p.y:.3f} {p.angle}) (length 2.54) '
            f'(name "{p.name}" (effects (font (size 1.27 1.27)))) '
            f'(number "{p.number}" (effects (font (size 1.27 1.27)))))'
        )
    lines += ["\t\t\t)", "\t\t)", ""]
    return "\n".join(lines)


STANDARD = {
    "Device:R": ("Device.kicad_sym", "R"),
    "Device:C": ("Device.kicad_sym", "C"),
    "Device:D_Schottky": ("Device.kicad_sym", "D_Schottky"),
    "Device:D_TVS": ("Device.kicad_sym", "D_TVS"),
    "Device:D_Zener": ("Device.kicad_sym", "D_Zener"),
    "Device:Fuse": ("Device.kicad_sym", "Fuse"),
    "Transistor_FET:Q_NMOS_GSD": ("Transistor_FET.kicad_sym", "Q_NMOS_GSD"),
    "Connector_Generic:Conn_01x02": ("Connector_Generic.kicad_sym", "Conn_01x02"),
    "Connector_Generic:Conn_01x03": ("Connector_Generic.kicad_sym", "Conn_01x03"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def rename_symbol(block: str, lib_id: str) -> str:
    lib, name = lib_id.split(":", 1)
    head = block[:block.index("(") + 1]
    body = block[block.index("("):]
    body = body.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
    return head + body if head.strip() else body


def build_symbols() -> dict[str, str]:
    # Frozen embedded symbols are sufficient for offline consistency checks,
    # NOT a fresh KiCad ERC or a manufacturer terminal audit.
    cli = kicad_cli()
    libs = symbol_libs() if cli is not None else None
    source_schematic = OUT / "sr_fault_validation.kicad_sch"
    if libs is None and not source_schematic.is_file():
        raise SystemExit("KiCad symbols unavailable: install kicad-cli or provide the committed schematic")
    symbols: dict[str, str] = {}
    for lib_id, (lib, name) in STANDARD.items():
        if libs is None:
            block = extract_symbol(source_schematic, lib_id)
        else:
            block = extract_symbol(libs / lib, name)
            block = block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)
        symbols[lib_id] = block
    ucc = [
        Pin("1", "VG1", 7.62, 2.54, 180, "output"),
        Pin("2", "PGND", 0, -8.89, 90, "power_in"),
        Pin("3", "REG", 0, 8.89, 270, "power_out"),
        Pin("4", "VD1", -7.62, 2.54, 0, "input"),
        Pin("5", "VSS", -7.62, 0, 0, "input"),
        Pin("6", "VD2", -7.62, -2.54, 0, "input"),
        Pin("7", "VDD", 7.62, 0, 180, "power_in"),
        Pin("8", "VG2", 7.62, -2.54, 180, "output"),
    ]
    symbols["UCC24624:UCC24624"] = custom_symbol(
        "UCC24624:UCC24624", ucc, 10.16, 12.7, "U",
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
    bsc = [
        Pin("1", "S", 0, -7.62, 90, "passive"),
        Pin("2", "S", 0, -7.62, 90, "passive"),
        Pin("3", "S", 0, -7.62, 90, "passive"),
        Pin("4", "G", -7.62, 0, 0, "input"),
        Pin("5", "D", 0, 7.62, 270, "passive"),
        Pin("6", "D", 0, 7.62, 270, "passive"),
        Pin("7", "D", 0, 7.62, 270, "passive"),
        Pin("8", "D", 0, 7.62, 270, "passive"),
    ]
    symbols["SR:BSC010N04LS6"] = custom_symbol(
        "SR:BSC010N04LS6", bsc, 7.62, 10.16, "Q", BSC_FOOTPRINT)
    return symbols


# ------------------------------------------------------------------ parts
def bias_parts() -> list[Part]:
    block = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    hdr = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    return [
        Part("J1", "Connector_Generic:Conn_01x02", "VBIAS 15V", block, 30, 55,
             {"1": "VBIAS", "2": "PGND"}, "15 V, 0.5 A",
             "bias input; polarity marked on the silk"),
        Part("F1", "Device:Fuse", "0.5A", "Fuse:Fuse_1206_3216Metric", 52, 45,
             {"1": "VBIAS", "2": "VIN_F"}, "0.5 A", "bias fuse"),
        Part("D1", "Device:D_TVS", "SMBJ15A", "Diode_SMD:D_SMB", 52, 68,
             {"1": "VIN_F", "2": "PGND"}, "15 V standoff", "bias TVS"),
        Part("D2", "Device:D_Schottky", "SS34", "Diode_SMD:D_SMA", 72, 45,
             {"1": "VDD_IN", "2": "VIN_F"}, "40 V 3 A",
             "reverse-polarity block; pin 1 is the cathode"),
        Part("JP1", "Connector_Generic:Conn_01x02", "VDD CUT", hdr, 92, 45,
             {"1": "VDD_IN", "2": "VDD"},
             note="shunt fitted = VDD connected; remove to test a VDD-only cut"),
        Part("C1", "Device:C", "10uF/35V", "Capacitor_SMD:C_1210_3225Metric",
             104, 38, {"1": "VDD", "2": "PGND"}, "35 V X7R", ""),
        Part("C2", "Device:C", "1uF/35V", "Capacitor_SMD:C_0805_2012Metric",
             116, 38, {"1": "VDD", "2": "PGND"}, "35 V X7R", ""),
        Part("C3", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric",
             128, 38, {"1": "VDD", "2": "PGND"}, "50 V X7R", "at pin 7"),
        Part("#FLG1", "power:PWR_FLAG", "PWR_FLAG", "", 30, 30,
             {"1": "VBIAS"}, "", "ERC: bias input is a source"),
        Part("#FLG2", "power:PWR_FLAG", "PWR_FLAG", "", 50, 30,
             {"1": "PGND"}, "", "ERC: return is a source"),
        Part("#FLG3", "power:PWR_FLAG", "PWR_FLAG", "", 70, 30,
             {"1": "VDD_IN"}, "", "ERC: post-diode node is a source"),
        Part("#FLG4", "power:PWR_FLAG", "PWR_FLAG", "", 92, 30,
             {"1": "VDD"}, "", "ERC: the jumper separates VDD from VDD_IN"),
    ]


def controller_parts() -> list[Part]:
    return [
        Part("U1", "UCC24624:UCC24624", "UCC24624DR",
             "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 170, 95,
             {"1": "VG1", "2": "PGND", "3": "REG", "4": "VD1", "5": "VSS",
              "6": "VD2", "7": "VDD", "8": "VG2"}, "230 V VD pins",
             "SR controller, SOIC-8",
             mpn="UCC24624DR",
             mpn_source="references/datasheets/ucc24624.txt"),
        Part("C4", "Device:C", "2.2uF/25V", "Capacitor_SMD:C_1206_3216Metric",
             170, 70, {"1": "REG", "2": "PGND"}, "25 V X7R",
             "REG bypass, <=1 cm from pin 3"),
        Part("C5", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric",
             184, 70, {"1": "REG", "2": "PGND"}, "50 V X7R", "REG HF bypass"),
        Part("R1", "Device:R", "0R", "Resistor_SMD:R_0805_2012Metric",
             205, 95, {"1": "VSS", "2": "SR_SRC"}, "<=212 R option",
             "Roffset: VTHOFF = 10.5 mV + 330 uA * R; 0R keeps the datasheet value"),
        Part("R2", "Device:R", "0R", "Resistor_SMD:R_0603_1608Metric",
             215, 78, {"1": "VD1", "2": "SEC_A"}, "100 R option",
             "VD1 series link; 100R only if drain ringing demands it"),
        Part("R3", "Device:R", "0R", "Resistor_SMD:R_0603_1608Metric",
             215, 112, {"1": "VD2", "2": "SEC_B"}, "100 R option", "VD2 series link"),
    ]


def power_parts() -> list[Part]:
    block = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm"
    load = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
    return [
        Part("Q1", "SR:BSC010N04LS6", "BSC010N04LS6",
             BSC_FOOTPRINT, 260, 78,
             {"1": "SR_SRC", "2": "SR_SRC", "3": "SR_SRC", "4": "G1",
              "5": "SEC_A", "6": "SEC_A", "7": "SEC_A", "8": "SEC_A"},
             "40 V 1.0 mR", "SR1; source Kelvin to VSS",
             mpn="BSC010N04LS6",
             mpn_source="references/datasheets/bsc010n04ls6.txt"),
        Part("Q2", "SR:BSC010N04LS6", "BSC010N04LS6",
             BSC_FOOTPRINT, 260, 138,
             {"1": "SR_SRC", "2": "SR_SRC", "3": "SR_SRC", "4": "G2",
              "5": "SEC_B", "6": "SEC_B", "7": "SEC_B", "8": "SEC_B"},
             "40 V 1.0 mR", "SR2; source Kelvin to VSS",
             mpn="BSC010N04LS6",
             mpn_source="references/datasheets/bsc010n04ls6.txt"),
        Part("Rg1", "Device:R", "2.2R", "Resistor_SMD:R_0805_2012Metric",
             232, 68, {"1": "VG1", "2": "G1"}, "1/8 W", "gate resistor, main-board value"),
        Part("Rg2", "Device:R", "2.2R", "Resistor_SMD:R_0805_2012Metric",
             232, 148, {"1": "VG2", "2": "G2"}, "1/8 W", "gate resistor, main-board value"),
        Part("Rgs1", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
             246, 60, {"1": "G1", "2": "SR_SRC"}, "1/10 W", "gate-source pulldown"),
        Part("Rgs2", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
             246, 156, {"1": "G2", "2": "SR_SRC"}, "1/10 W", "gate-source pulldown"),
        Part("CGL1", "Device:C", "6.8nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             234, 56, {"1": "G1", "2": "SR_SRC"}, "50 V", "gate-load test", True),
        Part("CGL2", "Device:C", "6.8nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             234, 160, {"1": "G2", "2": "SR_SRC"}, "50 V", "gate-load test", True),
        Part("Rsh1", "Device:R", "1mR 1%", "Resistor_SMD:R_2512_6332Metric",
             286, 108, {"1": "SR_SRC", "2": "PGND"}, "2 W",
             "return current sense; 10 A -> 10 mV"),
        Part("Rsn1", "Device:R", "10R DNP", "Resistor_SMD:R_0603_1608Metric",
             274, 56, {"1": "SEC_A", "2": "SN1"}, "1/10 W", "RC snubber", True),
        Part("Csn1", "Device:C", "1nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             286, 56, {"1": "SN1", "2": "SR_SRC"}, "50 V", "RC snubber", True),
        Part("Rsn2", "Device:R", "10R DNP", "Resistor_SMD:R_0603_1608Metric",
             274, 160, {"1": "SEC_B", "2": "SN2"}, "1/10 W", "RC snubber", True),
        Part("Csn2", "Device:C", "1nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             286, 160, {"1": "SN2", "2": "SR_SRC"}, "50 V", "RC snubber", True),
        Part("J3", "Connector_Generic:Conn_01x04", "SEC A/CT/B",
             block, 330, 175,
             {"1": "SEC_A", "2": "VOUT", "3": "SEC_B", "4": "PGND"},
             "20 V peak, 10 A", "isolated low-voltage centre-tapped source"),
        Part("C6", "Device:C", "100uF/6.3V", "Capacitor_SMD:C_1210_3225Metric",
             318, 95, {"1": "VOUT", "2": "PGND"}, "6.3 V X5R", ""),
        Part("C7", "Device:C", "10uF/10V", "Capacitor_SMD:C_0805_2012Metric",
             330, 95, {"1": "VOUT", "2": "PGND"}, "10 V X7R", ""),
        Part("J2", "Connector_Generic:Conn_01x02", "LOAD 0.2-2R", load, 350, 110,
             {"1": "VOUT", "2": "PGND"}, "2 A max", "load / electronic load"),
        Part("R5", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
             110, 195, {"1": "FORCE1", "2": "VD1"}, "1/10 W", "VD1 injection"),
        Part("R6", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
             126, 215, {"1": "FORCE2", "2": "VD2"}, "1/10 W", "VD2 injection"),
        Part("JP2", "Connector_Generic:Conn_01x02", "FORCE1 low",
             "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 90, 195,
             {"1": "FORCE1", "2": "PGND"}, note="shunt = force VD1 low"),
        Part("JP3", "Connector_Generic:Conn_01x02", "FORCE2 low",
             "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 106, 215,
             {"1": "FORCE2", "2": "PGND"}, note="shunt = force VD2 low"),
    ]


def fault_parts() -> list[Part]:
    """The fault interface: active-high input, REG crowbar, optional VG clamps.

    Q41 is the primary shutdown.  Q42/Q43 are DNP because a clamp that can hold
    VG below the SR FET's 1.3 V threshold has to sink ~1.5 A, and the UCC24624
    would dissipate 12-18 W inside its own output stage trying to source it.
    The footprints are present so that contention can be measured once, on
    purpose, instead of being argued about.
    """
    hdr = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
    return [
        Part("J4", "Connector_Generic:Conn_01x03", "FAULT/STATUS", hdr, 40, 260,
             {"1": "FAULT_IN", "2": "PGND", "3": "FAULT_N"},
             "3.3/5 V CMOS or open-drain, active high",
             "pin 1 = fault request, pin 3 = open-drain status"),
        Part("R40", "Device:R", f"{R_FAULT_SERIES / 1e3:g}k", "Resistor_SMD:R_0603_1608Metric",
             58, 250, {"1": "FAULT_IN", "2": "FAULT_G"}, "1/10 W",
             "series limit into the clamp"),
        Part("D40", "Device:D_Zener", "5V1", "Diode_SMD:D_SOD-123",
             58, 272, {"1": "FAULT_G", "2": "PGND"}, "5.1 V",
             "input clamp; two-pad land so the cathode (pad 1, the banded end) "
             "actually reaches FAULT_G -- an SOT-23 land left pad 3, which is "
             "where a BZX84 puts its cathode, as spare copper.  MPN TO_SELECT: "
             "no 5.1 V zener datasheet is in the repository"),
        Part("R41", "Device:R", f"{R_FAULT_PULLDOWN / 1e3:g}k", "Resistor_SMD:R_0603_1608Metric",
             74, 272, {"1": "FAULT_G", "2": "PGND"}, "1/10 W",
             "default = no fault (fail-open input); 10k * 1nF = 10 us input filter"),
        Part("C40", "Device:C", "1nF/16V", "Capacitor_SMD:C_0603_1608Metric",
             90, 272, {"1": "FAULT_G", "2": "PGND"}, "16 V X7R",
             "10 us; a 1 ms debounce would dominate every other delay"),
        Part("Q40", "Transistor_FET:Q_NMOS_GSD", "2N7002",
             "Package_TO_SOT_SMD:SOT-23", 74, 250, {"1": "FAULT_G", "2": "PGND", "3": "FAULT_N"},
             "60 V", "open-drain status: low while the fault is asserted",
             mpn="2N7002LT1G",
             mpn_source="references/datasheets/2n7002lt1g_onsemi_oem_parameters.txt"),
        Part("R42", "Device:R", f"{R_STATUS_PULLDOWN / 1e3:g}k", "Resistor_SMD:R_0603_1608Metric",
             90, 250, {"1": "FAULT_N", "2": "PGND"}, "1/10 W",
             "status default low; the external pull-up sees this 100k to PGND"),
        Part("R43", "Device:R", "100R", "Resistor_SMD:R_0603_1608Metric",
             58, 292, {"1": "FAULT_G", "2": "RC_G"}, "1/10 W", "crowbar gate resistor"),
        Part("Q41", "Transistor_FET:Q_NMOS_GSD", Q41_MPN,
             "Package_TO_SOT_SMD:SOT-23", 74, 292, {"1": "RC_G", "2": "PGND", "3": "REG_CROW"},
             "30 V, 5.7 A, IDM 30 A",
             f"REG crowbar; 3.0 V gate from a 3.3 V harness, Rds(on) <= "
             f"{Q41_RDS_MAX[2.5]:.3f} ohm at 2.5 V VGS (max, 25 C); absorbs "
             f"{crowbar_pulse()['fet_energy_j'] * 1e3:.3f} mJ per event; selected, not "
             f"qualified (see report q41_selection)", mpn=Q41_MPN, mpn_source=Q41_MPN_SOURCE),
        Part("R44", "Device:R", "4.7R 0.5W", "Resistor_SMD:R_1206_3216Metric",
             92, 292, {"1": "REG", "2": "REG_CROW"}, "0.5 W pulse",
             f"sets the discharge tau with Q41; {crowbar_pulse()['r44_energy_j'] * 1e3:.3f} mJ / "
             f"{crowbar_pulse()['r44_peak_power_w']:.1f} W peak per event "
             f"({crowbar_pulse()['r44_equivalent_pulse_width_s'] * 1e6:.1f} us equivalent), "
             f"single-pulse rating UNVERIFIED"),
        Part("R45", "Device:R", "100R", "Resistor_SMD:R_0603_1608Metric",
             58, 312, {"1": "FAULT_G", "2": "VC1_G"}, "1/10 W", "VG1 clamp gate resistor"),
        Part("Q42", "Transistor_FET:Q_NMOS_GSD", "NMOS clamp DNP",
             "Package_TO_SOT_SMD:SOT-23", 74, 312, {"1": "VC1_G", "2": "PGND", "3": "VC1_D"},
             "30 V", "optional VG1 clamp; contention test only", True),
        Part("R47", "Device:R", "0R DNP", "Resistor_SMD:R_0805_2012Metric",
             92, 312, {"1": "VC1_D", "2": "VG1"}, "1/4 W",
             "clamp link: fitting this removes U1's ability to hold VG1 high", True),
        Part("R46", "Device:R", "100R", "Resistor_SMD:R_0603_1608Metric",
             58, 332, {"1": "FAULT_G", "2": "VC2_G"}, "1/10 W", "VG2 clamp gate resistor"),
        Part("Q43", "Transistor_FET:Q_NMOS_GSD", "NMOS clamp DNP",
             "Package_TO_SOT_SMD:SOT-23", 74, 332, {"1": "VC2_G", "2": "PGND", "3": "VC2_D"},
             "30 V", "optional VG2 clamp; contention test only", True),
        Part("R48", "Device:R", "0R DNP", "Resistor_SMD:R_0805_2012Metric",
             92, 332, {"1": "VC2_D", "2": "VG2"}, "1/4 W", "clamp link", True),
    ]


def test_points() -> list[Part]:
    tps = [
        ("TP1", "VDD_IN"), ("TP2", "VDD"), ("TP3", "REG"), ("TP4", "REG_CROW"),
        ("TP5", "VG1"), ("TP6", "VG2"), ("TP7", "G1"), ("TP8", "G2"),
        ("TP9", "VD1"), ("TP10", "VD2"), ("TP11", "VSS"), ("TP12", "SR_SRC"),
        ("TP13", "SEC_A"), ("TP14", "SEC_B"), ("TP15", "VOUT"),
        ("TP16", "FAULT_IN"), ("TP17", "FAULT_G"), ("TP18", "FAULT_N"),
        ("TP19", "PGND"), ("TP20", "PGND"),
    ]
    return [Part(ref, "Connector:TestPoint", net, "TestPoint:TestPoint_Pad_D1.0mm",
                 30 + 15 * i, 360, {"1": net}, "1 mm pad",
                 "scope probe / Kelvin point")
            for i, (ref, net) in enumerate(tps)]


def parts() -> list[Part]:
    return (bias_parts() + controller_parts() + power_parts()
            + fault_parts() + test_points())


# ------------------------------------------------------------------ layout
def origin(part: Part) -> tuple[float, float]:
    return part.x, part.y


def pin_tip_positions(part: Part, symbols: dict[str, str]) -> dict[str, tuple[float, float]]:
    tips = pin_tips(symbols[part.lib])
    ox, oy = origin(part)
    return {num: (ox + x, oy - y) for num, (x, y) in tips.items()}


def validate(ps: list[Part], symbols: dict[str, str]) -> None:
    seen: set[str] = set()
    for part in ps:
        key = f"{part.ref}.{part.unit}" if part.unit != 1 else part.ref
        if key in seen:
            raise SystemExit(f"duplicate reference {key}")
        seen.add(key)
        if part.lib not in symbols:
            raise SystemExit(f"{part.ref}: unknown symbol {part.lib}")
        nums = pin_numbers(symbols[part.lib])
        if set(nums) != set(part.nets):
            raise SystemExit(f"{part.ref}: pins {nums} != nets {sorted(part.nets)}")
        for net in part.nets.values():
            if not net or " " in net:
                raise SystemExit(f"{part.ref}: bad net name {net!r}")


def validate_no_coincident_tips(ps: list[Part], symbols: dict[str, str]) -> None:
    """Two *different* parts may not land on one point.

    Pins of the same part may coincide: the SR symbol merges S1-S3 and D5-D8
    onto one graphic tip, which is normal for a power device.  Those pins are
    all on the same net, so the merged tip carries exactly one label.
    """
    seen: dict[tuple[float, float], tuple[str, str]] = {}
    for part in ps:
        for num, (x, y) in pin_tip_positions(part, symbols).items():
            key = (round(x, 3), round(y, 3))
            if key in seen:
                other_ref, other_net = seen[key]
                if other_ref != part.ref or other_net != part.nets[num]:
                    raise SystemExit(
                        f"{part.ref}.{num} shares a tip with {other_ref}")
                continue
            seen[key] = (part.ref, part.nets[num])


def nets_of(ps: list[Part]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for part in ps:
        for num, net in part.nets.items():
            out.setdefault(net, []).append(f"{part.ref}.{num}")
    return {k: sorted(v) for k, v in sorted(out.items())}


def instance(part: Part, symbols: dict[str, str], labels: list[str]) -> str:
    block = symbols[part.lib]
    tips = pin_tips(block)
    on_board = "no" if part.ref.startswith("#") else "yes"
    in_bom = "no" if part.ref.startswith("#") else "yes"
    lines = [
        "\t(symbol",
        f'\t\t(lib_id "{part.lib}")',
        f"\t\t(at {part.x:g} {part.y:g} 0)",
        f"\t\t(unit {part.unit}) (body_style 1)",
        f"\t\t(exclude_from_sim no) (in_bom {in_bom}) (on_board {on_board}) (in_pos_files {on_board})",
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
        f'\t\t(property "Description" "{part.note}" (at {part.x:g} {part.y:g} 0) (hide yes) '
        '(show_name no) (do_not_autoplace no) (effects (font (size 1.27 1.27))))',
    ]
    for num in sorted(part.nets, key=lambda s: int(s)):
        lines.append(f'\t\t(pin "{num}" (uuid "{uid(part.ref, num)}"))')
    lines.append("\t)")
    for num, net in part.nets.items():
        px, py = tips[num]
        ax, ay = part.x + px, part.y - py
        labels.append(
            f'\t(label "{net}" (at {ax:g} {ay:g} 0) '
            f'(effects (font (size 1.016 1.016))) (uuid "{uid(part.ref, num, "label")}"))'
        )
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
    inst = "\n".join(instances)
    lab = "\n".join(kept.values())
    return f"""(kicad_sch
\t(version 20260101)
\t(generator "make_sr_fault_board.py")
\t(generator_version "10.0")
\t(uuid "{uid("root")}")
\t(paper "A3")
\t(title_block
\t\t(title "UCC24624 single-pair SR fault-shutdown validation board")
\t\t(date "2026-11-04")
\t\t(rev "A")
\t\t(comment 1 "Low-energy, isolated secondary-equivalent test. NOT the 48 V main board.")
\t\t(comment 2 "Primary shutdown = REG crowbar. VG clamps are DNP contention tests.")
\t\t(comment 3 "Net-label schematic generated by tools/make_sr_fault_board.py.")
\t)
\t(lib_symbols
{body}
\t)
{inst}
{lab}
\t(sheet_instances
\t\t(path "/" (page "1"))
\t)
)
"""


def snap(part: Part) -> Part:
    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def write_libs(symbols: dict[str, str]) -> None:
    for lib, name in (("UCC24624", "UCC24624"), ("SR", "BSC010N04LS6")):
        key = f"{lib}:{name}"
        block = symbols[key].replace(f'(symbol "{key}"', f'(symbol "{name}"', 1)
        text = ('(kicad_symbol_lib (version 20241209) (generator "make_sr_fault_board.py")\n'
                + block[block.index("("):] + "\n)\n")
        (OUT / f"{lib}.kicad_sym").write_text(text, encoding="utf-8")
    (OUT / "sym-lib-table").write_text(
        '(sym_lib_table\n'
        '\t(version 7)\n'
        '\t(lib (name "UCC24624")(type "KiCad")(uri "${KIPRJMOD}/UCC24624.kicad_sym")'
        '(options "")(descr ""))\n'
        '\t(lib (name "SR")(type "KiCad")(uri "${KIPRJMOD}/SR.kicad_sym")'
        '(options "")(descr ""))\n'
        ')\n', encoding="utf-8")


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
    # ``missing_courtyard`` is IGNORED by default, so a board with no courtyards
    # at all reports "0 violations".  The PCB generator raises it to error; the
    # setting has to live in the project file because that is the only place
    # kicad-cli reads rule severities from.
    board = {"design_settings": {"rule_severities": {"missing_courtyard": "error"}}}
    return json.dumps({
        "board": board, "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "sr_fault_validation.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def erc_violations(path: Path | None = None, *, newer_than: Path | None = None) -> list[dict]:
    path = path or OUT / "erc.json"
    if not path.exists():
        return []
    if newer_than is not None and path.stat().st_mtime < newer_than.stat().st_mtime:
        return [{"severity": "error", "type": "stale_report",
                 "description": f"{path.name} is older than {newer_than.name}"}]
    data = json.loads(path.read_text(encoding="utf-8"))
    return [v for sheet in data.get("sheets", []) for v in sheet.get("violations", [])]


# ------------------------------------------------------------------ physics
def discharge_time(r_total: float, v_threshold: float) -> float:
    """RC discharge from VREG_TYP through ``r_total`` down to ``v_threshold``."""
    return (r_total * (C_REG_BYPASS + C_REG_HF)
            * math.log(VREG_TYP / v_threshold))


def discharge_time_with_injection(r_total: float, i_inject: float,
                                  v_threshold: float) -> float:
    """Same discharge against a constant current source feeding REG.

    ``t = RC ln[(V0 - IR)/(Vth - IR)]``; only valid while ``I*R < Vth``, and the
    datasheet's 95 mA is an 8 V condition, so this is a sensitivity bound.
    """
    ir = i_inject * r_total
    if ir >= v_threshold:
        raise ValueError(f"I*R = {ir:.3f} V does not leave the node below {v_threshold} V")
    return (r_total * (C_REG_BYPASS + C_REG_HF)
            * math.log((VREG_TYP - ir) / (v_threshold - ir)))


def crowbar() -> dict:
    """REG crowbar: stored energy, peak current, time constant, UVLO time.

    The delay is quoted at ``VREGOFF_MIN`` (3.63 V): a device that turns off at
    the lowest threshold is the slowest one, so that is the number the design
    has to cover.  None of these is a hardware worst case -- see ``worst_case``.
    """
    c = C_REG_BYPASS + C_REG_HF
    r = R_CROWBAR + RDS_SELECTED
    energy = 0.5 * c * VREG_TYP ** 2
    released = 0.5 * c * (VREG_TYP ** 2 - VREGOFF_MIN ** 2)
    tau = r * c
    t_uvlo = discharge_time(r, VREGOFF_MIN)
    scenarios = [
        {
            "label": label,
            "rds_on_ohm": rds,
            "r_total_ohm": R_CROWBAR + rds,
            "time_to_uvlo_s": discharge_time(R_CROWBAR + rds, VREGOFF_MIN),
            "time_to_uvlo_at_max_threshold_s": discharge_time(R_CROWBAR + rds, VREGOFF_MAX),
        }
        for label, rds in (
            ("R44 only, ideal clamp", 0.0),
            (f"Q41 {Q41_MPN} at 2.5 V VGS (selected, 25 C max)", RDS_SELECTED),
            ("Q41 at the BOM target", RDS_BOM_TARGET),
            ("Q41 placeholder (2N7002 class)", RDS_ON_CROWBAR),
        )
    ]
    return {
        "c_reg_f": c,
        "r_total_ohm": r,
        "stored_energy_j": energy,
        "energy_released_to_uvlo_j": released,
        "peak_current_a": VREG_TYP / r,
        "tau_s": tau,
        "time_to_uvlo_s": t_uvlo,
        "time_to_uvlo_at_max_threshold_s": discharge_time(r, VREGOFF_MAX),
        "time_to_uvlo_with_reg_current_limit_s":
            discharge_time_with_injection(r, IREGLIM_MAX_A, VREGOFF_MIN),
        "threshold_basis": {
            "turn_off_min_v": VREGOFF_MIN,
            "turn_off_typ_v": VREGOFF_TYP,
            "turn_off_max_v": VREGOFF_MAX,
            "design_uses": "turn_off_min_v: the lowest threshold is the slowest to reach",
        },
        "scenarios": scenarios,
        "resistor_share_j": released * R_CROWBAR / r,
        "fet_share_j": released * RDS_SELECTED / r,
        "fet_peak_a": VREG_TYP / r,
        "worst_case": {
            "is_worst_case": False,
            "reasons": [
                "the UCC24624 linear regulator keeps sourcing into REG while the "
                "crowbar pulls it down; the constant-current column is a "
                "sensitivity, not a guaranteed bound",
                "no component tolerance band is applied to R44 or the REG capacitors",
                f"Q41 is the selected {Q41_MPN}, but selection is not qualification: "
                "its Rds(on) is the datasheet max at 2.5 V VGS and 25 C, with no "
                "SOA curve at the turn-on crossing and no self-heating",
                "the discharge model starts with Q41 already on; the gate slewing "
                "through R43 delays the 11 V connection, so the quoted time is a floor",
                "turn-on propagation of Q41 and the UVLO-to-VG transient are not modelled",
            ],
        },
        "note": f"headline uses the selected {Q41_MPN} at its 2.5 V VGS maximum; "
                "the 1.5 ohm row is the old 2N7002-class placeholder and must not be "
                "quoted as the design number",
    }


def crowbar_pulse() -> dict:
    """Energy and power the crowbar puts into R44 and Q41, per event and per rate.

    The 1206's 0.5 W rating is a *continuous* rating.  At any plausible
    repetition rate the thermal average is microwatts, so the binding limit is
    the single-pulse surge -- and this repository has no vendor pulse curve and
    no Q41 thermal model, so that limit is reported as unverified rather than
    assumed.
    """
    c = crowbar()
    released = c["energy_released_to_uvlo_j"]
    duration = c["time_to_uvlo_s"]
    peak_current = VREG_TYP / c["r_total_ohm"]
    r44_energy = released * R_CROWBAR / c["r_total_ohm"]
    fet_energy = released * RDS_SELECTED / c["r_total_ohm"]
    r44_peak = peak_current ** 2 * R_CROWBAR
    return {
        "duration_s": duration,
        "r44_energy_j": r44_energy,
        "fet_energy_j": fet_energy,
        "r44_peak_power_w": r44_peak,
        "r44_mean_power_w": r44_energy / duration,
        "r44_equivalent_pulse_width_s": r44_energy / r44_peak,
        "fet_peak_power_w": peak_current ** 2 * RDS_SELECTED,
        "fet_mean_power_w": fet_energy / duration,
        "repetition": {
            "1_per_s_w": r44_energy * 1,
            "10_per_s_w": r44_energy * 10,
            "100_per_s_w": r44_energy * 100,
            "continuous_rating_w": 0.5,
            "rate_at_continuous_rating_per_s": 0.5 / r44_energy,
            "basis": "thermal average = released energy x rate; the single-pulse "
                     "surge, not this average, is the binding limit",
        },
        "r44_pulse_rating_j": None,
        "q41_thermal": None,
        "temperature_note": "no vendor pulse curve for the 1206 and no Q41 thermal "
                            "model in this repository: single-pulse capability and "
                            "temperature rise are UNVERIFIED, not assumed",
    }


def q41_selection() -> dict:
    """Why AO3400A, at which gate voltage its Rds(on) is taken, and what is left.

    The review (2026-11-05) accepted AO3400A as a candidate and asked for the
    actual gate voltage, the turn-on crossing and the pins.  Those three are
    answered here; selection is not qualification, so ``qualified`` stays false
    and the open items are listed rather than closed.
    """
    vg = 3.3 * R_FAULT_PULLDOWN / (R_FAULT_SERIES + R_FAULT_PULLDOWN)   # 3.0 V
    rds_used = Q41_RDS_MAX[2.5]
    assert 2.5 <= vg < 4.5, "the 3.3 V harness has to land between two datasheet columns"
    r_source = R_FAULT_SERIES * R_FAULT_PULLDOWN / (R_FAULT_SERIES + R_FAULT_PULLDOWN)
    r_gate = R_CROWBAR_GATE + Q41_RG_MAX
    tau_g = (r_source + r_gate) * Q41_CISS_TYP
    # Exact step response of the linear C40 / Ciss two-node ladder, not
    # two independently added RC delays. Ciss is typical and voltage-dependent.
    trace = (1 / r_source + 1 / r_gate) / FAULT_RC_C + 1 / (r_gate * Q41_CISS_TYP)
    determinant = 1 / (r_source * r_gate * FAULT_RC_C * Q41_CISS_TYP)
    fast = (trace + math.sqrt(trace * trace - 4 * determinant)) / 2
    slow = determinant / fast
    def crossing(target):
        lo, hi = 0.0, 100 / slow
        for _ in range(80):
            mid = (lo + hi) / 2
            voltage = vg * (1 - (fast * math.exp(-slow * mid)
                                  - slow * math.exp(-fast * mid)) / (fast - slow))
            if voltage < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    t_th = crossing(Q41_VGS_TH_MAX)
    plateau = Q41_VGS_TH_MAX + 0.75
    t_plateau = crossing(plateau)
    i_drive = (vg - plateau) / (r_source + r_gate)
    t_miller = Q41_QGD_TYP / i_drive
    # Add a quasi-static Miller interval to the linear ladder estimate.
    # This is neither a nonlinear MOSFET model nor a guaranteed upper bound.
    turn_on = t_plateau + t_miller
    peak_a = VREG_TYP / (R_CROWBAR + RDS_SELECTED)
    return {
        "ref": "Q41",
        "mpn": Q41_MPN,
        "mpn_source": Q41_MPN_SOURCE,
        "package": "SOT-23",
        "footprint": "Package_TO_SOT_SMD:SOT-23",
        "pins": {"1": "G", "2": "S", "3": "D"},
        "symbol_pin_map": "Q_NMOS_GSD: 1=G, 2=S, 3=D -- same numbering as SOT-23",
        "abs_max_vds_v": 30.0,
        "abs_max_vgs_v": 12.0,
        "id_a_25c": Q41_ID_A,
        "idm_a": Q41_IDM_A,
        "vgs_th_max_v": Q41_VGS_TH_MAX,
        "rds_max_ohm_by_vgs": {f"{k:g}": v for k, v in sorted(Q41_RDS_MAX.items())},
        "gate_level_v_at_3v3_harness": vg,
        "rds_used_ohm": rds_used,
        "rds_basis": f"{vg:.1f} V sits between the 2.5 and 4.5 V datasheet columns; "
                      "the 2.5 V maximum is used because interpolation is not a "
                      "guarantee and the 4.5 V column does not apply",
        "turn_on_estimate": {
            "gate_rc_s": tau_g,
            "source_thevenin_ohm": r_source,
            "time_to_plateau_s": t_plateau,
            "total_estimate_s": turn_on,
            "includes_input_filter": True,
            "is_upper_bound": False,
            "time_to_threshold_s": t_th,
            "miller_crossing_s": t_miller,
            "assumed_plateau_v": plateau,
            "peak_switch_power_w": VREG_TYP * peak_a,
            "linear_ramp_energy_estimate_j":
                0.5 * VREG_TYP * peak_a * turn_on,
            "status": "ESTIMATE from datasheet typ Ciss/Qgd and an assumed Miller "
                      "plateau; no SOA curve at this crossing is digitised in the "
                      "repository, so turn-on stress is UNVERIFIED",
        },
        "stress_check": {
            "peak_current_a": peak_a,
            "idm_margin": Q41_IDM_A / peak_a,
            "fet_peak_power_w": peak_a ** 2 * RDS_SELECTED,
            "fet_energy_j": crowbar()["fet_share_j"],
        },
        "open_items": [
            "SOA at the 11 V turn-on crossing is not checked against a vendor curve",
            "self-heating and the Rds(on) temperature coefficient are not modelled",
            "repeated-pulse capability of R44 is not checked (no vendor curve)",
            "the 3.3 V harness gives a 3.0 V gate; a 5 V harness would allow the "
            "4.5 V column, but that column is not used here",
        ],
        "qualified": False,
    }


def input_default() -> dict:
    """What the board does when nobody drives it.

    FAULT_IN falls back to no-fault, so a disconnected or unpowered fault
    source does not shut anything down.  The status output is open drain with
    an on-board 100k to PGND, so its high level is a divider against whatever
    the harness pulls up with.
    """
    # The open-drain pin sits at the bottom of a divider: external pull-up on
    # top, R42 (100 k) to PGND below, so the high level is the pulldown's share.
    high_10k = EXTERNAL_PULLUP_V * R_STATUS_PULLDOWN / (10e3 + R_STATUS_PULLDOWN)
    return {
        "fault_input_pulldown_ohm": R_FAULT_PULLDOWN,
        "fault_input_default": "no crowbar",
        "limitation": "a disconnected or unpowered fault source leaves the board "
                      "in no-fault; the harness must drive FAULT_IN and a "
                      "lost-source case belongs in the bench plan",
        "status_output": {
            "pulldown_ohm": R_STATUS_PULLDOWN,
            "external_pullup_v": EXTERNAL_PULLUP_V,
            "high_level_v_with_10k_pullup": high_10k,
            "note": "open drain; without an external pull-up the status pin reads "
                    "low in both states",
        },
        "gate_drive": {
            "fault_g_v_at_3v3": 3.3 * R_FAULT_PULLDOWN / (R_FAULT_SERIES + R_FAULT_PULLDOWN),
            "fault_g_v_at_5v0": 5.0 * R_FAULT_PULLDOWN / (R_FAULT_SERIES + R_FAULT_PULLDOWN),
            "series_ohm": R_FAULT_SERIES,
            "note": "D40 clamps at 5.1 V and does not conduct at either harness level",
            "rds_claim": f"{Q41_MPN} meets {RDS_BOM_TARGET:g} ohm at the 3.0 V gate the "
                         "3.3 V harness produces (datasheet max 0.048 ohm at 2.5 V); "
                         "a 2N7002-class part at 3.0 V does not",
        },
    }


def vdd_cut() -> dict:
    """How long a VDD-only cut takes to reach REG UVLO."""
    c = C_VDD_TOTAL
    t_to_uvlo = c * (VDD_NOM - VREGON_MAX) / IVDD_RUN_MAX
    t_to_zero = c * VDD_NOM / IVDD_RUN_MAX
    standby = c * VDD_NOM / IVDD_STBY_TYP
    return {
        "c_vdd_f": c,
        "ivdd_run_max_a": IVDD_RUN_MAX,
        "time_to_reg_uvlo_s": t_to_uvlo,
        "time_to_0v_at_run_current_s": t_to_zero,
        "time_to_0v_at_standby_current_s": standby,
        "note": "constant-current discharge; the gate stays high until REG UVLO, "
                "so a VDD cut alone is not a protection",
    }


def vg_clamp_table() -> list[dict]:
    """Contention between a clamp and the UCC24624's 6.5 ohm pull-up."""
    rows = []
    for rds in RDS_CLAMP_TABLE:
        v_hold = VREG_TYP * rds / (RVG_PU_TYP + rds)
        i_drive = VREG_TYP / (RVG_PU_TYP + rds)
        p_ic = (VREG_TYP - v_hold) * i_drive
        rows.append({
            "rds_on_ohm": rds,
            "vg_hold_v": v_hold,
            "driver_current_a": i_drive,
            "ic_dissipation_w": p_ic,
            "pulse_energy_j_at_10us": p_ic * 10e-6,
            "below_vgs_th_min": v_hold < VGS_TH_MIN,
            # Once the demanded current passes the 1.5 A source limit the IC
            # stops regulating VG, so the divider overstates VG.  Both columns
            # are reported so the crossover is visible rather than assumed.
            "exceeds_ic_source_limit": i_drive > IVG_SRC_TYP,
        })
    return rows


def gate_discharge() -> dict:
    """Passive gate decay through Rgs if nothing else pulls the gate down."""
    tau = R_GS * CISS_MAX
    t_to_threshold = tau * math.log(VGHI_TYP / VGS_TH_MIN)
    active = CISS_MAX * VGHI_TYP / IVG_SNK_TYP
    return {
        "rgs_ohm": R_GS,
        "ciss_max_f": CISS_MAX,
        "passive_tau_s": tau,
        "passive_time_to_threshold_s": t_to_threshold,
        "active_sink_time_s": active,
        "note": "4 A sink discharges the gate in nanoseconds; Rgs alone needs "
                "tens of microseconds and is the power-down default, not a fault path",
    }


def states() -> list[dict]:
    """Who drives VG, who pulls it down, in every state the board can be put in."""
    return [
        {
            "state": "NORMAL",
            "entry": "FAULT_IN low, JP1 fitted, VDD and REG valid",
            "vg_high_driver": "U1 VG pin through RVG_PU 6.5 ohm from REG",
            "vg_low_driver": "U1 VG pin through RVG_PD 0.9 ohm to PGND",
            "reg_owner": "U1 internal linear regulator, 11 V",
            "vdd_owner": "J1 through F1, D2 and JP1",
            "gate_pulldown": "Rgs 10k (backup only)",
            "expected": "normal SR switching; VG follows the VD sense",
        },
        {
            "state": "FAULT_REG_CROWBAR",
            "entry": "FAULT_IN high, JP1 fitted",
            "vg_high_driver": "U1 still sources until REG crosses VREGOFF (3.63 V min)",
            "vg_low_driver": "U1 UVLO sink (4 A) after REG crosses VREGOFF; "
                             "Q41 only collapses REG, it does not touch VG",
            "reg_owner": "Q41 + R44 pull REG to PGND against the U1 regulator, "
                         "which keeps sourcing while it can",
            "vdd_owner": "still connected; this is the point of the test",
            "gate_pulldown": "Rgs 10k in parallel with the U1 sink",
            "expected": f"REG reaches UVLO in {crowbar()['time_to_uvlo_s'] * 1e6:.1f} us "
                        "at the 3.63 V threshold (estimate, not a worst case), "
                        "then VG is actively low",
        },
        {
            "state": "FAULT_VDD_CUT",
            "entry": "JP1 removed, FAULT_IN low",
            "vg_high_driver": "none; C_VDD holds U1 alive",
            "vg_low_driver": "Rgs 10k only until VDD crosses UVLO",
            "reg_owner": "U1 regulator until VDD UVLO",
            "vdd_owner": "C1+C2+C3 discharging into U1",
            "gate_pulldown": "Rgs 10k",
            "expected": f"{vdd_cut()['time_to_reg_uvlo_s'] * 1e3:.0f} ms to REG UVLO; "
                        "cutting VDD alone is not a protection",
        },
        {
            "state": "FAULT_VG_CLAMP",
            "entry": "FAULT_IN high, R47/R48 fitted, Q42/Q43 fitted",
            "vg_high_driver": "U1 VG source, current-limited at 1.5 A typ",
            "vg_low_driver": "Q42/Q43 to PGND; contention with U1",
            "reg_owner": "U1 regulator (REG stays at 11 V)",
            "vdd_owner": "J1 through F1, D2 and JP1",
            "gate_pulldown": "clamp FET, not Rgs",
            "expected": "measured contention; see vg_clamp_table. A clamp that "
                        "holds VG below 1.3 V makes U1 dissipate >10 W",
        },
        {
            "state": "STANDBY",
            "entry": "U1 detects standby after tSTBY_DET >= 5.5 ms",
            "vg_high_driver": "none",
            "vg_low_driver": "U1 actively holds VG low",
            "reg_owner": "U1 regulator, 180 uA standby",
            "vdd_owner": "unchanged",
            "gate_pulldown": "U1 internal",
            "expected": "too slow for a fault window (7.5 ms typ vs ~15 us)",
        },
        {
            "state": "POWER_DOWN",
            "entry": "VDD and REG at 0 V",
            "vg_high_driver": "none",
            "vg_low_driver": "Rgs 10k",
            "reg_owner": "none",
            "vdd_owner": "none",
            "gate_pulldown": "Rgs 10k",
            "expected": f"gate decays through Rgs in {gate_discharge()['passive_tau_s'] * 1e6:.0f} us tau",
        },
    ]


def delay_budget() -> dict:
    """Branch delays for the SR side of the roadmap's t_stop equation.

    The primary branch is not on this board; its reference numbers come from
    the same datasheet set so the ``max`` can be evaluated.  With the values
    here the SR branch is the slower one, and it is REG UVLO -- not the 4 A
    gate sink -- that sets it.  That is the whole argument for a crowbar.
    """
    c = crowbar()
    gd = gate_discharge()
    turn_on = q41_selection()["turn_on_estimate"]["total_estimate_s"]
    sr = turn_on + c["time_to_uvlo_s"] + gd["active_sink_time_s"]
    primary = 500e-9 + 750e-9 + 30e-9 + 10e-9
    return {
        "detection_common": {
            "fault_input_rc_s": 0.0,
            "note_filter": "C40 is included once in Q41 two-node turn-on estimate",
            "comparator": "not on this board; the fault input is a logic signal",
            "note": "the SR branch starts when FAULT_IN is valid",
        },
        "sr_branch": {
            "input_rc_s": 0.0,
            "input_filter_included_in_turn_on": True,
            "crowbar_fet_turn_on_s": turn_on,
            "crowbar_fet_turn_on_basis": "C40/Ciss two-node ladder plus assumed Miller plateau; not worst case",
            "reg_to_uvlo_s": c["time_to_uvlo_s"],
            "reg_to_uvlo_basis": f"3.63 V turn-off threshold (slowest of "
                                 f"3.63/4.0/4.25 V), {Q41_MPN} Rds(on) "
                                 f"{RDS_SELECTED} ohm at 2.5 V VGS",
            "reg_to_uvlo_with_reg_current_limit_s":
                c["time_to_uvlo_with_reg_current_limit_s"],
            "vg_active_low_s": gd["active_sink_time_s"],
            "total_s": sr,
            "dominant_term": "reg_to_uvlo_s",
        },
        "primary_branch_reference": {
            "note": "not implemented on this board; numbers are for the roadmap "
                    "equation, from the same datasheet set",
            "ucc25600_oc_propagation_max_s": 500e-9,
            "ucc25600_disable_propagation_max_s": 750e-9,
            "ucc27282_propagation_max_s": 30e-9,
            "ucc27282_fall_time_1n8_s": 10e-9,
            "total_s": primary,
        },
        "max_branch_s": max(sr, primary),
        "slowest_branch": "sr" if sr > primary else "primary",
        "is_worst_case": False,
        "not_worst_case_reasons": [
            "reg_to_uvlo_s is an RC estimate at the 3.63 V threshold; the "
            "regulator keeps sourcing, and the current-limit column is a sensitivity",
            "component tolerances on R44 and the REG capacitors are not applied",
            "Q41 turn-on and its gate threshold are estimates from typical "
            "datasheet values; there is no digitised SOA curve in the repository",
        ],
        "rule": "t_stop = t_common + max(t_primary, t_SR); do not add the two "
                "branches in series",
    }


def observations() -> list[dict]:
    c = crowbar()
    v = vdd_cut()
    clamp = vg_clamp_table()
    weak = clamp[[r["rds_on_ohm"] for r in clamp].index(1.5)]
    strong = clamp[0]
    return [
        {
            "id": "SR-01",
            "finding": "The UCC24624 has no enable pin; only REG UVLO or standby "
                       "turns the gate off. The crowbar therefore targets REG, not VG.",
            "evidence": f"{UCC} (pin functions, electrical characteristics)",
            "status": "DESIGN_DECISION",
        },
        {
            "id": "SR-02",
            "finding": f"REG holds {c['stored_energy_j'] * 1e6:.0f} uJ at 11 V "
                       f"({c['energy_released_to_uvlo_j'] * 1e6:.0f} uJ down to the "
                       f"3.63 V threshold); the {c['r_total_ohm']:.1f} ohm crowbar "
                       f"reaches UVLO in {c['time_to_uvlo_s'] * 1e6:.1f} us. That is an "
                       "estimate covering a low-threshold part, not a fast hard "
                       "shutdown and not a hardware worst case.",
            "evidence": f"computed from C4+C5 and {UCC} VREGOFF min/max",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "SR-03",
            "finding": f"A VDD-only cut takes {v['time_to_reg_uvlo_s'] * 1e3:.0f} ms "
                       f"at the 1.5 mA run current -- three orders of magnitude slower.",
            "evidence": f"computed from C1+C2+C3 and {UCC} IVDDRUN",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "SR-04",
            "finding": "A 2N7002-class VG clamp (1.5 ohm) only reaches "
                       f"{weak['vg_hold_v']:.2f} V, above the {VGS_TH_MIN:.2f} V "
                       "threshold, so it cannot guarantee the SR FET is off.",
            "evidence": f"divider against {UCC} RVG_PU; {BSC} VGS(th)",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "SR-05",
            "finding": "A clamp strong enough to hold VG low "
                       f"({strong['rds_on_ohm']:.2f} ohm) makes U1 dissipate "
                       f"{strong['ic_dissipation_w']:.1f} W while it keeps sourcing.",
            "evidence": f"computed from {UCC} RVG_PU and IVGSOURCE",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "SR-06",
            "finding": "Passive gate decay through Rgs 10k is "
                       f"{gate_discharge()['passive_tau_s'] * 1e6:.0f} us tau; the "
                       "4 A active sink is what makes the UVLO path fast.",
            "evidence": f"{BSC} Ciss; {UCC} IVGSINK",
            "status": "DESIGN_ESTIMATE",
        },
        {
            "id": "SR-07",
            "finding": "This board is not a 100 A power stage and has no thermal "
                       "model; it validates the shutdown interface only.",
            "evidence": "scope of the board",
            "status": "BOUNDARY",
        },
        {
            "id": "SR-08",
            "finding": "FAULT_IN defaults to no crowbar. A lost or unpowered fault "
                       "source therefore does not shut the board down; the bench "
                       "plan has to drive it and test the lost-source case.",
            "evidence": "R41 10k to PGND on the fault input",
            "status": "BOUNDARY",
        },
        {
            "id": "SR-09",
            "finding": f"A 3.3 V harness gives Q41 only "
                       f"{input_default()['gate_drive']['fault_g_v_at_3v3']:.1f} V of "
                       "gate drive, so the BOM's Rds(on) <= 0.1 ohm has to be quoted "
                       "at that voltage or the harness has to drive 5 V.",
            "evidence": "R40/R41 divider into the Q41 gate; Q41 AO3400A selected, transient qualification open",
            "status": "DESIGN_DECISION",
        },
    ]


def report(ps: list[Part]) -> dict:
    nets = nets_of(ps)
    return {
        "kind": "UCC24624_SINGLE_PAIR_FAULT_SHUTDOWN_BOARD",
        "evidence_level": "GENERATED_SCHEMATIC_AND_NETLIST_NOT_HARDWARE",
        "hardware_built": False,
        "fabrication_approved": False,
        "part_instances": len(ps),
        "physical_parts": len([p for p in ps if not p.ref.startswith("#")]),
        "nets": len(nets),
        "net_map": nets,
        "states": states(),
        "crowbar": crowbar(),
        "crowbar_pulse": crowbar_pulse(),
        "q41_selection": q41_selection(),
        "input_default": input_default(),
        "vdd_cut": vdd_cut(),
        "vg_clamp_table": vg_clamp_table(),
        "gate_discharge": gate_discharge(),
        "delay_budget": delay_budget(),
        "observations": observations(),
        "limits": [
            "low-energy validation board, <=10 A and <=5 V output",
            "no thermal model; Rds(on) and Ciss are datasheet typical/max, not measured",
            f"Q41 is selected as {Q41_MPN} (datasheet in references/) but not qualified: "
            "SOA at the turn-on crossing, self-heating and the R44 pulse curve are open",
            "no vendor pulse curve for R44 and no Q41 thermal model; pulse "
            "capability and temperature rise are unverified",
            "FAULT_IN defaults to no crowbar: a lost fault source is not a shutdown",
            "a clean ERC only says the drawing agrees with itself",
        ],
    }


# ------------------------------------------------------------------ driver
def check() -> None:
    cli = kicad_cli()
    if cli is None:
        raise SystemExit("kicad-cli not found: ERC and netlist export cannot be reproduced here")
    sch = OUT / "sr_fault_validation.kicad_sch"
    net = OUT / "sr_fault_validation.net"
    erc = OUT / "erc.rpt"
    (OUT / "sr_fault_validation.kicad_pro").write_text(project_file(), encoding="utf-8")
    subprocess.run([str(cli), "sch", "export", "netlist", str(sch), "-o", str(net)],
                   check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", str(sch), "-o", str(erc)],
                   check=True)
    subprocess.run([str(cli), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=True)
    text = net.read_text(encoding="utf-8")
    print(f"netlist: {text.count('(net' + chr(10))} nets -> {net.name}")
    violations = erc_violations(newer_than=sch)
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean -- fix the circuit or record why each one is accepted")
    required = ["VDD", "REG", "VG1", "VG2", "VD1", "VD2", "VSS", "SR_SRC",
                "SEC_A", "SEC_B", "VOUT", "FAULT_IN", "FAULT_G", "FAULT_N",
                "REG_CROW", "G1", "G2"]
    net_names = set(re.findall(r'\(name "/([^"]+)"\)', text))
    missing = [n for n in required if n not in net_names]
    if missing:
        raise SystemExit(f"nets missing from netlist: {missing}")


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
    path = OUT / "sr_fault_validation.kicad_sch"
    path.write_text(schematic(symbols, ps), encoding="utf-8")
    print(f"wrote {path}")
    bom(ps)
    (OUT / "sr_fault_validation.json").write_text(
        json.dumps(report(ps), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'sr_fault_validation.json'}")
    if args.check:
        check()


if __name__ == "__main__":
    main()
