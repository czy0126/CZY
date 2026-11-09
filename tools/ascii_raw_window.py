"""Stream a time window out of a large LTspice ASCII raw file.

The 8 ms cold-start raws are 10-13 GB.  PyLTSpice reads the whole file and
allocates every variable (minutes, several GB), and it refuses a raw whose run
was stopped early because the header still says "No. Points: 0".  Both problems
disappear if we only need a few columns over a time window:

    * bisect the byte offset of t0 (record start times are monotone),
    * parse from there in 64 MB blocks, keeping only the requested columns,
    * stop at t1 and ignore a truncated final record.

This is the "seek to the tail" rule in CLAUDE.md, generalised to a window and
to named columns.  It only understands the ASCII format that `-ascii` writes.

Usage:
    python tools/ascii_raw_window.py sim/v2/x.raw --from-ms 5.4 "V(oc)" "V(out)"
    python tools/ascii_raw_window.py sim/v3/y.raw --step-profile --bin-us 100
"""

from __future__ import annotations

import argparse
from array import array
from pathlib import Path

import numpy as np

CHUNK = 64 << 20


def read_header(handle) -> tuple[list[str], int]:
    """Return (variable names in order, byte offset of the first data record)."""
    names: list[str] = []
    in_vars = False
    while True:
        pos = handle.tell()
        line = handle.readline()
        if not line:
            raise ValueError("ASCII raw has no 'Values:' section")
        if line.startswith(b"Variables:"):
            in_vars = True
            continue
        if in_vars:
            parts = [p for p in line.split(b"\t") if p]
            if len(parts) >= 2 and parts[0].strip().isdigit():
                names.append(parts[1].decode("latin-1"))
            elif line.startswith(b"Values:"):
                return names, pos + len(line)
        if line.startswith(b"Values:"):
            return names, pos + len(line)


def _record_time(line: bytes) -> float | None:
    """Time column of a record-start line, or None for a value line."""
    parts = line.split(b"\t")
    if len(parts) < 3:
        return None
    try:
        return float(parts[2])
    except ValueError:
        return None


def find_offset(handle, t0: float, size: int, n_variables: int) -> int:
    """Byte offset of the first record whose time is at or after t0.

    A record is one time line plus ``n_variables - 1`` value lines, so the
    scan for the next record start must cover a whole record.  The original
    fixed 64-line scan was shorter than the 81-line records of the
    80-variable decks; at random byte offsets it found no record start,
    reported "no time", and bisected into the middle of the file.  The 120 A
    raw was read as 65.7-120 us instead of 0-120 us (see
    test_ascii_raw_window.py).
    """
    span = n_variables + 2

    def time_at(off: int) -> float | None:
        handle.seek(off)
        handle.readline()  # drop the partial line the seek landed in
        for _ in range(span):
            line = handle.readline()
            if not line:
                return None
            if line.startswith(b"\t"):
                continue
            tv = _record_time(line)
            if tv is not None:
                return tv
        return None

    lo, hi = 0, size
    for _ in range(48):
        mid = (lo + hi) // 2
        tv = time_at(mid)
        if tv is None or tv < t0:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1:
            break
    # ``lo`` is inside the record before the first one at or after t0 (or at
    # EOF).  Walk forward to that record's start rather than dropping the
    # line the seek happens to land on.
    handle.seek(lo)
    handle.readline()
    while True:
        pos = handle.tell()
        line = handle.readline()
        if not line:
            return pos
        if line.startswith(b"\t"):
            continue
        tv = _record_time(line)
        if tv is not None and tv >= t0:
            return pos


def last_time(path: str | Path, chunk: int = 1 << 20) -> float:
    """Time of the last complete record, read from the tail only.

    A stalled solve can write gigabytes per nanosecond of simulated time (the
    50 V hot-fault run spent 13.3 GB on its last 0.93 us), so reading the whole
    file just to learn where it stopped is not affordable.  Records are one
    time line plus one line per non-time variable, so the search walks
    backwards over blocks until a non-continuation line parses as a time.
    """
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        end = size
        while end > 0:
            start = max(0, end - chunk)
            handle.seek(start)
            lines = handle.read(end - start).split(b"\n")
            # A non-zero start lands mid-line: drop that partial first line.
            scan = lines[1:] if start > 0 else lines
            # Only a record start followed by a value line is complete: a write
            # cut inside the time field can still parse, but its continuation
            # never arrived, so accepting it would report a wrong last time.
            for i in range(len(scan) - 2, -1, -1):
                line = scan[i]
                if not line.startswith(b"\t") and scan[i + 1].startswith(b"\t"):
                    value = _record_time(line)
                    if value is not None:
                        return value
            end = start
    raise ValueError(f"{path.name} has no record times")


