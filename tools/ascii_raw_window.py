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


def find_offset(handle, t0: float, size: int) -> int:
    """Byte offset of the first record at or after t0 (bisection on record starts)."""
    def time_at(off: int) -> float | None:
        handle.seek(off)
        handle.readline()  # drop the partial line
        for _ in range(64):
            line = handle.readline()
            if not line:
                return None
            if not line.startswith(b"\t"):
                parts = line.split(b"\t")
                if len(parts) >= 3:
                    try:
                        return float(parts[2])
                    except ValueError:
                        return None
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
    handle.seek(lo)
    handle.readline()  # align to a record boundary
    return handle.tell()


def read_window(path: str | Path, names: list[str], t0: float,
                t1: float | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return (time, {name: values}) for records with t0 <= t < t1."""
    path = Path(path)
    with path.open("rb") as handle:
        var_names, _ = read_header(handle)
        index = {name: i for i, name in enumerate(var_names)}
        missing = [n for n in names if n not in index]
        if missing:
            raise KeyError(f"{path.name} has no traces {missing}; available: {var_names}")
        columns = [index[n] for n in names]
        size = path.stat().st_size
        handle.seek(find_offset(handle, t0, size))

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--from-ms", type=float, required=True)
    ap.add_argument("--to-ms", type=float, default=None)
    ap.add_argument("traces", nargs="+")
    args = ap.parse_args()
    t, data = read_window(args.raw, args.traces, args.from_ms * 1e-3,
                          None if args.to_ms is None else args.to_ms * 1e-3)
    print(f"{t.size} points, {t[0] * 1e3:.4f}..{t[-1] * 1e3:.4f} ms")
    for name in args.traces:
        print(f"  {name}: min={np.nanmin(data[name]):.6g} max={np.nanmax(data[name]):.6g}")


if __name__ == "__main__":
    main()
