"""One responsibility row per placeholder ref on the main power board.

The roadmap asks for a 61-placeholder item-by-item ECO.  What this repository
can honestly produce is the *join*: for every placeholder, which artefact
governs its connection, which artefact fixes its value, what the native design
has actually verified, and what single thing still blocks it.  It cannot
produce the MPN: no manufacturer evidence exists offline here, so every row
carries ``verified_mpn: null`` and the tool refuses to invent one.

Four existing artefacts are joined, none of them rewritten:

* ``component_decision_register.json``  -- the 61 rows and the decision asked;
* ``design/v3/pcb/board_netlist.csv``   -- refs the deck-derived netlist fixes;
* ``tools/main_board_schematic.py``     -- the 17 peripherals deliberately kept
  out of the golden netlist (decoupling, EN filter, control pull-downs);
* ``pin_footprint_review.csv``          -- the per-pin native review status.

The invariant that makes the list complete: the 61 placeholders partition into
"in the golden netlist" and "a schematic peripheral", with nothing in both and
nothing in neither.  A new placeholder that lands in neither fails the check.

Run:
    python tools/placeholder_eco.py            # print the summary
    python tools/placeholder_eco.py --write    # regenerate json + csv
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

import main_board_schematic as schematic
from magnetics_rfq_package import frozen_lr_core

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
BOM = ROOT / "design/v3/bom"
MAG = ROOT / "design/v3/magnetics/magnetics_design.json"
DECK = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
LIB = ROOT / "models/sr_timing_v3_3.lib"
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
REGISTER = HW / "component_decision_register.json"
PIN_REVIEW = HW / "pin_footprint_review.csv"
INVENTORY = HW / "gen/native_inventory_raw.json"
RFQ = HW / "rfq"
OUT_JSON = HW / "placeholder_eco.json"
OUT_CSV = HW / "placeholder_eco.csv"

STATUS = "RESPONSIBILITY_LIST_NOT_AN_ECO_ORDER"
MAGNETIC_ROLES = ("transformer winding", "over-current CT", "resonant inductor")
PERIPHERAL_ROLES = ("VDD decoupling", "EN filter", "U2 control pull-downs and run jumper")
OPEN = "OPEN - REASON GIVEN"

UNTRACED = {
    "REG capacitors": (
        "the 2.2 uF value is the UCC24624 datasheet recommendation; no computed artefact "
        "in this repository fixes it, so a candidate cannot be checked against a number here"
    ),
    "SR drain Kelvin link": (
        "the requirement is topologogical (VD1/VD2 must sense at the SR drain, so 0 ohm from "
        "the drain pad); no numeric artefact fixes it and a wrong part is a routing error, not "
        "a value error"
    ),
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _si(text: str) -> float:
    """Parse a SPICE value token: 47n, 1k, 5.36k, 976, 10meg."""
    text = text.strip().lower()
    for suffix, scale in (("meg", 1e6), ("n", 1e-9), ("u", 1e-6), ("m", 1e-3), ("k", 1e3)):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * scale
    return float(text)


def schematic_si(text: str | None) -> float | None:
    """Parse the schematic's own value style: ``10kΩ``, ``2.2Ω``, ``220nF``.

    The native project writes the part value as ``<number><multiplier><unit>``
    with no space, and the unit is sometimes the ohm sign and sometimes ``F``.
    Only the multiplier changes the number, so stripping the unit first keeps
    ohms, farads and henries in one function -- the ref decides which quantity
    is being compared, never the string.
    """
    if not text:
        return None
    body = text.strip()
    while body and body[-1] in "FΩΩ":
        body = body[:-1]
    try:
        return _si(body)
    except ValueError:
        return None


def deck_element(name: str) -> list[str]:
    """Tokens of the deck line whose first token is ``name``.

    Cites by element name, never by line number: a line number survives an edit
    and then silently points at a different component.
    """
    for line in DECK.read_text(encoding="utf-8").splitlines():
        tokens = line.split()
        if tokens and tokens[0].lower() == name.lower():
            return tokens
    raise SystemExit(f"deck has no element {name}")


@lru_cache(maxsize=None)
def _sources() -> dict[str, dict]:
    """role -> the artefact that fixes its value, with the numbers recomputed."""
    mag = _json(MAG)
    ct = _json(BOM / "ct_design.json")
    cout = _json(BOM / "cout_bank.json")
    crb = _json(BOM / "cr_bank.json")["requirements"]
    cin = _json(BOM / "cin_bank.json")
    burden = _json(BOM / "oc_burden_pulse.json")

    bank = cout["banks"][0]
    burden_run = burden["results"]["runs"][0]
    as_built = ct["as_built"]
    # One freeze, one source: the manufacturing page picks the Lr core and turn
    # count through the same helper, so the join cannot quote a different part.
    lr = frozen_lr_core()
    lr_tank, lr_turn = lr["tank"], lr["turn"]

    cf = _si(deck_element("Cf")[3])
    rf = _si(deck_element("Rf")[3])
    rd1 = _si(deck_element("Rd1")[3])
    rd2 = _si(deck_element("Rd2")[3])
    drive = re.search(r"8\.7,3\.1", LIB.read_text(encoding="utf-8"))
    if not drive:
        raise SystemExit("the SR timing model no longer drives the gate through 8.7/3.1 ohm")
    deck = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
    lib = "models/sr_timing_v3_3.lib"

    def element(name: str) -> dict:
        tokens = deck_element(name)
        numbers: dict[str, float] = {}
        if len(tokens) > 3:
            try:
                numbers["si"] = _si(tokens[3])
            except ValueError:
                numbers["si"] = None  # a model name, e.g. Dbt aux hb DBOOT
        return {"source": f"{deck}:{name}",
                "value": " ".join(tokens[1:]),
                "numbers": numbers}

    return {
        "transformer winding": {
            "source": "design/v3/magnetics/magnetics_design.json:gap_mm",
            "value": f"centre-leg gap {mag['gap_mm']:.4f} mm from AL; Lm 10 uH, 3:1:1",
            "numbers": {"gap_mm": mag["gap_mm"]}},
        "resonant inductor": {
            "source": f"design/v3/bom/lr_design.json:catalogue_cores[{lr['id']}].turns + tank",
            "value": (f"external L {lr_tank['external_target_h'] * 1e6:.3f} uH = tank "
                      f"{lr_tank['total_target_h'] * 1e6:.3f} uH less the modelled "
                      f"{lr_tank['leakage_model_h'] * 1e6:.3f} uH leakage; {lr['id']} "
                      f"{lr_turn['turns']} turns, gap {lr_turn['gap_mm']:.4f} mm, "
                      f"Isat {lr_turn['isat_a_amin']:.1f} A (Amin)"),
            "numbers": {"external_h": lr_tank["external_target_h"],
                        "total_h": lr_tank["total_target_h"],
                        "gap_mm": lr_turn["gap_mm"], "isat_a": lr_turn["isat_a_amin"]}},
        "over-current CT": {
            "source": "design/v3/bom/ct_design.json:as_built",
            "value": (f"{as_built['turns_ratio']:.0f}:1, burden {as_built['burden_ohm']:.1f} ohm, "
                      f"trips at {as_built['trip_peak_a']:.3f} A peak"),
            "numbers": {"turns": as_built["turns_ratio"],
                        "trips_a": as_built["trip_peak_a"]}},
        "output capacitor bank": {
            "source": "design/v3/bom/cout_bank.json:banks[0]",
            "value": (f"{bank['n']} x {bank['part']} ({bank['governed_by']}-governed: "
                      f"cap {bank['counts']['capacitance']}, rms {bank['counts']['rms']}, "
                      f"esr {bank['counts']['esr']})"),
            "numbers": {"n": bank["n"], "esr_ohm": bank["bank_esr_ohm"]}},
        "resonant capacitor": {
            "source": "design/v3/bom/cr_bank.json:requirements",
            "value": (f"{crb['capacitance_f'] * 1e6:.2f} uF, v_max {crb['v_max_v']:.2f} V at the 120 A "
                      f"overload point ({crb['sizing_points']['rated_100a']['v_max_v']:.2f} V at the rated "
                      f"100 A), {crb['irms_a']:.2f} A RMS ({crb['sizing_points']['rated_100a']['i_rms_a']:.2f} A "
                      f"at 100 A), bank ESR <= {crb['esr_ceiling_ohm'] * 1e3:.2f} mohm "
                      f"({crb['sizing_points']['rated_100a']['esr_ceiling_ohm'] * 1e3:.2f} mohm at 100 A)"),
            "numbers": {"capacitance_f": crb["capacitance_f"], "v_max_v": crb["v_max_v"],
                        "esr_ceiling_ohm": crb["esr_ceiling_ohm"]}},
        "48 V input capacitor bank": {
            "source": "design/v3/bom/cin_bank.json:requirements",
            "value": (f"bridge AC RMS {cin['requirements']['bridge_ac_rms_a_at_worst_measured_load']:.4f} A "
                      f"at 200 kHz at the 120 A overload point "
                      f"({cin['requirements']['bridge_ac_rms_a_at_100a']:.4f} A at the rated 100 A); "
                      f"{cin['requirements']['ipri_peak_a']:.4f} A repetitive peak "
                      f"(not the 0.227 A through Cin, whose source impedance is 1 mohm)"),
            "numbers": {"bridge_ac_rms_a": cin["requirements"]["bridge_ac_rms_a_at_worst_measured_load"],
                        "bridge_ac_rms_a_at_100a": cin["requirements"]["bridge_ac_rms_a_at_100a"],
                        "ipri_peak_a": cin["requirements"]["ipri_peak_a"]}},
        "OC burden resistor": {
            "source": ("design/v3/bom/ct_design.json:as_built.burden_ohm + "
                       "oc_burden_pulse.json:runs[0]"),
            "value": (f"{as_built['burden_ohm']:.1f} ohm; {burden_run['pre_fault']['mean_w'] * 1e3:.1f} mW "
                      f"continuous, {burden_run['fault']['peak_w']:.3f} W / "
                      f"{burden_run['fault']['energy_mj']:.3f} mJ fault pulse"),
            "numbers": {"ohm": as_built["burden_ohm"],
                        "continuous_w": burden_run["pre_fault"]["mean_w"]}},
        "OC filter (Cf)": {
            "source": f"{deck}:Cf",
            "value": f"{cf * 1e9:.0f} nF, tau with Rf {rf:.0f} ohm = {rf * cf * 1e6:.1f} us",
            "numbers": {"farads": cf, "tau_s": rf * cf}},
        "OC filter series (Rf)": element("Rf"),
        "OC divider top (Rd1)": {
            "source": f"{deck}:Rd1",
            "value": f"{rd1:.0f} ohm, divider gain {as_built['divider_gain']:.4f}",
            "numbers": {"ohm": rd1, "divider_gain": as_built["divider_gain"]}},
        "OC divider bottom (Rd2)": element("Rd2"),
        "OC hold (Coc)": element("Coc"),
        "SS capacitor": element("Css"),
        "HB bootstrap": element("Cbt"),
        "bootstrap diode": element("Dbt"),
        "DT resistor": element("Rdt"),
        "RT resistor": element("Rrt"),
        "QH gate-source pull-down": element("RgsH"),
        "QL gate-source pull-down": element("RgsL"),
        "primary gate resistor": {
            "source": f"{deck}:Rgh,Rgl (3.2 ohm lumped)",
            "value": "2.2 ohm external; the deck's 3.2 ohm lump = UCC27282 1.3/0.85 + 2.2",
            "numbers": {"external_ohm": 2.2}},
        "SR gate resistor": {
            "source": f"{lib}:150 (8.7/3.1 ohm drive)",
            "value": "2.2 ohm external; 6.5/0.9 ohm UCC24624 + 2.2 = the model's 8.7/3.1",
            "numbers": {"drive_on_ohm": 8.7, "drive_off_ohm": 3.1, "external_ohm": 2.2}},
    }


# ---------------------------------------------------------------- ECO batch
#
# The review asked to apply the standard-device batch to the one native
# project rather than update a CSV and leave the board on its old parts.  That
# needs three facts per row and none of them may be guessed:
#
#   * what the board holds now -- ``gen/native_inventory_raw.json``, a read-only
#     dump of the running editor (Value, footprint name, library device);
#   * what it must hold        -- a deck element, the register's frozen number,
#     or PERIPHERALS for the 17 the deck does not model;
#   * whether that is a value change or a device change.
#
# A value change touches only ``otherProperty.Value``.  The library device is
# what a BOM export emits, so the edit leaves it in place -- recorded as a
# residual risk below, not glossed over.
ECO_EXECUTOR = {
    "ALREADY_CONFORMS": "NONE_BOARD_MPN_ONLY",
    "NATIVE_VALUE_EDIT": "TOOL_NATIVE_VALUE_ECO",
    "NATIVE_DEVICE_CHANGE": "GUI_DEVICE_SWAP",
}

# refs whose target value the SPICE deck models by name, so the number is read
# off the deck rather than retyped here
DECK_BACKED = {
    "R1": "Rdt", "R2": "Rrt", "R3": "Rbur", "R15": "Rf", "R16": "Rd1",
    "R17": "Rd2", "R18": "RgsH", "R19": "RgsL",
    "C5": "Cbt", "C6": "Css", "C11": "Cf", "C12": "Coc",
}

# target values with neither a deck element nor a schematic entry: the number
# is the register's frozen value and no computed artefact fixes it
FIXED: dict[str, tuple[float, str]] = {"R4": (2.2, "ohm"), "R5": (2.2, "ohm")}
for _ref in (f"R{i}" for i in range(20, 28)):
    FIXED[_ref] = (2.2, "ohm")  # SR gate resistor, external
for _ref in (f"R{i}" for i in range(28, 36)):
    FIXED[_ref] = (0.0, "ohm")  # SR drain Kelvin link
for _ref in ("C7", "C8", "C9", "C10"):
    FIXED[_ref] = (2.2e-6, "farad")  # UCC24624 REG capacitor per its datasheet
del _ref

# refs whose package or device is wrong whatever the value is.  A value edit
# cannot fix these: the placed library device is the orderable part.
DEVICE = {
    "C5": ("0805", "220 nF >= 25 V bootstrap capacitor; the 0603 placeholder cannot hold the value"),
    "R3": ("0805 or larger",
           "10 ohm burden dissipates 125.7 mW continuous = 100.6 % of a 0.125 W 0805 "
           "before derating, so the resistance stays frozen and the package must move"),
    "Cin": ("48 V bank", "the board carries one 0603 symbol for the whole input bank"),
    "Cout": ("polymer SMD bank", "the board carries one 0603 symbol for fifteen 470 uF parts"),
    "Cr": ("film", "0.62 uF film bank; the 0603 placeholder is not a film part"),
    "D_BT": ("SOD-323", ">=100 V standoff: the placed BAT54WS is a 30 V part"),
    "Lr": ("ELP38", "custom 2-turn ELP38 inductor; no 10 mm SMD inductor holds 1.0 uH at 84 A"),
    "CT": ("4-terminal custom", "current transformer; the present two-pad footprint is invalid"),
    "T1": ("ELP32 3:1:1", "custom wound transformer on the ELP32 kit"),
    "T2": ("ELP32 3:1:1", "custom wound transformer on the ELP32 kit"),
    "T3": ("ELP32 3:1:1", "custom wound transformer on the ELP32 kit"),
    "T4": ("ELP32 3:1:1", "custom wound transformer on the ELP32 kit"),
}

SIZE_CODES = ("0201", "0402", "0603", "0805", "1206", "1210", "2010", "2512")


@lru_cache(maxsize=None)
def _native() -> dict[str, dict]:
    """ref -> the live board's own reading, straight out of the inventory dump."""
    if not INVENTORY.is_file():
        raise SystemExit(
            f"{INVENTORY} is missing: run hardware/dcx_main/gen/read_native_inventory.js "
            "against the native project (read-only; the header of that file has the two CLI calls)")
    value = _json(INVENTORY).get("value") or {}
    if value.get("status") != "INVENTORY":
        raise SystemExit(f"{INVENTORY} is not an inventory dump: {value.get('status')!r}")
    return {c["ref"]: c for c in value["components"]}


