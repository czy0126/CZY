"""Run the read-only native DRC on the routed G1 candidate and keep the raw result.

Open by `--path` (never `openProject`) and close the session with `--destroy`. This
script never saves; it records md5 before/after and fails if the board file changed.
The DRC body itself is `driver_drc.js` (confirmed API: `pcb_Drc.check(strict,
userInterface, includeVerboseError)`; `includeVerboseError=true` always returns an array).
`--rules` runs the same protocol with `driver_rules.js` instead and writes
`driver_rules_raw.json`, so the board's own rule file has a committed producer.

Two editor traps are built in (2026-11-10, see docs/agent/EDA.md):

* a real ``eda`` body sent sooner than ``SETTLE_S`` after ``open`` wedges that
  render for good (every later body, in every session, times out) -> settle and
  ping with ``return 1;`` first;
* ``subprocess.run(capture_output=True)`` can block forever because the detached
  app keeps the inherited pipe open -> redirect to files and wait on the PID.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDA = Path(r"D:\lceda-pro\lceda-pro.exe")
BOARD = HERE / "dcx_main_board_g1_driver_route.eprj2"
JS = HERE / "driver_drc.js"

#: ``--rules`` runs the other read-only body instead: it opens the PCB document
#: and returns ``pcb_Drc.getCurrentRuleConfiguration()`` so the via minima and
#: spacing values the offline checker uses come from the board, not from a
#: remembered fab table. Same protocol, different body and output prefix.
RULES_JS = HERE / "driver_rules.js"
MODE = {"drc": (JS, "driver_drc"), "rules": (RULES_JS, "driver_rules")}
VIA_FORM = ("config", "Physics", "Via Size", "viaSize", "form")

#: Measured: 20 s after ``open`` the first real body answers in 3 ms; 1-3 s
#: after ``open`` it never answers and poisons the app.
SETTLE_S = 20


def build_open_args(board: Path) -> list[str]:
    return [str(LEDA), "open", "--path", str(board), "--headless", "true"]


def build_invoke_args(session: str, code: str, timeout_ms: int = 60000) -> list[str]:
    return [str(LEDA), "invoke", "--session", session, "--ext-uuid", "eda",
            "--timeout", str(timeout_ms), "--code", code]


def build_ping_args(session: str) -> list[str]:
    """`return 1;` never enters the ``eda`` namespace, so it answers while the
    render is still loading — the two-step liveness check."""
    return build_invoke_args(session, "return 1;", 5000)


def build_close_args(session: str) -> list[str]:
    return [str(LEDA), "session", "close", "--session", session, "--destroy"]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def call(args: list[str], timeout_s: float = 150) -> dict:
    """Run one CLI call with output redirected to files, then parse its JSON."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdout=out, stderr=err)
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
            return {"ok": False, "error": {"code": "CLI_TIMEOUT",
                                           "message": f"lceda-pro did not exit in {timeout_s}s"}}
        out.seek(0)
        err.seek(0)
        stdout, stderr = _decode(out.read()), _decode(err.read())
    try:
        return json.loads(stdout.strip() or stderr.strip())
    except json.JSONDecodeError:
        return {"ok": False, "stdout": stdout, "stderr": stderr, "code": proc.returncode}


def via_minima(value: dict) -> dict | None:
    """Pull the via size limits out of a rule-configuration value, or None."""
    node: object = value
    for key in VIA_FORM:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return {"viaInnerdiameterMin": node.get("viaInnerdiameterMin"),
            "viaOuterdiameterMin": node.get("viaOuterdiameterMin")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--settle-s", type=float, default=SETTLE_S)
    parser.add_argument("--rules", action="store_true",
                        help="read the board's rule configuration instead of running DRC")
    parser.add_argument("--prefix", default=None,
                        help="receipt prefix (default: the mode's own, so an older "
                             "candidate's receipts are overwritten -- pass one to keep both)")
    args = parser.parse_args()

    #: ``open --path`` resolves a relative path against the *app's* working
    #: directory, not the caller's: the session still opens and the ping still
    #: answers, but the project is empty and every ``eda`` body reports
    #: "PCB missing". Always hand the editor an absolute path.
    board = args.board.resolve()
    body_path, default_prefix = MODE["rules" if args.rules else "drc"]
    prefix = args.prefix or default_prefix

    def dump(name: str, payload: dict) -> None:
        (HERE / f"{prefix}_{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    before = md5(board)
    opened = call(build_open_args(board))
    dump("open", opened)
    session = (opened.get("value") or {}).get("sessionId")
    if not session:
        print(json.dumps({"ok": False, "why": "no session", "open": opened}, ensure_ascii=False))
        return 1

    time.sleep(args.settle_s)
    ping = call(build_ping_args(session), timeout_s=30)
    dump("ping", ping)
    if not ping.get("ok"):
        call(build_close_args(session))
        print(json.dumps({"ok": False, "why": "render not answering after settle", "ping": ping},
                         ensure_ascii=False))
        return 1

    try:
        raw = call(build_invoke_args(session, body_path.read_text(encoding="utf-8"),
                                     args.timeout_ms))
    finally:
        dump("close", call(build_close_args(session)))

    dump("raw", raw)
    after = md5(board)
    value = raw.get("value") or {}
    if args.rules:
        summary = {"rule_config": value.get("name"), "via_minima": via_minima(value),
                   "source": body_path.name}
    else:
        summary = {"rule_config": value.get("rule_config"), "count": value.get("count"),
                   "source": body_path.name}
    print(json.dumps({"ok": raw.get("ok", False), "unchanged": before == after, **summary},
                     ensure_ascii=False))
    return 0 if raw.get("ok") and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
