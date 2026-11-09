"""The window reader must not silently start late.

A raw record is one time line plus one line per non-time variable.  The first
version of ``find_offset`` scanned only 64 lines for the next record start, so
on the 80-variable decks it could fail to find one at a random byte offset,
treat that as "time < t0", and bisect to the middle of the file.  The 120 A raw
was read as 65.7-120 us instead of 0-120 us, which made a 22-period extraction
report "only 10 complete periods" -- a loud failure here, but every
per-window metric would have been silently wrong if the truncated window had
still contained enough edges.

These tests build a raw whose layout is exactly what LTspice ``-ascii`` writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ascii_raw_window import last_time, read_header, read_window, step_profile


def write_raw(path: Path, variables: int, points: int, step_s: float = 1e-6,
              times: list[float] | None = None) -> None:
    """A minimal but structurally exact ASCII raw: 1 + (variables-1) lines per record."""
    if times is None:
        times = [k * step_s for k in range(points)]
    lines = [
        "Title: synthetic\n",
        f"No. Variables: {variables}\n",
        f"No. Points: {len(times)}\n",
        "Variables:\n",
        "\t0\ttime\ttime\n",
    ]
    for i in range(1, variables):
        lines.append(f"\t{i}\tV(v{i})\tvoltage\n")
    lines.append("Values:\n")
    for k, t in enumerate(times):
        lines.append(f"{k}\t\t{t:.12e}\n")
        for i in range(1, variables):
            lines.append(f"\t{t * 1e3 + i * 0.5:.12e}\n")
    path.write_text("".join(lines), encoding="latin-1")


@pytest.mark.parametrize("variables", [8, 40, 80, 200])
def test_a_zero_start_keeps_the_first_record(tmp_path: Path, variables: int):
    """A window at t0=0 must begin at the first datum, whatever the width."""
    raw = tmp_path / "wide.raw"
    write_raw(raw, variables, points=4000)
    t, _ = read_window(raw, ["V(v1)"], 0.0, None)
    assert t.size == 4000
    assert t[0] == 0.0


@pytest.mark.parametrize("variables", [40, 80, 200])
def test_a_mid_window_starts_at_the_first_record_after_t0(tmp_path: Path, variables: int):
    """A seek into the middle must not jump past records it should have kept."""
    raw = tmp_path / "wide.raw"
    write_raw(raw, variables, points=4000)
    t0 = 1234e-6
    t, _ = read_window(raw, ["V(v1)"], t0, None)
    assert t[0] >= t0
    # The grid is 1 us: the first requested record is exactly t0, never later.
    assert t[0] == pytest.approx(t0, abs=1e-12)
    assert t.size == 4000 - 1234


def test_the_header_offset_points_at_the_first_record(tmp_path: Path):
    raw = tmp_path / "small.raw"
    write_raw(raw, 8, points=5)
    with raw.open("rb") as handle:
        names, offset = read_header(handle)
        assert names[0] == "time"
        handle.seek(offset)
        assert handle.readline().split(b"\t")[0] == b"0"


@pytest.mark.parametrize("variables", [8, 80, 200])
def test_last_time_reads_the_final_record_from_the_tail(tmp_path: Path, variables: int):
    # A stalled solve can be gigabytes deep, so "did it reach the stop?" must
    # cost one tail read, not a full parse.
    raw = tmp_path / "wide.raw"
    write_raw(raw, variables, points=3000)
    assert last_time(raw) == pytest.approx(2999e-6, rel=1e-12)


def test_last_time_ignores_a_record_start_cut_mid_write(tmp_path: Path):
    # A killed run can leave a hole where the time line should be.  The line
    # parses, but no value line follows it, so it is not a complete record.
    raw = tmp_path / "cut.raw"
    write_raw(raw, 40, points=100)
    with raw.open("ab") as handle:
        handle.write(b"100\t\t1.0000000")
    assert last_time(raw) == pytest.approx(99e-6, rel=1e-12)


def test_step_profile_of_a_uniform_grid_is_flat(tmp_path: Path):
    raw = tmp_path / "flat.raw"
    write_raw(raw, 8, points=1000)
    profile = step_profile(raw)
    assert profile["records"] == 1000
    assert profile["dt_min"] == pytest.approx(1e-6)
    assert profile["dt_max"] == pytest.approx(1e-6)
    assert profile["collapses"] == []


def test_step_profile_reports_the_onset_not_the_last_short_step(tmp_path: Path):
    """The first short step is the finding; a later one must not overwrite it.

    A stalled solve usually takes many short steps before it dies, so "when
    did the timestep break" is the first one.  Reporting the last would name
    the instant the run ended and make every variant look identical.
    """
    times = [k * 1e-6 for k in range(50)]
    times.append(times[-1] + 1e-13)
    base = times[-1]
    times.extend(base + k * 1e-6 for k in range(1, 50))
    times.append(times[-1] + 1e-15)
    raw = tmp_path / "broken.raw"
    write_raw(raw, 8, points=0, times=times)

    profile = step_profile(raw)
    assert profile["records"] == len(times)
    onset = profile["collapses"][0]
    assert onset["threshold"] == 1e-9
    assert onset["t"] == pytest.approx(times[50], rel=1e-12)
    assert onset["dt"] == pytest.approx(1e-13)
    # the later 1 fs step is real but must not be what "first" reports
    assert profile["dt_min"] == pytest.approx(1e-15)


def test_step_profile_bins_key_on_simulated_time(tmp_path: Path):
    # 3000 points at 1 us are 2999 steps: three 1 ms bins, the last one short.
    raw = tmp_path / "bins.raw"
    write_raw(raw, 8, points=3000)
    profile = step_profile(raw, bin_s=1e-3)
    assert [b["steps"] for b in profile["bins"]] == [1000, 1000, 999]
    assert profile["bins"][1]["t_start"] == pytest.approx(1e-3)


def test_step_profile_window_skips_earlier_records(tmp_path: Path):
    raw = tmp_path / "win.raw"
    write_raw(raw, 8, points=2000)
    profile = step_profile(raw, t0=1e-3)
    assert profile["t_first"] == pytest.approx(1e-3)
    assert profile["records"] == 1000


def test_step_profile_rejects_a_single_record(tmp_path: Path):
    raw = tmp_path / "one.raw"
    write_raw(raw, 8, points=1)
    with pytest.raises(ValueError, match="need >= 2"):
        step_profile(raw)
