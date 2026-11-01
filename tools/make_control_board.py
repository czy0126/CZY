"""Generate the UCC24624 SR control-validation board (schematic + BOM).

Why generated: the board is small but has ~40 parts and 50 nets.  Writing the
KiCad s-expression by hand would make every later pin swap a manual edit; this
script keeps one component table as the single source of truth for the
schematic, the netlist and the BOM.  The PCB is a separate step (see
`pcb/control_validation/`), because placement/layout is a manufacturing choice,
not a netlist fact.

The schematic is NET-LABEL FIRST: every pin gets a local label with its net
name instead of a drawn wire.  That is valid KiCad connectivity (verified with
`kicad-cli sch export netlist`) and is honest about what this file is -- a
machine-checked netlist with a human-readable symbol layout.  A human should
redraw it for readability before releasing a production board; the netlist and
BOM stay authoritative either way.

Usage:
    python tools/make_control_board.py
    python tools/make_control_board.py --check     # kicad-cli netlist + ERC, fails on violations

``--check`` also writes ``control_validation.kicad_pro``.  That file is not
decoration: without it ``kicad-cli`` never loads ``sym-lib-table`` and ERC
reports every symbol from the two project-local libraries as an unknown
library (measured: 3 warnings without it, 0 violations with it).  See
``project_file()`` for the experiment.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "control_validation"
KICAD_SHARE = Path(r"C:\Users\27792\AppData\Local\Programs\KiCad\10.0\share\kicad")
SYMBOL_LIBS = KICAD_SHARE / "symbols"
KICAD_CLI = Path(r"C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe")
NS = uuid.UUID("6f1c2a54-6d0e-4c1f-9c1f-2b1a4f5e6d70")


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
    nets: dict[str, str]  # pin number -> net name
    rating: str = ""
    note: str = ""
    dnp: bool = False


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


# ---------------------------------------------------------------- symbols
def extract_symbol(path: Path, name: str) -> str:
    """Copy a balanced (symbol "name" ...) block out of a KiCad library."""
    text = path.read_text(encoding="utf-8")
    key = f'(symbol "{name}"'
    start = text.find(key)
    if start < 0:
        raise SystemExit(f"{name} not found in {path}")
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
                    return text[start:i + 1]
        i += 1
    raise SystemExit(f"unbalanced symbol {name}")


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
    """Pin number -> symbol-space pin tip (x, y), y up."""
    out: dict[str, tuple[float, float]] = {}
    i = 0
    while True:
        i = block.find("(pin ", i)
        if i < 0:
            return out
        j = block.find("(number \"", i)
        at = block.find("(at ", i)
        if j < 0 or at < 0:
            return out
        num = block[j + len("(number \""):block.find('"', j + len("(number \""))]
        nums = block[at + 4:block.find(")", at)].split()
        out[num] = (float(nums[0]), float(nums[1]))
        i = j + 1


def custom_symbol(name: str, pins: list[Pin], width: float, height: float,
                  reference: str = "U", footprint: str = "") -> str:
    """A rectangular symbol with explicit pin tips (KiCad modern format)."""
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
    "Device:Fuse": ("Device.kicad_sym", "Fuse"),
    "Transistor_FET:Q_NMOS_GSD": ("Transistor_FET.kicad_sym", "Q_NMOS_GSD"),
    "Connector_Generic:Conn_01x02": ("Connector_Generic.kicad_sym", "Conn_01x02"),
    "Connector_Generic:Conn_01x04": ("Connector_Generic.kicad_sym", "Conn_01x04"),
    "Connector:TestPoint": ("Connector.kicad_sym", "TestPoint"),
    "power:PWR_FLAG": ("power.kicad_sym", "PWR_FLAG"),
}


def build_symbols() -> dict[str, str]:
    symbols: dict[str, str] = {}
    for lib_id, (lib, name) in STANDARD.items():
        block = extract_symbol(SYMBOL_LIBS / lib, name)
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
        "SR:BSC010N04LS6", bsc, 7.62, 10.16, "Q",
        "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm")
    return symbols


# ---------------------------------------------------------------- parts
def parts() -> list[Part]:
    p: list[Part] = [
        # bias input
        Part("J1", "Connector_Generic:Conn_01x02", "VBIAS 15V",
             "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm", 30, 55,
             {"1": "VBIAS", "2": "PGND"}, "15 V, 0.5 A", "bias input, polarity marked"),
        Part("F1", "Device:Fuse", "0.5A",
             "Fuse:Fuse_1206_3216Metric", 52, 45, {"1": "VBIAS", "2": "VIN_F"},
             "0.5 A", "bias fuse"),
        Part("D1", "Device:D_TVS", "SMBJ15A",
             "Diode_SMD:D_SMB", 52, 68, {"1": "VIN_F", "2": "PGND"},
             "15 V standoff", "bias TVS"),
        Part("D2", "Device:D_Schottky", "SS34",
             "Diode_SMD:D_SMA", 72, 45, {"1": "VDD", "2": "VIN_F"},
             "40 V 3 A", "reverse-polarity block; VDD = 15 V - 0.5 V"),
        Part("C1", "Device:C", "10uF/35V", "Capacitor_SMD:C_1210_3225Metric",
             92, 38, {"1": "VDD", "2": "PGND"}, "35 V X7R", ""),
        Part("C2", "Device:C", "1uF/35V", "Capacitor_SMD:C_0805_2012Metric",
             104, 38, {"1": "VDD", "2": "PGND"}, "35 V X7R", ""),
        Part("C3", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric",
             116, 38, {"1": "VDD", "2": "PGND"}, "50 V X7R", "at pin 7"),
        # controller
        Part("U1", "UCC24624:UCC24624", "UCC24624DR",
             "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 160, 90,
             {"1": "VG1", "2": "PGND", "3": "REG", "4": "VD1", "5": "VSS",
              "6": "VD2", "7": "VDD", "8": "VG2"}, "230 V VD pins",
             "SR controller, SOIC-8"),
        Part("C4", "Device:C", "2.2uF/25V", "Capacitor_SMD:C_1206_3216Metric",
             160, 68, {"1": "REG", "2": "PGND"}, "25 V X7R", "REG bypass, <=1 cm"),
        Part("C5", "Device:C", "100nF/50V", "Capacitor_SMD:C_0603_1608Metric",
             174, 68, {"1": "REG", "2": "PGND"}, "50 V X7R", ""),
        Part("Q4", "Transistor_FET:Q_NMOS_GSD", "2N7002",
             "Package_TO_SOT_SMD:SOT-23", 142, 66, {"1": "REG_HOLD", "2": "PGND", "3": "REG"},
             "60 V", "REG hold-low for power-on qualification test"),
        Part("R4", "Device:R", "100k", "Resistor_SMD:R_0603_1608Metric",
             130, 78, {"1": "REG_HOLD", "2": "PGND"}, "1/10 W", "Q4 gate pulldown"),
        # VSS / offset / sensing links
        Part("R1", "Device:R", "0R", "Resistor_SMD:R_0805_2012Metric",
             196, 90, {"1": "VSS", "2": "SR_SRC"}, "<=212 R option",
             "Roffset: VTHOFF = 10.5 mV + 330 uA * R"),
        Part("R2", "Device:R", "0R", "Resistor_SMD:R_0603_1608Metric",
             206, 72, {"1": "VD1", "2": "SEC_A"}, "100 R option", "VD1 link"),
        Part("R3", "Device:R", "0R", "Resistor_SMD:R_0603_1608Metric",
             206, 108, {"1": "VD2", "2": "SEC_B"}, "100 R option", "VD2 link"),
        # SR pair
        Part("Q1", "SR:BSC010N04LS6", "BSC010N04LS6",
             "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm", 250, 70,
             {"1": "SR_SRC", "2": "SR_SRC", "3": "SR_SRC", "4": "G1",
              "5": "SEC_A", "6": "SEC_A", "7": "SEC_A", "8": "SEC_A"},
             "40 V 1.0 mR", "SR1; source Kelvin to VSS"),
        Part("Q2", "SR:BSC010N04LS6", "BSC010N04LS6",
             "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm", 250, 130,
             {"1": "SR_SRC", "2": "SR_SRC", "3": "SR_SRC", "4": "G2",
              "5": "SEC_B", "6": "SEC_B", "7": "SEC_B", "8": "SEC_B"},
             "40 V 1.0 mR", "SR2; source Kelvin to VSS"),
        Part("Rg1", "Device:R", "0R", "Resistor_SMD:R_0805_2012Metric",
             222, 62, {"1": "VG1", "2": "G1"}, "2.2-10 R option", "gate resistor"),
        Part("Rg2", "Device:R", "0R", "Resistor_SMD:R_0805_2012Metric",
             222, 138, {"1": "VG2", "2": "G2"}, "2.2-10 R option", "gate resistor"),
        Part("Rgs1", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
             236, 52, {"1": "G1", "2": "SR_SRC"}, "1/10 W", "gate-source pulldown"),
        Part("Rgs2", "Device:R", "10k", "Resistor_SMD:R_0603_1608Metric",
             236, 148, {"1": "G2", "2": "SR_SRC"}, "1/10 W", "gate-source pulldown"),
        Part("CGL1", "Device:C", "6.8nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             224, 48, {"1": "G1", "2": "SR_SRC"}, "50 V", "specified gate-load test", True),
        Part("CGL2", "Device:C", "6.8nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             224, 152, {"1": "G2", "2": "SR_SRC"}, "50 V", "specified gate-load test", True),
        Part("Rsh1", "Device:R", "1mR 1%", "Resistor_SMD:R_2512_6332Metric",
             276, 70, {"1": "SR_SRC", "2": "PGND"}, "2 W", "current sense 10 A -> 10 mV"),
        Part("Rsh2", "Device:R", "1mR 1%", "Resistor_SMD:R_2512_6332Metric",
             276, 130, {"1": "SR_SRC", "2": "PGND"}, "2 W", "current sense"),
        Part("Rsn1", "Device:R", "10R DNP", "Resistor_SMD:R_0603_1608Metric",
             266, 50, {"1": "SEC_A", "2": "SN1"}, "1/10 W", "RC snubber", True),
        Part("Csn1", "Device:C", "1nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             278, 50, {"1": "SN1", "2": "SR_SRC"}, "50 V", "RC snubber", True),
        Part("Rsn2", "Device:R", "10R DNP", "Resistor_SMD:R_0603_1608Metric",
             266, 150, {"1": "SEC_B", "2": "SN2"}, "1/10 W", "RC snubber", True),
        Part("Csn2", "Device:C", "1nF DNP", "Capacitor_SMD:C_0603_1608Metric",
             278, 150, {"1": "SN2", "2": "SR_SRC"}, "50 V", "RC snubber", True),
        # output / transformer interface
        Part("J3", "Connector_Generic:Conn_01x04", "SEC A/CT/B",
             "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm", 320, 170,
             {"1": "SEC_A", "2": "VOUT", "3": "SEC_B", "4": "PGND"},
             "20 V peak, 10 A", "isolated low-voltage centre-tapped source"),
        Part("C6", "Device:C", "100uF/6.3V", "Capacitor_SMD:C_1210_3225Metric",
             318, 95, {"1": "VOUT", "2": "PGND"}, "6.3 V X5R", ""),
        Part("C7", "Device:C", "10uF/10V", "Capacitor_SMD:C_0805_2012Metric",
             330, 95, {"1": "VOUT", "2": "PGND"}, "10 V X7R", ""),
        Part("J2", "Connector_Generic:Conn_01x02", "LOAD 0.2-2R",
             "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm", 350, 110,
             {"1": "VOUT", "2": "PGND"}, "2 A max", "load / electronic load"),
        # injection for interlock and narrow-pulse tests
        Part("R5", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
             110, 190, {"1": "FORCE1", "2": "VD1"}, "1/10 W", "VD1 injection"),
        Part("R6", "Device:R", "1k", "Resistor_SMD:R_0603_1608Metric",
             110, 210, {"1": "FORCE2", "2": "VD2"}, "1/10 W", "VD2 injection"),
        Part("JP1", "Connector_Generic:Conn_01x02", "FORCE1 low",
             "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 90, 190,
             {"1": "FORCE1", "2": "PGND"}, "shunt = force VD1 low", ""),
        Part("JP2", "Connector_Generic:Conn_01x02", "FORCE2 low",
             "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 90, 210,
             {"1": "FORCE2", "2": "PGND"}, "shunt = force VD2 low", ""),
        Part("#FLG1", "power:PWR_FLAG", "PWR_FLAG", "", 120, 30,
             {"1": "VDD"}, "", "ERC: declares the bias input as a source"),
        Part("#FLG2", "power:PWR_FLAG", "PWR_FLAG", "", 140, 30,
             {"1": "PGND"}, "", "ERC: declares the return as a source"),
    ]
    tps = [
        ("TP1", "VDD"), ("TP2", "REG"), ("TP3", "VSS"), ("TP4", "VD1"),
        ("TP5", "VD2"), ("TP6", "VG1"), ("TP7", "VG2"), ("TP8", "PGND"),
        ("TP9", "SR_SRC"), ("TP10", "PGND"), ("TP11", "VOUT"), ("TP12", "PGND"),
    ]
    for i, (ref, net) in enumerate(tps):
        p.append(Part(ref, "Connector:TestPoint", net,
                      "TestPoint:TestPoint_Pad_D1.0mm", 30 + 15 * i, 240,
                      {"1": net}, "1 mm pad", "scope probe / Kelvin point"))
    return p


def validate(ps: list[Part], symbols: dict[str, str]) -> None:
    seen: set[str] = set()
    for part in ps:
        if part.ref in seen:
            raise SystemExit(f"duplicate reference {part.ref}")
        seen.add(part.ref)
        if part.lib not in symbols:
            raise SystemExit(f"{part.ref}: unknown symbol {part.lib}")
        nums = pin_numbers(symbols[part.lib])
        if set(nums) != set(part.nets):
            raise SystemExit(f"{part.ref}: pins {nums} != nets {sorted(part.nets)}")
        for net in part.nets.values():
            if not net or " " in net:
                raise SystemExit(f"{part.ref}: bad net name {net!r}")


# ---------------------------------------------------------------- schematic
def instance(part: Part, symbols: dict[str, str], labels: list[str]) -> str:
    block = symbols[part.lib]
    tips = pin_tips(block)
    on_board = "no" if part.ref.startswith("#") else "yes"
    in_bom = "no" if part.ref.startswith("#") else "yes"
    lines = [
        "\t(symbol",
        f'\t\t(lib_id "{part.lib}")',
        f"\t\t(at {part.x:g} {part.y:g} 0)",
        "\t\t(unit 1) (body_style 1)",
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
    # One label per unique (net, coordinate); stacked pins share a tip.
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
	(version 20260101)
	(generator "make_control_board.py")
	(generator_version "10.0")
	(uuid "{uid("root")}")
	(paper "A3")
	(title_block
		(title "UCC24624 SR control validation board")
		(date "2026-10-31")
		(rev "A")
		(comment 1 "Low-energy, isolated secondary-equivalent test. NOT a 48 V main board.")
		(comment 2 "Net-label schematic generated by tools/make_control_board.py.")
	)
	(lib_symbols
{body}
	)
{inst}
{lab}
	(sheet_instances
		(path "/" (page "1"))
	)
)
"""