def package_code(name: str | None) -> str | None:
    """Chip size code of a footprint name; anything else compares verbatim.

    The native board names footprints ``R0603``/``C0603`` while the register
    writes ``0603``, so the size code is the comparable part.
    """
    if not name:
        return None
    for code in SIZE_CODES:
        if code in name:
            return code
    return name


def display(si: float, quantity: str) -> str:
    """Write a value in the native project's own style: ``5.36kΩ``, ``220nF``."""
    def trim(x: float) -> str:
        return f"{x:.6g}"

    if quantity == "ohm":
        return f"{trim(si / 1e3)}kΩ" if abs(si) >= 1e3 else f"{trim(si)}Ω"
    if abs(si) >= 1e-6:
        return f"{trim(si / 1e-6)}uF"
    return f"{trim(si / 1e-9)}nF"


def target(ref: str, role: str) -> dict:
    """What the board must hold at ``ref``: SI value, style, package and source."""
    value_si: float | None = None
    source = ""

    if ref in DECK_BACKED:
        element = DECK_BACKED[ref]
        value_si = _si(deck_element(element)[3])
        source = f"{DECK.name}:{element}"
    elif ref in FIXED:
        value_si = FIXED[ref][0]
        source = "component_decision_register.json (frozen value, no computed artefact)"
    elif ref in schematic.PERIPHERALS:
        part = schematic.PERIPHERALS[ref]
        value_si = schematic_si(part["value"])
        source = "tools/main_board_schematic.py:PERIPHERALS"

    package, why = DEVICE.get(ref, (None, ""))
    if package and not source:
        source = "component_decision_register.json (device, not a value)"
    quantity = "ohm" if ref.startswith("R") else "farad"
    return {
        "value_si": value_si,
        "value": None if value_si is None else display(value_si, quantity),
        "package": package,
        "why": why or source,
        "source": source,
    }


