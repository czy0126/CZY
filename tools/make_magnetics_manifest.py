"""Refresh design/v3/magnetics/manifest.json.

The magnetic package quotes numbers that come from a deck, a raw, three tools,
and two generated drawings.  The manifest pins all of them by SHA256 so a
reviewer can tell whether the files still match the text.

Usage:
    python tools/make_magnetics_manifest.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir",
    "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw",
    "sim/v3/sr_tank_dual_v33_ss_1ms_100a.log",
    "tools/magnetics_design.py",
    "tools/extract_op_point.py",
    "tools/draw_magnetics.py",
    "tools/winding_polarity.py",
    "tools/board_netlist.py",
    "tools/make_magnetics_manifest.py",
    "tools/test_magnetics_design.py",
    "tools/test_extract_op_point.py",
    "tools/test_draw_magnetics.py",
    "tools/test_board_netlist.py",
    "design/v3/magnetics/磁件设计包_2026-10-31.md",
    "design/v3/magnetics/绕组工艺卡_2026-11-01.md",
    "design/v3/magnetics/magnetics_design.json",
    "design/v3/magnetics/operating_point_100a.json",
    "design/v3/magnetics/winding_cross_section.svg",
    "design/v3/magnetics/height_stackup.svg",
    "design/v3/magnetics/winding_connections.svg",
    "design/v3/magnetics/winding_polarity.json",
    "design/v3/magnetics/winding_polarity.csv",
    "design/v3/magnetics/first_article_polarity_record.csv",
    "design/v3/magnetics/height_stackup.csv",
    "design/v3/magnetics/inspection_spec.csv",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest() -> dict[str, object]:
    entries = {}
    for rel in FILES:
        path = ROOT / rel
        entries[rel] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tools", "-q"],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        tail = [line for line in result.stdout.splitlines() if "passed" in line or "failed" in line]
        test_result = tail[-1].strip() if tail else "unknown"
    except OSError:
        test_result = "not run"
    return {
        "date": date.today().isoformat(),
        "status": "design estimate, not hardware validated",
        "test_command": "python -m pytest tools -q",
        "test_result": test_result,
        "files": entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=ROOT / "design/v3/magnetics/manifest.json")
    args = ap.parse_args()
    args.json.write_text(json.dumps(manifest(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)


if __name__ == "__main__":
    main()