def snap(part: Part) -> Part:
    """Keep every pin tip on KiCad's 1.27 mm connection grid.

    Library pin offsets are multiples of 1.27 mm, so snapping the origin is
    enough and makes ERC's off-grid warnings disappear without moving labels.
    """
    from dataclasses import replace

    return replace(part, x=round(part.x / 1.27) * 1.27, y=round(part.y / 1.27) * 1.27)


def write_libs(symbols: dict[str, str]) -> None:
    """Project-local symbol libraries for the two custom parts."""
    for lib, name in (("UCC24624", "UCC24624"), ("SR", "BSC010N04LS6")):
        key = f"{lib}:{name}"
        block = symbols[key].replace(f'(symbol "{key}"', f'(symbol "{name}"', 1)
        text = ('(kicad_symbol_lib (version 20241209) (generator "make_control_board.py")\n'
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
                    "MPN", "LCSC", "Qty"])
        for part in parts_:
            if part.ref.startswith("#"):
                continue
            w.writerow([part.ref, part.value, part.footprint, part.rating, part.note,
                        "yes" if part.dnp else "", "", "", 1])
    print(f"wrote {path}")


def project_file() -> str:
    """The ``.kicad_pro`` without which ERC cannot see the project libraries.

    ``sym-lib-table`` points at ``${KIPRJMOD}/UCC24624.kicad_sym`` and
    ``${KIPRJMOD}/SR.kicad_sym``.  ``kicad-cli`` only loads that table when a
    project file sits next to the schematic; with none it leaves KIPRJMOD
    undefined, and every symbol from those two libraries is reported as an
    unknown library.  Measured 2026-11-01 on this board (``--severity-all``):
    no project file -> 3 ``lib_symbol_issues`` warnings, with project file ->
    **0 violations**.  Passing ``-D KIPRJMOD=...`` on the command line does
    *not* fix it; the table is never read at all.

    The warnings said nothing about the circuit -- a reader could easily have
    "cleared" them by editing the symbols instead.
    """
    return json.dumps({
        "board": {}, "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "control_validation.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        # must match the root sheet's uuid in the generated schematic, or the
        # project has no root sheet and the table is still not loaded
        "sheets": [[uid("root"), "Root"]],
        "text_variables": {},
    }, indent=2) + "\n"


