"""Generate the terminal-level DOT map for T1-T4 and the first-article record.

`board_netlist.winding_layout()` proves the deck, the board pin map and the
coupling coefficients agree.  This tool turns that proof into two shop-floor
artefacts so the polarity is not re-derived from prose:

    design/v3/magnetics/winding_polarity.json          machine-readable map
    design/v3/magnetics/winding_polarity.csv           terminal list (one row each)
    design/v3/magnetics/first_article_polarity_record.csv   blank measurement sheet

The internal 3-turn primary is included because the deck models it as one 10 uH
inductor: P1_OUT -> P2_IN and P2_OUT -> P3_IN are construction jumpers, not board
pins.  Each turn's DOT is its start, so series-aiding means non-dot end of turn N
meets dot end of turn N+1.  The secondary is one turn per half; CTAP is S_A's DOT
and S_B's NON-dot (see the module docstring in board_netlist.py for the SPICE rule).

Usage:
    python tools/winding_polarity.py --out design/v3/magnetics
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

from board_netlist import NODE_NET, ROOT, winding_layout

OUT = ROOT / "design/v3/magnetics"


def terminal_rows(report: dict[str, object]) -> list[dict[str, str]]:
    """One row per physical terminal, including the internal primary turn joins."""
    rows: list[dict[str, str]] = []
    for name, transformer in report["transformers"].items():
        primary = transformer["primary"]
        for turn in (1, 2, 3):
            start = f"P{turn}_IN"
            end = f"P{turn}_OUT"
            rows.append({
                "transformer": name, "terminal": start, "winding": "PRIMARY",
                "dot": "DOT", "deck_node": "", "deck_pin": "",
                "board_net": "",
                "connects_to": ("overall primary DOT (= PRI_A)" if turn == 1
                                else f"P{turn - 1}_OUT"),
            })
            rows.append({
                "transformer": name, "terminal": end, "winding": "PRIMARY",
                "dot": "NON-DOT", "deck_node": "", "deck_pin": "",
                "board_net": "",
                "connects_to": ("overall primary NON-DOT (= PRI_B)" if turn == 3
                                else f"P{turn + 1}_IN"),
            })
        # The two endpoints are the only primary terminals that reach the board;
        # attach the deck/board provenance to each turn-1 start and turn-3 end.
        for row in rows[-6:]:
            if row["transformer"] != name:
                continue
            if row["terminal"] == "P1_IN":
                row["deck_node"] = primary["dot_node"]
                row["deck_pin"] = primary["dot_pin"]
                row["board_net"] = NODE_NET.get(primary["dot_node"], "")
            if row["terminal"] == "P3_OUT":
                row["deck_node"] = primary["non_dot_node"]
                row["deck_pin"] = primary["non_dot_pin"]
                row["board_net"] = NODE_NET.get(primary["non_dot_node"], "")

        a, b = transformer["secondary_a"], transformer["secondary_b"]
        rows.append({
            "transformer": name, "terminal": "CTAP", "winding": "SECONDARY",
            "dot": "S_A DOT / S_B NON-DOT", "deck_node": a["dot_node"],
            "deck_pin": " / ".join(sorted({a["dot_pin"], b["non_dot_pin"]})),
            "board_net": NODE_NET.get(a["dot_node"], ""),
            "connects_to": "S_A start and S_B finish (one copper terminal)",
        })
        rows.append({
            "transformer": name, "terminal": "SEC_A", "winding": "SEC_A",
            "dot": "NON-DOT", "deck_node": a["non_dot_node"],
            "deck_pin": a["non_dot_pin"],
            "board_net": NODE_NET.get(a["non_dot_node"], ""),
            "connects_to": "S_A finish",
        })
        rows.append({
            "transformer": name, "terminal": "SEC_B", "winding": "SEC_B",
            "dot": "DOT", "deck_node": b["dot_node"],
            "deck_pin": b["dot_pin"],
            "board_net": NODE_NET.get(b["dot_node"], ""),
            "connects_to": "S_B start",
        })
    return rows


def first_article_rows(report: dict[str, object]) -> list[dict[str, str]]:
    """Blank first-article record: expected results only, measurements left open."""
    rows: list[dict[str, str]] = []
    for name in report["transformers"]:
        rows += [
            {"transformer": name, "test": "S_A polarity vs CTAP",
             "excitation": "1 kHz, 1 Vpp square through 100 ohm into PRI_A-PRI_B; "
                           "SR MOSFETs not fitted",
             "expected": "V(SEC_A-CTAP) in phase with V(PRI_A-PRI_B)",
             "measured": "", "pass": "", "operator": "", "date": "", "note": ""},
            {"transformer": name, "test": "S_B polarity vs CTAP",
             "excitation": "same drive; probe V(SEC_B-CTAP)",
             "expected": "V(SEC_B-CTAP) in anti-phase (180 deg) with V(PRI_A-PRI_B)",
             "measured": "", "pass": "", "operator": "", "date": "", "note": ""},
            {"transformer": name, "test": "S_A turns ratio",
             "excitation": "same drive; measure both windings with differential probe",
             "expected": "|V(SEC_A-CTAP)| / |V(PRI_A-PRI_B)| = 1/3, +/-5 %",
             "measured": "", "pass": "", "operator": "", "date": "", "note": ""},
            {"transformer": name, "test": "S_B turns ratio",
             "excitation": "same drive; probe V(SEC_B-CTAP)",
             "expected": "|V(SEC_B-CTAP)| / |V(PRI_A-PRI_B)| = 1/3, +/-5 %",
             "measured": "", "pass": "", "operator": "", "date": "", "note": ""},
        ]
    for i in (1, 2, 3):
        rows.append({
            "transformer": f"T{i}->T{i + 1}",
            "test": "primary series phase",
            "excitation": "1 kHz, 1 Vpp across the series string; probe each unit",
            "expected": "V(T{i+1} PRI_A-PRI_B) in phase with V(T{i} PRI_A-PRI_B)",
            "measured": "", "pass": "", "operator": "", "date": "", "note": "",
        })
    return rows


def build(path: Path | None = None) -> dict[str, object]:
    report = winding_layout() if path is None else winding_layout(path)
    rows = terminal_rows(report)
    return {
        "deck": report["deck"],
        "convention": report["convention"],
        "ok": report["ok"],
        "checks": report["checks"],
        "ctap_definition": "CTAP = S_A DOT = S_B NON-DOT",
        "primary_series_order": ["T1", "T2", "T3", "T4"],
        "transformers": report["transformers"],
        "terminals": rows,
        "first_article": first_article_rows(report),
    }


def _csv_text(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write(out: Path = OUT) -> None:
    payload = build()
    out.mkdir(parents=True, exist_ok=True)
    (out / "winding_polarity.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "winding_polarity.csv").write_text(_csv_text(payload["terminals"]), encoding="utf-8")
    (out / "first_article_polarity_record.csv").write_text(
        _csv_text(payload["first_article"]), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    write(args.out)
    payload = build()
    print(f"wrote {args.out}: {len(payload['terminals'])} terminals, "
          f"{len(payload['first_article'])} first-article checks, polarity ok={payload['ok']}")
    if not payload["ok"]:
        raise SystemExit("polarity checks failed")


if __name__ == "__main__":
    main()