def eco(ref: str, role: str) -> dict:
    """Classify one ref against the live board and write its acceptance test."""
    native = _native().get(ref, {})
    footprint = (native.get("footprint") or {}).get("name") or None
    device = (native.get("component") or {}).get("name") or None
    native_si = schematic_si(native.get("value"))
    want = target(ref, role)

    if want["package"] and package_code(want["package"]) != package_code(footprint):
        klass = "NATIVE_DEVICE_CHANGE"
    elif want["value_si"] is None or native_si is None:
        klass = "NATIVE_DEVICE_CHANGE"
    elif abs(want["value_si"] - native_si) <= 1e-9 * max(1.0, abs(want["value_si"])):
        klass = "ALREADY_CONFORMS"
    else:
        klass = "NATIVE_VALUE_EDIT"

    acceptance = {
        "ALREADY_CONFORMS":
            f"no edit: the board already reads {native.get('value')} ({device}); "
            f"only the BOM MPN is open",
        "NATIVE_VALUE_EDIT":
            f"re-run gen/read_native_inventory.js and require Value {want['value']} "
            f"with the LCSC Part Name unchanged ({device})",
        "NATIVE_DEVICE_CHANGE":
            f"the package/device must be swapped in the editor (a value edit cannot do it); "
            f"accept when the inventory shows {want['package']}",
    }[klass]
    risk = {
        "ALREADY_CONFORMS": "the placed device and its MPN stay the register's open item",
        "NATIVE_VALUE_EDIT":
            f"the library device stays {device}, so the BOM still lists that part: the value "
            f"edit moves what is printed on the board and in the schematic, not what is ordered",
        "NATIVE_DEVICE_CHANGE":
            "not executable through the editor API: the swap is a GUI step, then re-inventory",
    }[klass]

    return {
        "native_value": native.get("value"),
        "native_value_si": native_si,
        "native_package": footprint,
        "native_device": device,
        "target_value": want["value"],
        "target_value_si": want["value_si"],
        "target_package": want["package"],
        "eco_target_source": want["why"],
        "eco_class": klass,
        "eco_executor": ECO_EXECUTOR[klass],
        "eco_acceptance": acceptance,
        "placed_device_unchanged": klass != "NATIVE_DEVICE_CHANGE",
        "eco_residual_risk": risk,
    }


