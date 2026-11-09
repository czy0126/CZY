"""Run the read-only native DRC on the routed G1 candidate and keep the raw result.

Open by `--path` (never `openProject`) and close the session with `--destroy`. This
script never saves; it records md5 before/after and fails if the board file changed.
The DRC body itself is `driver_drc.js` (confirmed API: `pcb_Drc.check(strict,
userInterface, includeVerboseError)`; `includeVerboseError=true` always returns an array).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDA = Path(r"D:\lceda-pro\lceda-pro.exe")
BOARD = HERE / "dcx_main_board_g1_driver_route.eprj2"
JS = HERE / "driver_drc.js"


def build_open_args(board: Path) -> list[str]:
    return [str(LEDA), "open", "--path", str(board), "--headless", "true"]


def build_invoke_args(session: str, code: str, timeout_ms: int = 60000) -> list[str]:
    return [str(LEDA), "invoke", "--session", session, "--ext-uuid", "eda",
            "--timeout", str(timeout_ms), "--code", code]


def build_close_args(session: str) -> list[str]:
    return [str(LEDA), "session", "close", "--session", session, "--destroy"]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def call(args: list[str], timeout_s: int = 150) -> dict:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout_s)
    try:
        return json.loads(proc.stdout.strip() or proc.stderr.strip())
    except json.JSONDecodeError:
        return {"ok": False, "stdout": proc.stdout, "stderr": proc.stderr, "code": proc.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    args = parser.parse_args()

    before = md5(args.board)
    opened = call(build_open_args(args.board))
    (HERE / "driver_drc_open.json").write_text(
        json.dumps(opened, ensure_ascii=False, indent=2), encoding="utf-8")
    session = (opened.get("value") or {}).get("sessionId")
    if not session:
        print(json.dumps({"ok": False, "why": "no session", "open": opened}, ensure_ascii=False))
        return 1
    try:
        raw = call(build_invoke_args(session, JS.read_text(encoding="utf-8"), args.timeout_ms))
    finally:
        closed = call(build_close_args(session))
        (HERE / "driver_drc_close.json").write_text(
            json.dumps(closed, ensure_ascii=False, indent=2), encoding="utf-8")

    (HERE / "driver_drc_raw.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    after = md5(args.board)
    value = raw.get("value") or {}
    print(json.dumps({"ok": raw.get("ok", False), "unchanged": before == after,
                      "rule_config": value.get("rule_config"), "count": value.get("count")},
                     ensure_ascii=False))
    return 0 if raw.get("ok") and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
