"""The cold-overload convergence comparison must not compare different circuits.

``cold_oc_convergence`` exists to answer one question: does the cshunt aid let
the 8 ms fault run finish without changing the fault physics?  These tests pin
the three ways that answer could be faked: a circuit edit hidden in the
"variant", a stalled base counted as complete, or a comparison window that the
base never reached.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cold_oc_convergence import compare

DECK = """* synthetic cold-overload deck
.options plotwinsize=0 method=gear
Vfltctl ctl 0 PWL(0 0 5.5m 0 5.6m 5 8m 5)
Sflt out flt ctl 0 SFLT
Rflt flt 0 1m
Rload out sgnd 15.4m
.tran 0 8m 0 10n uic
.end
"""


def write_raw(path: Path, points: list[tuple[float, float, float, float, float, float]]) -> None:
    """Structurally exact ASCII raw for the five traces this tool reads."""
    names = ["V(oc)", "I(Lr)", "V(out)", "I(VSa1)", "I(VSb1)"]
    lines = [
        "Title: synthetic\n",
        "No. Variables: 6\n",
        f"No. Points: {len(points)}\n",
        "Variables:\n",
        "\t0\ttime\ttime\n",
    ]
    for i, name in enumerate(names, 1):
        lines.append(f"\t{i}\t{name}\tvoltage\n")
    lines.append("Values:\n")
    for k, (t, voc, ilr, vout, isa1, isb1) in enumerate(points):
        lines.append(f"{k}\t\t{t:.12e}\n")
        for value in (voc, ilr, vout, isa1, isb1):
            lines.append(f"\t{value:.12e}\n")
    path.write_text("".join(lines), encoding="latin-1")


def fault_points(end_us: float) -> list[tuple[float, float, float, float, float, float]]:
    """A clean fault: engage 5.55 ms, 84 A peak, V(oc) trips at 5.59 ms.

    The body-diode traces are negative in this deck (same convention as the
    published record), so their max forward value is 60 A.
    """
    out = []
    t_us = 5400.0
    while t_us < end_us:
        t = t_us * 1e-6
        voc = 0.70 if t < 5.59e-3 else 1.20
        ilr = 50.0 + 34.0 * max(0.0, 1.0 - abs(t - 5.58e-3) / 0.03e-3)
        vout = 1.80 - 0.90 * max(0.0, 1.0 - abs(t - 5.58e-3) / 0.03e-3)
        isa1 = -60.0 if 5.57e-3 <= t < 5.60e-3 else -1.0
        isb1 = -5.0
        out.append((t, voc, ilr, vout, isa1, isb1))
        t_us += 0.4
    return out


def test_a_stalled_base_and_a_completed_variant_are_reported_as_such(tmp_path: Path):
    base = tmp_path / "base.raw"
    variant = tmp_path / "variant.raw"
    base_deck = tmp_path / "base.cir"
    variant_deck = tmp_path / "variant.cir"
    base_deck.write_text(DECK, encoding="utf-8")
    variant_deck.write_text(
        DECK.replace(".options plotwinsize=0 method=gear",
                     ".options plotwinsize=0 method=gear cshunt=1e-15"),
        encoding="utf-8",
    )
    write_raw(base, fault_points(5900.0))
    # The aid's run reaches the deck stop; its final record is the proof.
    write_raw(variant, fault_points(6000.0) + [(8e-3, 0.0, 0.0, 0.0, 0.0, 0.0)])
    record = compare(base, base_deck, variant, variant_deck)
    assert record["checks"]["the_two_decks_differ_only_on_solver_settings"] is True
    # The stalled base caps both reads at 5.9 ms, so the declared 6.0 ms slice
    # is not covered -- and the absence is reported rather than hidden.
    assert record["checks"]["the_comparison_window_is_covered_by_both_raws"] is False
    assert record["results"]["declared_window_fully_covered"] is False
    assert record["results"]["window_end_us"] == pytest.approx(5900.0, abs=0.05)
    assert record["results"]["declared_window_end_us"] == pytest.approx(6000.0)
    assert any("common slice ends" in limit for limit in record["limits"])
    assert record["results"]["base_reached_saved_stop"] is False
    assert record["results"]["variant_reached_saved_stop"] is True
    assert record["results"]["base_t_last_us"] == pytest.approx(5900.0, abs=0.05)
    assert record["results"]["variant_t_last_us"] == pytest.approx(8000.0)
    assert record["results"]["base"]["ipri_peak_a"] == pytest.approx(84.0)
    assert record["results"]["base"]["sr_forward_peak_a"] == pytest.approx(60.0)
    assert record["results"]["base"]["trip_s"] == pytest.approx(5.5904e-3, abs=1e-9)
    # Both sides are read over the same slice, so an identical waveform gives
    # exactly zero movement even though the files have different lengths.
    assert record["results"]["delta"]["ipri_peak_a"] == pytest.approx(0.0, abs=1e-12)
    assert record["results"]["delta"]["sr_forward_peak_a"] == pytest.approx(0.0, abs=1e-12)


def test_a_fully_covered_window_is_reported_as_covered(tmp_path: Path):
    raw = tmp_path / "same.raw"
    write_raw(raw, fault_points(6000.0) + [(8e-3, 0.0, 0.0, 0.0, 0.0, 0.0)])
    deck = tmp_path / "deck.cir"
    deck.write_text(DECK, encoding="utf-8")
    record = compare(raw, deck, raw, deck)
    assert record["checks"]["the_comparison_window_is_covered_by_both_raws"] is True
    assert record["results"]["declared_window_fully_covered"] is True
    assert record["results"]["window_end_us"] == pytest.approx(6000.0)
    assert not any("common slice ends" in limit for limit in record["limits"])


def test_a_circuit_edit_is_not_accepted_as_a_solver_variant(tmp_path: Path):
    base_deck = tmp_path / "base.cir"
    variant_deck = tmp_path / "variant.cir"
    base_deck.write_text(DECK, encoding="utf-8")
    variant_deck.write_text(
        DECK.replace(".options plotwinsize=0 method=gear",
                     ".options plotwinsize=0 method=gear cshunt=1e-15")
        .replace("Rload out sgnd 15.4m", "Rload out sgnd 15.5m"),
        encoding="utf-8",
    )
    raw = tmp_path / "same.raw"
    write_raw(raw, fault_points(6000.0) + [(8e-3, 0.0, 0.0, 0.0, 0.0, 0.0)])
    record = compare(raw, base_deck, raw, variant_deck)
    assert record["circuit_differences"]
    assert record["checks"]["the_two_decks_differ_only_on_solver_settings"] is False


def test_a_window_beyond_the_saved_stop_is_refused(tmp_path: Path):
    deck = tmp_path / "short.cir"
    deck.write_text(DECK.replace(".tran 0 8m 0 10n uic", ".tran 0 5.5m 0 10n uic"),
                    encoding="utf-8")
    raw = tmp_path / "same.raw"
    write_raw(raw, fault_points(5450.0))
    with pytest.raises(ValueError, match="saved stop"):
        compare(raw, deck, raw, deck)