def requirement(ref: str, role: str) -> dict | None:
    if role in PERIPHERAL_ROLES:
        part = schematic.PERIPHERALS.get(ref)
        if part is None:
            return None
        pads = ",".join(f"{pin}={net}" for pin, net in part["pads"].items())
        return {"source": "tools/main_board_schematic.py:PERIPHERALS",
                "value": f"{part['value']} on {pads}",
                "numbers": {}}
    return _sources().get(role)


@lru_cache(maxsize=None)
def golden_refs() -> frozenset[str]:
    rows = csv.DictReader(GOLDEN.open(encoding="utf-8"))
    return frozenset(r["ref"] for r in rows)


@lru_cache(maxsize=None)
def pin_review() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for row in csv.DictReader(PIN_REVIEW.open(encoding="utf-8")):
        by.setdefault(row["ref"], []).append(row)
    return by


def review_status(ref: str) -> tuple[str, list[str]]:
    rows = pin_review().get(ref)
    if not rows:
        return "MISSING", []
    open_pins = [f"{r['golden_pin'] or r['pad']}" for r in rows if r["review_status"] == OPEN]
    if open_pins:
        return "OPEN", open_pins
    if all(r["review_status"] != "MAPPED" for r in rows):
        return "BONDED BY DESIGN", []
    return "MAPPED", []


