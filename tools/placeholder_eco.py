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

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
BOM = ROOT / "design/v3/bom"
MAG = ROOT / "design/v3/magnetics/magnetics_design.json"
DECK = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
LIB = ROOT / "models/sr_timing_v3_3.lib"
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
REGISTER = HW / "component_decision_register.json"
PIN_REVIEW = HW / "pin_footprint_review.csv"
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
    lr = _json(BOM / "lr_design.json")
    ct = _json(BOM / "ct_design.json")
    cout = _json(BOM / "cout_bank.json")
    cr = _json(BOM / "cr_stress.json")
    passive = _json(BOM / "passive_requirements.json")
    burden = _json(BOM / "oc_burden_pulse.json")

    bank = cout["banks"][0]
    burden_run = burden["results"]["runs"][0]
    three = next(c for c in lr["candidates"] if c["turns"] == 3)
    as_built = ct["as_built"]

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
            "source": "design/v3/bom/lr_design.json:tank,candidates[3 turns]",
            "value": (f"tank total {lr['tank']['total_target_h'] * 1e6:.3f} uH external, "
                      f"3 turns, gap {three['gap_mm']:.4f} mm, Isat {three['isat_a']:.1f} A"),
            "numbers": {"total_h": lr["tank"]["total_target_h"],
                        "gap_mm": three["gap_mm"], "isat_a": three["isat_a"]}},
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
            "source": "design/v3/bom/cr_stress.json",
            "value": (f"{cr['capacitance_f'] * 1e6:.2f} uF, v_max {cr['v_max_v']:.2f} V, "
                      f"{cr['i_rms_a']:.2f} A RMS, bank ESR <= {cr['esr_ceiling_ohm'] * 1e3:.2f} mohm"),
            "numbers": {"capacitance_f": cr["capacitance_f"], "v_max_v": cr["v_max_v"],
                        "esr_ceiling_ohm": cr["esr_ceiling_ohm"]}},
        "48 V input capacitor bank": {
            "source": "design/v3/bom/passive_requirements.json:cin",
            "value": (f"bridge AC RMS {passive['cin']['bridge_ac_rms_a']:.4f} A at 200 kHz "
                      f"(not the 0.227 A through Cin, whose source impedance is 1 mohm)"),
            "numbers": {"bridge_ac_rms_a": passive["cin"]["bridge_ac_rms_a"]}},
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
        "traced_requirements": sum(1 for r in rs if r["requirement_source"]),
        "untraced_requirements": sum(1 for r in rs if not r["requirement_source"]),
        "with_decision_owner": sum(1 for r in rs if r["decision_owner"]),
        "with_verified_mpn": sum(1 for r in rs if r["verified_mpn"]),
    }
    for key, bucket in (("priority", "by_priority"),
                        ("netlist_governance", "by_netlist_governance"),
                        ("blocked_on", "by_blocked_on"),
                        ("native_pin_review", "by_native_pin_review")):
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
    }
    return {"status": STATUS, "counts": counts, "checks": checks, "rows": rs}


def to_csv(rs: list[dict]) -> str:
    columns = ["ref", "priority", "part_role", "netlist_governance", "native_pin_review",
               "native_pin_review_scope", "native_open_pins", "requirement_source",
               "requirement", "blocked_on", "next_action", "decision_owner", "reviewer",
               "verified_mpn"]
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