def read_window(path: str | Path, names: list[str], t0: float,
                t1: float | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return (time, {name: values}) for records with t0 <= t < t1."""
    path = Path(path)
    with path.open("rb") as handle:
        var_names, data_offset = read_header(handle)
        index = {name: i for i, name in enumerate(var_names)}
        missing = [n for n in names if n not in index]
        if missing:
            raise KeyError(f"{path.name} has no traces {missing}; available: {var_names}")
        columns = [index[n] for n in names]
        size = path.stat().st_size
        # t0=0 must include the very first record; bisection would align past
        # it because it seeks into the middle of a line before aligning.
        handle.seek(data_offset if t0 <= 0.0
                    else find_offset(handle, t0, size, len(var_names)))

        times = array("d")
        values = {name: array("d") for name in names}
        leftover = b""
        slot = 0            # 0 = next line is a record start, else variable index
        record_started = False
        done = False
        while not done:
            block = handle.read(CHUNK)
            if not block:
                break
            lines = (leftover + block).split(b"\n")
            leftover = lines.pop()
            for line in lines:
                if not line:
                    continue
                if line.startswith(b"\t"):
                    if record_started:
                        if slot in columns:
                            try:
                                values[var_names[slot]][-1] = float(line)
                            except ValueError:
                                pass
                        slot += 1
                    continue
                parts = line.split(b"\t")
                if len(parts) < 3:
                    continue
                try:
                    t = float(parts[2])
                except ValueError:
                    continue
                if t < t0:
                    slot, record_started = 0, False
                    continue
                if t1 is not None and t >= t1:
                    done = True
                    break
                times.append(t)
                for name in names:
                    values[name].append(float("nan"))  # filled by continuations
                slot, record_started = 1, True
            if done:
                break

    t_arr = np.frombuffer(times, dtype=np.float64).copy()
    n = t_arr.size
    out = {name: np.frombuffer(values[name], dtype=np.float64).copy()[:n] for name in names}
    # A record cut off at EOF keeps NaN in the columns that never arrived.
    mask = np.ones(n, dtype=bool)
    for name in names:
        mask &= np.isfinite(out[name])
    return t_arr[mask], {name: out[name][mask] for name in names}


def step_profile(path: str | Path, t0: float = 0.0, t1: float | None = None,
                 bin_s: float = 100e-6,
                 thresholds: tuple[float, ...] = (1e-9, 1e-10, 1e-11, 1e-12),
                 ) -> dict:
    """Summarise the solver timestep against simulated time for one raw.

    A converged solve of this converter should hold the deck's max step.  When
    it does not, the ``.log`` only names the *last* point ("Time step too
    small ... trouble with node X"), which reads like a single event at that
    instant.  The profile shows the step was already at the floor long before,
    so the reported instant is where the solver gave up, not where it first
    struggled.  ``collapses`` keeps, per threshold, the first step that falls
    below it -- that is the onset, and it is what a claim about "when it broke"
    has to quote.

    The time axis is read with an empty trace list so no other column is
    allocated; a 10 M-point raw costs one float per record.

    TRAP: a ``uic`` deck starts at t=0 with a ~1e-13 s first step, so the
    earliest ``collapses`` entry is always that start, not an instability.
    Pass ``t0`` past the initial transient before calling anything a collapse.
    """
    t, _ = read_window(path, [], t0, t1)
    if t.size < 2:
        raise ValueError(f"{Path(path).name}: {t.size} record(s); need >= 2 for a step")
    dt = np.diff(t)
    if np.any(dt <= 0.0):
        raise ValueError(f"{Path(path).name}: record times are not increasing")

    starts = t[:-1]
    bins = []
    if bin_s > 0:
        index = np.floor((starts - starts[0]) / bin_s).astype(np.int64)
        order = np.argsort(index, kind="stable")
        bounds = np.flatnonzero(np.diff(index[order])) + 1
        for chunk in np.split(order, bounds):
            if chunk.size == 0:
                continue
            bins.append({
                "t_start": float(t[chunk[0]]),
                "t_end": float(t[chunk[-1] + 1]),
                "steps": int(chunk.size),
                "dt_min": float(dt[chunk].min()),
                "dt_max": float(dt[chunk].max()),
            })

    collapses = []
    for threshold in thresholds:
        hit = np.flatnonzero(dt < threshold)
        if hit.size:
            k = int(hit[0])
            collapses.append({"threshold": float(threshold),
                              "t": float(t[k + 1]), "dt": float(dt[k])})

    return {
        "records": int(t.size),
        "t_first": float(t[0]),
        "t_last": float(t[-1]),
        "dt_min": float(dt.min()),
        "dt_max": float(dt.max()),
        "dt_median": float(np.median(dt)),
        "bins": bins,
        "collapses": collapses,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--from-ms", type=float, default=0.0)
    ap.add_argument("--to-ms", type=float, default=None)
    ap.add_argument("--step-profile", action="store_true",
                    help="report timestep vs simulated time instead of trace ranges")
    ap.add_argument("--bin-us", type=float, default=100.0)
    ap.add_argument("traces", nargs="*")
    args = ap.parse_args()
    t0 = args.from_ms * 1e-3
    t1 = None if args.to_ms is None else args.to_ms * 1e-3

    if args.step_profile:
        profile = step_profile(args.raw, t0, t1, bin_s=args.bin_us * 1e-6)
        print(f"{profile['records']} records, {profile['t_first'] * 1e3:.6f}.."
              f"{profile['t_last'] * 1e3:.6f} ms  dt median={profile['dt_median']:.3e}"
              f"  min={profile['dt_min']:.3e}  max={profile['dt_max']:.3e}")
        for hit in profile["collapses"]:
            print(f"  first step < {hit['threshold']:g} s at t={hit['t']:.9e} s"
                  f"  (dt={hit['dt']:.3e})")
        for b in profile["bins"]:
            print(f"  t=[{b['t_start'] * 1e3:9.4f},{b['t_end'] * 1e3:9.4f}) ms"
                  f"  steps={b['steps']:9d}  dt_min={b['dt_min']:.3e}"
                  f"  dt_max={b['dt_max']:.3e}")
        return

    if not args.traces:
        ap.error("give at least one trace, or --step-profile")
    t, data = read_window(args.raw, args.traces, t0, t1)
    print(f"{t.size} points, {t[0] * 1e3:.4f}..{t[-1] * 1e3:.4f} ms")
    for name in args.traces:
        print(f"  {name}: min={np.nanmin(data[name]):.6g} max={np.nanmax(data[name]):.6g}")


if __name__ == "__main__":
    main()