def next_action(ref: str, role: str, status: str, blocked_on: str, traced: bool) -> str:
    if blocked_on == "MAGNETIC_PHYSICAL_TERMINAL_DRAWING":
        return (f"obtain the manufacturer physical terminal drawing and pad map, then fill "
                f"physical_pad in hardware/dcx_main/rfq/{ref}.md (currently NOT AVAILABLE); "
                f"do not invent pad numbers")
    if not traced:
        return ("no computed requirement exists in this repository: record the requirement (or "
                "why none is needed) before selecting a part, or a purchase cannot be checked")
    if status == "OPEN":
        return f"resolve the open footprint review rows for {ref} in pin_footprint_review.csv first"
    return ("select a purchasable part meeting the stated requirement, then record verified_mpn, "
            "manufacturer_datasheet and eda_footprint_verified in the register")


def rows() -> list[dict]:
    register = _json(REGISTER)["items"]
    gold = golden_refs()
    peripherals = set(schematic.PERIPHERALS)
    out = []
    for item in register:
        ref, role = item["ref"], item["part_role"]
        governed = "GOLDEN_NETLIST" if ref in gold else (
            "SCHEMATIC_PERIPHERAL" if ref in peripherals else "UNGOVERNED")
        status, open_pins = review_status(ref)
        traced = requirement(ref, role)
        blocked = ("MAGNETIC_PHYSICAL_TERMINAL_DRAWING" if role in MAGNETIC_ROLES
                   else "MANUFACTURER_EVIDENCE")
        out.append({
            "ref": ref,
            "priority": item["priority"],
            "part_role": role,
            "existing_value_or_rating": item["existing_value_or_rating"],
            "current_package": item["current_package"],
            "netlist_governance": governed,
            "native_pin_review": status,
            "native_pin_review_scope": ("LOGICAL_TERMINAL_NAME_ONLY" if role in MAGNETIC_ROLES
                                        else "PIN_TO_PAD"),
            "native_open_pins": open_pins,
            "requirement_source": traced["source"] if traced else None,
            "requirement": traced["value"] if traced else None,
            "requirement_numbers": traced["numbers"] if traced else None,
            "untraced_reason": None if traced else UNTRACED.get(role, "no requirement artefact"),
            "blocked_on": blocked,
            "next_action": next_action(ref, role, status, blocked, traced is not None),
            "decision_owner": item["decision_owner"],
            "reviewer": item["reviewer"],
            "verified_mpn": item["verified_mpn"],
            **eco(ref, role),
        })
    return out