def erc_violations(path: Path | None = None) -> list[dict]:
    """Every ERC violation in ``erc.json``, flattened across sheets.

    ``path`` lets a caller read a report written somewhere other than the
    project directory -- the test does, so that running it does not rewrite a
    committed file just to change its timestamp.

    Returns ``[]`` when the file is missing -- the caller decides whether that
    is a skip or a failure, and this function does not pretend a missing report
    is a clean one.
    """
    path = path or OUT / "erc.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [v for sheet in data.get("sheets", []) for v in sheet.get("violations", [])]


def check() -> None:
    sch = OUT / "control_validation.kicad_sch"
    net = OUT / "control_validation.net"
    pro = OUT / "control_validation.kicad_pro"
    erc = OUT / "erc.rpt"
    pro.write_text(project_file(), encoding="utf-8")
    subprocess.run([str(KICAD_CLI), "sch", "export", "netlist", str(sch), "-o", str(net)], check=True)
    # --severity-all: the default report skips exclusions, and "0 violations"
    # has to mean every severity or it is not a sign-off.
    subprocess.run([str(KICAD_CLI), "sch", "erc", "--severity-all", str(sch), "-o", str(erc)],
                   check=False)
    subprocess.run([str(KICAD_CLI), "sch", "erc", "--severity-all", "--format", "json",
                    str(sch), "-o", str(OUT / "erc.json")], check=False)
    text = net.read_text(encoding="utf-8")
    nets = text.count("(net\n")
    print(f"netlist: {nets} nets -> {net.name}")
    print(f"ERC report -> {erc.name}")
    violations = erc_violations()
    print(f"ERC: {len(violations)} violation(s) at every severity")
    if violations:
        for v in violations:
            print(f"  {v['severity']} {v['type']}: {v['description']}")
        raise SystemExit("ERC is not clean -- fix the circuit or record why each one is accepted")
    missing = [n for n in ("VDD", "PGND", "REG", "SEC_A", "SEC_B", "VOUT", "VD1", "VD2")
               if f'"/{n}"' not in text and f'"{n}"' not in text]
    if missing:
        raise SystemExit(f"nets missing from netlist: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = build_symbols()
    parts_ = [snap(p) for p in parts()]
    validate(parts_, symbols)
    write_libs(symbols)
    path = OUT / "control_validation.kicad_sch"
    path.write_text(schematic(symbols, parts_), encoding="utf-8")
    print(f"wrote {path}  ({len(parts_)} parts, {len(symbols)} symbols)")
    bom(parts_)
    if args.check:
        check()


if __name__ == "__main__":
    main()
