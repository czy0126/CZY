"""Regressions against LTspice 24 NaN and incomplete RAW behaviors."""
import struct
from pathlib import Path
import pytest
from poc_raw_evidence import RawEvidenceError, inspect_raw


def sample(path: Path, rows, count=None, flags="real forward nocompression"):
    if count is None:
        count = len(rows)
    header = (f"Title: t\nPlotname: Transient Analysis\nFlags: {flags}\n"
              f"No. Variables: 2\nNo. Points: {count}\n"
              "Variables:\n0\ttime\ttime\n1\tV(out)\tvoltage\nBinary:\n")
    path.write_bytes(header.encode("utf-16le")
                     + b"".join(struct.pack("<df", t, v) for t, v in rows))


def test_complete_finite_raw(tmp_path):
    p = tmp_path / "ok.raw"
    sample(p, [(0, 0), (.004, 1), (.008, 1.87)])
    data = inspect_raw(p)
    assert data["points"] == 3
    assert data["hardware_qualified"] is False


def test_nan_at_557us_even_with_complete_time_axis(tmp_path):
    p = tmp_path / "nan.raw"
    sample(p, [(0, 0), (.000557826, float("nan")), (.008, float("nan"))])
    with pytest.raises(RawEvidenceError, match="nonfinite RAW"):
        inspect_raw(p)


def test_mismatched_header_and_payload_byte_counts(tmp_path):
    p = tmp_path / "extra.raw"
    sample(p, [(0, 0), (.008, 1)], count=3)
    with pytest.raises(RawEvidenceError, match="byte count"):
        inspect_raw(p)


def test_pre_8ms_stop_cannot_be_published_as_full_run(tmp_path):
    p = tmp_path / "short.raw"
    sample(p, [(0, 0), (.00057, .05)])
    with pytest.raises(RawEvidenceError, match="early termination"):
        inspect_raw(p)


def test_unsupported_fastaccess_layout_is_rejected(tmp_path):
    p = tmp_path / "fast.raw"
    sample(p, [(0, 0), (.008, 2)], flags="real fastaccess")
    with pytest.raises(RawEvidenceError, match="unsupported RAW"):
        inspect_raw(p)


def test_time_reversal_is_rejected(tmp_path):
    p = tmp_path / "badtime.raw"
    sample(p, [(.008, 0), (.004, 0)])
    with pytest.raises(RawEvidenceError, match="reversed time"):
        inspect_raw(p)