def build() -> dict:
    rs = rows()
    counts: dict[str, object] = {
        "placeholders": len(rs),
        "by_priority": {},
        "by_netlist_governance": {},
        "by_blocked_on": {},
        "by_native_pin_review": {},
        "by_eco_class": {},
        "traced_requirements": sum(1 for r in rs if r["requirement_source"]),
        "untraced_requirements": sum(1 for r in rs if not r["requirement_source"]),
        "with_decision_owner": sum(1 for r in rs if r["decision_owner"]),
        "with_verified_mpn": sum(1 for r in rs if r["verified_mpn"]),
    }
    for key, bucket in (("priority", "by_priority"),
                        ("netlist_governance", "by_netlist_governance"),
                        ("blocked_on", "by_blocked_on"),
                        ("native_pin_review", "by_native_pin_review"),
                        ("eco_class", "by_eco_class")):
        for row in rs:
            counts[bucket][row[key]] = counts[bucket].get(row[key], 0) + 1

    refs = [r["ref"] for r in rows()]
    checks = {
        "one_row_per_register_item": len(rs) == len(_json(REGISTER)["items"]) == 61,
        "refs_match_the_register": refs == [i["ref"] for i in _json(REGISTER)["items"]],
        "every_ref_has_exactly_one_netlist_governance": all(
            r["netlist_governance"] in ("GOLDEN_NETLIST", "SCHEMATIC_PERIPHERAL") for r in rs),
        "no_ref_appears_in_both_netlist_sources": not (golden_refs() & set(schematic.PERIPHERALS)),
        "every_ref_has_a_native_pin_review_row": all(r["native_pin_review"] != "MISSING" for r in rs),
        "every_row_states_a_requirement_or_a_reason": all(
            r["requirement_source"] or r["untraced_reason"] for r in rs),
        "every_untraced_row_asks_for_a_requirement_before_a_purchase": all(
            "no computed requirement exists" in r["next_action"]
            for r in rs if not r["requirement_source"]),
        "every_magnetic_row_has_an_rfq_sheet_that_still_says_not_available": all(
            (RFQ / f"{r['ref']}.md").is_file()
            and "NOT AVAILABLE" in (RFQ / f"{r['ref']}.md").read_text(encoding="utf-8")
            for r in rs if r["blocked_on"] == "MAGNETIC_PHYSICAL_TERMINAL_DRAWING"),
        "no_row_claims_a_verified_mpn": all(r["verified_mpn"] is None for r in rs),
        "no_magnetic_row_is_presented_as_a_verified_physical_pinout": all(
            r["native_pin_review_scope"] == "LOGICAL_TERMINAL_NAME_ONLY"
            for r in rs if r["blocked_on"] == "MAGNETIC_PHYSICAL_TERMINAL_DRAWING"),
        "every_row_carries_a_next_action": all(r["next_action"].strip() for r in rs),
        "every_row_is_classified_against_the_live_board": all(
            r["eco_class"] in ECO_EXECUTOR and r["eco_executor"] == ECO_EXECUTOR[r["eco_class"]]
            for r in rs),
        "a_value_edit_never_targets_the_value_the_board_already_has": all(
            abs(r["target_value_si"] - r["native_value_si"])
            > 1e-9 * max(1.0, abs(r["target_value_si"]))
            for r in rs if r["eco_class"] == "NATIVE_VALUE_EDIT"),
        "a_row_whose_package_changes_is_never_a_value_edit": all(
            r["eco_class"] == "NATIVE_DEVICE_CHANGE" for r in rs
            if r["target_package"] and package_code(r["target_package"]) != package_code(r["native_package"])),
        "no_row_claims_the_placed_device_changes_when_only_its_value_does": all(
            r["placed_device_unchanged"] is (r["eco_class"] != "NATIVE_DEVICE_CHANGE") for r in rs),
    }
    return {"status": STATUS, "counts": counts, "checks": checks, "rows": rs}


