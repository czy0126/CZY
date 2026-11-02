"""The ledger's loss inventory must cover every dissipative element in the deck.

ELE-09 left the 50 V/120 A +0.49 W gap open with "trace the physical source".
Before a missing element can be blamed, the deck has to be exhausted: every
``Rser=``, every standalone resistor and every conduction resistance in a
``.model`` line is either measured by a loss term or excluded for a stated
reason.  Adding a dissipative element without updating the inventory must fail
here, and so must changing a resistance the tool reads from a module constant
instead of from the deck.
"""
from __future__ import annotations

import re
from pathlib import Path

import energy_ledger_100a as led

ROOT = Path(__file__).resolve().parent.parent
DECKS = [
    "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir",
    "sim/v3/sr_tank_dual_v33_ss_1ms_vin50_i120_cin.cir",
]

# How each dissipative element is handled by ``loss_terms()``.
COVERAGE = {
    "Rin": "rin",
    "Cr": "cr_esr",
    "Cout": "cout_esr",
    "Lr": "lr",
    "Lp1": "lp_series", "Lp2": "lp_series", "Lp3": "lp_series", "Lp4": "lp_series",
    "Lsa1": "secondary_copper", "Lsb1": "secondary_copper",
    "Lsa2": "secondary_copper", "Lsb2": "secondary_copper",
    "Lsa3": "secondary_copper", "Lsb3": "secondary_copper",
    "Lsa4": "secondary_copper", "Lsb4": "secondary_copper",
    "Rbur": "ct_burden_resistor",
    "Rload": "pout",
    # Excluded, with the bound that makes the exclusion safe:
    "Cin": "excluded: 5 mOhm, I(Cin) ac rms 0.349 A measured -> 0.6 mW",
    "Cbt": "excluded: only V(hb,sw) is read; no charge is drawn from it",
    "Rgh": "excluded: driven by an ideal B-source, not by the port",
    "Rgl": "excluded: driven by an ideal B-source, not by the port",
    "RgsH": "excluded: driven by an ideal B-source, not by the port",
    "RgsL": "excluded: driven by an ideal B-source, not by the port",
    "Rdt": "excluded: supplied by Vaux",
    "Rrt": "excluded: supplied by Vaux",
    "Rss_dc": "excluded: 1 GOhm",
    "Rf": "excluded: OC filter carries ~20 uA dc -> 14 uW",
    "Rd1": "excluded: OC filter carries ~20 uA dc",
    "Rd2": "excluded: OC filter carries ~20 uA dc",
}

_ELEMENT = re.compile(r"^(R\w+|C\w+|L\w+)\s+\S+\s+\S+\s+(\S+)(.*)$")
_MODEL_RON = re.compile(r"R(on|s)?=([0-9.]+[mun]?)", re.IGNORECASE)


def ohms(text: str) -> float:
    suffix = {"": 1.0, "m": 1e-3, "u": 1e-6, "n": 1e-9}
    return float(text[:-1]) * suffix[text[-1]] if text[-1].isalpha() else float(text)


def resistive_elements(path: Path) -> dict[str, str]:
    """Map every element that can dissipate conduction loss to its Rser/value."""
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in "*.+" or line.startswith(".model"):
            continue
        m = _ELEMENT.match(line)
        if not m:
            continue
        name, value, rest = m.groups()
        rser = re.search(r"Rser=([0-9.]+[mun]?)", rest)
        if name.startswith("R"):
            found[name] = value
        elif rser:
            found[name] = rser.group(1)
    return found


def model_ron(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith(".model"):
            parts = line.split()
            m = _MODEL_RON.search(line)
            if len(parts) >= 2 and m:
                out[parts[1]] = m.group(2)
    return out


def test_every_dissipative_element_is_in_the_inventory() -> None:
    for deck in DECKS:
        found = resistive_elements(ROOT / deck)
        missing = sorted(set(found) - set(COVERAGE))
        assert not missing, f"{deck}: unmapped dissipative element(s) {missing}"


def test_the_tool_constants_match_the_deck_they_describe() -> None:
    deck = ROOT / DECKS[1]
    found = resistive_elements(deck)
    assert ohms(found["Rin"]) == led.RIN
    assert ohms(found["Lr"]) == led.R_LR
    assert ohms(found["Lp1"]) == led.R_LP
    assert ohms(found["Cr"]) == led.R_CR
    assert ohms(found["Cout"]) == led.R_COUT
    assert ohms(found["Lsa1"]) == led.R_SEC
    assert ohms(model_ron(deck)["PRI_SW"]) == led.RON_PRI
