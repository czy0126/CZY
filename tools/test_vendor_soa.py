"""The digitized SOA and Zth must stay tied to the vendored PDF.

SOURCE-03 asked for the original 2022 Rev.2.3 SOA and transient-impedance
diagrams, not vendor marketing numbers.  The committed JSON is a digitisation
of a specific PDF, so every check here either re-reads that PDF's hash or
re-derives a physical anchor that the datasheet states in text or in the axis
range.  PyMuPDF is not a project dependency; the regeneration test skips when
it is absent, but the JSON's own invariants are checked everywhere.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "references/datasheets/bsc010n04ls6.pdf"
DIGITIZED = ROOT / "design/v3/power_priority/vendor_soa_digitized.json"


def data() -> dict:
    return json.loads(DIGITIZED.read_text(encoding="utf-8"))


def test_the_digitized_file_is_present_and_hashes_the_vendored_pdf():
    d = data()
    assert DIGITIZED.is_file(), DIGITIZED
    assert d["source"]["pdf"] == "references/datasheets/bsc010n04ls6.pdf"
    assert d["source"]["sha256"] == hashlib.sha256(PDF.read_bytes()).hexdigest()


def test_the_digitizer_reproduces_the_committed_file():
    """Regeneration must be deterministic, not eyeballed once.

    The JSON is what every downstream screen reads, so a stale or hand-edited
    file is exactly the drift this test exists to catch.
    """
    pytest.importorskip("pymupdf")
    from vendor_soa import digitize

    assert digitize(PDF) == data()


def test_six_soa_curves_are_recovered_with_the_datasheet_labels():
    curves = data()["soa"]["curves"]
    assert len(curves) == 6
    assert [c["label"] for c in curves] == ["1 us", "10 us", "100 us", "1 ms", "10 ms", "DC"]
    assert [c["pulse_s"] for c in curves] == [1e-6, 10e-6, 100e-6, 1e-3, 10e-3, None]


def test_every_soa_curve_ends_at_the_rated_voltage_and_is_current_ordered():
    curves = data()["soa"]["curves"]
    for curve in curves:
        v, i = zip(*curve["points"])
        assert 38.0 <= max(v) <= 42.0, (curve["label"], max(v))
        assert max(i) > min(i)
    crests = [max(i for _, i in c["points"]) for c in curves]
    assert crests == sorted(crests, reverse=True), crests


def test_the_longest_pulse_crest_matches_the_datasheet_pulse_current():
    """The 1 us curve's plateau is I_D,pulse = 1140 A in the same datasheet.

    A digitisation that lands within a few percent of a number printed in the
    document is calibrated; one that does not is an axis-mapping bug.
    """
    curve = data()["soa"]["curves"][0]
    crest = max(i for _, i in curve["points"])
    assert abs(crest / 1140.0 - 1.0) < 0.05, crest


def test_the_soa_limit_lookup_interpolates_and_clamps_outside_the_drawn_range():
    from vendor_soa import soa_limit_at

    curve = {"points": [[1.0, 100.0], [10.0, 10.0]]}
    assert soa_limit_at(curve, 10.0 ** 0.5) == pytest.approx(math.sqrt(100.0 * 10.0), rel=1e-9)
    assert soa_limit_at(curve, 0.01) == pytest.approx(100.0)
    assert soa_limit_at(curve, 1000.0) == pytest.approx(10.0)


def test_the_zth_trace_is_monotone_and_starts_at_the_axis_floor():
    zth = data()["zth"]["single_pulse"]
    t = [p[0] for p in zth]
    z = [p[1] for p in zth]
    assert all(b > a for a, b in zip(t, t[1:]))
    assert all(b >= a * 0.999 for a, b in zip(z, z[1:])), "Zth must not fall"
    assert 9e-6 <= t[0] <= 12e-6, t[0]


def test_the_zth_trace_plateaus_at_the_steady_state_thermal_resistance():
    """A single pulse held for a second has reached Rth(j-c); the datasheet
    draws that plateau at 1 K/W for this package."""
    zth = data()["zth"]["single_pulse"]
    assert 0.9 <= zth[-1][1] <= 1.1, zth[-1]


def test_the_zth_lookup_is_monotone_and_extrapolates_below_the_drawn_floor():
    from vendor_soa import zth_at

    zth = [[1e-5, 0.02], [1e-4, 0.06], [1e-3, 0.3]]
    assert zth_at(zth, 1e-3) == pytest.approx(0.3)
    assert zth_at(zth, 5e-4) < zth_at(zth, 1e-3)
    # below the digitised floor the curve continues as a square root, which is
    # the shape of the drawn trace at its left end
    assert zth_at(zth, 1e-6) == pytest.approx(0.02 * math.sqrt(0.1), rel=1e-9)
    assert zth_at(zth, 10.0) == pytest.approx(0.3)


def test_the_calibration_reports_its_own_error():
    """The drawn 40 V edge reads 41.07 V, so the toolbar makes no claim of
    better than a few percent on either axis."""
    cal = data()["method"]
    assert "calibration_error" in cal
    assert "percent" in cal["calibration_error"].lower()