def to_csv(rs: list[dict]) -> str:
    columns = ["ref", "priority", "part_role", "netlist_governance", "native_pin_review",
               "native_pin_review_scope", "native_open_pins",
               "eco_class", "eco_executor", "native_value", "native_package", "native_device",
               "target_value", "target_package", "eco_acceptance", "eco_residual_risk",
               "requirement_source", "requirement", "blocked_on", "next_action",
               "decision_owner", "reviewer", "verified_mpn"]
    lines = [",".join(columns)]
    for row in rs:
        cells = []
        for column in columns:
            value = row[column]
            text = "" if value is None else (
                "|".join(value) if isinstance(value, list) else str(value))
            cells.append('"' + text.replace('"', '""') + '"' if any(c in text for c in ',"') else text)
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def write(rs: list[dict]) -> list[tuple[Path, str]]:
    built = build()
    payload = json.dumps(built, ensure_ascii=False, indent=2) + "\n"
    table = to_csv(rs)
    OUT_JSON.write_text(payload, encoding="utf-8", newline="")
    OUT_CSV.write_text(table, encoding="utf-8", newline="")
    return [(OUT_JSON, payload), (OUT_CSV, table)]


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    built = build()
    counts = built["counts"]
    print(f"placeholders: {counts['placeholders']}  "
          f"traced: {counts['traced_requirements']}  "
          f"untraced: {counts['untraced_requirements']}")
    print(f"netlist governance: {counts['by_netlist_governance']}")
    print(f"blocked on: {counts['by_blocked_on']}")
    print(f"native pin review: {counts['by_native_pin_review']}")
    print(f"ECO class: {counts['by_eco_class']}")
    print(f"owners assigned: {counts['with_decision_owner']}  "
          f"verified MPNs: {counts['with_verified_mpn']}")
    if "--write" in args:
        write(built["rows"])
        print(f"wrote {OUT_JSON.name} and {OUT_CSV.name}")
    failed = [name for name, ok in built["checks"].items() if not ok]
    if failed:
        print("CHECKS FAILED: " + ", ".join(failed))
        return 1
    print("all structural checks pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
