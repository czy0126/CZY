"""Fail-closed LTspice standard transient binary RAW validation, stdlib only."""
from __future__ import annotations
import math
import re
import struct
from pathlib import Path


class RawEvidenceError(ValueError):
    pass


def inspect_raw(path: Path, stop_time_s: float = 0.008) -> dict:
    with path.open("rb") as f:
        head = f.read(131072)
        marker = "Binary:\n".encode("utf-16le")
        pos = head.find(marker)
        if pos < 0:
            raise RawEvidenceError("missing UTF-16LE Binary marker; unsupported RAW layout")
        text = head[:pos].decode("utf-16-le")
        offset = pos + len(marker)

        def field(pattern: str) -> str:
            m = re.search(pattern, text, re.I | re.M)
            if not m:
                raise RawEvidenceError("RAW header missing " + pattern)
            return m.group(1).strip()

        flags = field(r"^Flags:\s*(.+)$").lower().split()
        if "real" not in flags or "complex" in flags or "fastaccess" in flags:
            raise RawEvidenceError("unsupported RAW flags: " + str(flags))
        count = int(field(r"^No\. Points:\s*(\d+)"))
        n = int(field(r"^No\. Variables:\s*(\d+)"))
        if count < 2 or not 2 <= n <= 4096:
            raise RawEvidenceError("invalid RAW dimensions")
        fmt = "<d" + "f" * (n - 1)
        stride = struct.calcsize(fmt)
        actual = path.stat().st_size
        expected = offset + count * stride
        if actual != expected:
            raise RawEvidenceError(
                f"RAW byte count mismatch actual={actual}, expected={expected}, "
                f"points={count}, stride={stride}")
        f.seek(offset)
        previous = -math.inf
        point = 0
        while point < count:
            size = min(4096, count - point)
            chunk = f.read(size * stride)
            if len(chunk) != size * stride:
                raise RawEvidenceError("RAW truncated during scan")
            for row in struct.iter_unpack(fmt, chunk):
                t = row[0]
                if not math.isfinite(t) or t + 1e-15 < previous:
                    raise RawEvidenceError(f"nonfinite or reversed time point={point} t={t}")
                for col, value in enumerate(row[1:], 1):
                    if not math.isfinite(value):
                        raise RawEvidenceError(
                            f"nonfinite RAW point={point} t={t:.12g}s "
                            f"variable_index={col} value={value}")
                previous = t
                point += 1
        if previous < stop_time_s - 1e-7:
            raise RawEvidenceError(
                f"RAW early termination t={previous:.12g}s, required={stop_time_s}s")
        return {"status": "RAW_ALL_FINITE_AND_TIME_COMPLETE", "points": count,
                "variables": n, "bytes": actual, "last_time_s": previous,
                "hardware_qualified": False}
