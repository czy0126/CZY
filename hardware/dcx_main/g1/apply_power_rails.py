"""Apply the two power rails to a fresh copy of the routed candidate and read it back.

The rails are checked offline against `driver_route_readback.json`, but a plan is
not layout.  This is the single write step: copy -> open by `--path` -> settle ->
`return 1;` ping -> invoke the emit body (it saves itself) -> wait past the save
debounce -> close `--destroy` -> reopen -> read back -> `route_power_rails.verify`.

The routed candidate is never opened; every experiment opens a copy
(docs/agent/EDA.md).  The editor traps are the ones `run_driver_drc.py` documents:
a real ``eda`` body sent sooner than ``SETTLE_S`` after ``open`` wedges that
render for good, and a captured pipe can block forever, so every CLI call is
file-redirected and killed on timeout.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import route_power_rails as P
import run_driver_drc as D

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "dcx_main_board_g1_driver_route.eprj2"
TARGET = HERE / P.CANDIDATE
READ_JS = HERE / "read_driver_route.js"
BODY = P.R.emit_js(P.copper(), P.vias())


def dump(name: str, payload: dict) -> None:
    (HERE / f"power_rails_{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def invoke(session: str, code: str) -> dict:
    return D.call(D.build_invoke_args(session, code), timeout_s=150)


def open_and_ping(board: Path, label: str) -> str | None:
    """Open by path, settle, ping.  A render that does not answer is closed, not retried."""
    opened = D.call(D.build_open_args(board))
    dump(f"{label}_open", opened)
    session = (opened.get("value") or {}).get("sessionId")
    if not session:
        print(json.dumps({"ok": False, "why": "no session", "open": opened}, ensure_ascii=False))
        return None
    time.sleep(D.SETTLE_S)
    ping = D.call(D.build_ping_args(session), timeout_s=30)
    dump(f"{label}_ping", ping)
    if not ping.get("ok"):
        dump(f"{label}_close", D.call(D.build_close_args(session)))
        print(json.dumps({"ok": False, "why": "render not answering after settle",
                          "ping": ping}, ensure_ascii=False))
        return None
    return session


def main() -> int:
    source_md5 = D.md5(SOURCE)
    shutil.copy2(SOURCE, TARGET)
    print(json.dumps({"copied_from_md5": source_md5, "target": TARGET.name,
                      "target_size": TARGET.stat().st_size}))

    session = open_and_ping(TARGET, "apply")
    if not session:
        return 1
    applied = invoke(session, BODY)
    dump("apply", applied)
    time.sleep(30)  # save() is debounced ~20 s
    dump("close", D.call(D.build_close_args(session)))
    value = applied.get("value") or {}
    created = value.get("created") or []
    via_created = value.get("viasCreated") or []
    print(json.dumps({"apply_ok": applied.get("ok"), "created": len(created),
                      "vias": len(via_created), "failed": value.get("failed"),
                      "saved": value.get("saved"),
                      "target_md5_after": D.md5(TARGET)}, ensure_ascii=False))
    if not applied.get("ok") or value.get("failed") or not value.get("saved"):
        return 1
    if D.md5(SOURCE) != source_md5:
        print(json.dumps({"ok": False, "why": "the routed candidate changed"}, ensure_ascii=False))
        return 1

    session = open_and_ping(TARGET, "reopen")
    if not session:
        return 1
    try:
        readback = invoke(session, READ_JS.read_text(encoding="utf-8"))
    finally:
        dump("reopen_close", D.call(D.build_close_args(session)))
    (HERE / P.READBACK_OUT.name).write_text(
        json.dumps(readback, ensure_ascii=False, indent=2), encoding="utf-8")
    rb = readback.get("value") or {}
    print(json.dumps({"readback_ok": readback.get("ok"),
                      "components": len(rb.get("components") or []),
                      "pads": len(rb.get("pads") or []),
                      "nets": len(rb.get("nets") or []),
                      "polylines": rb.get("polylines"),
                      "lines": len(rb.get("lines") or []),
                      "vias": len(rb.get("vias") or [])}, ensure_ascii=False))
    if not readback.get("ok"):
        return 1

    report = P.verify()
    P.REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    ok = (report["layout_counts"]["unchanged"]
          and not report["lines"]["coverage_problems"]
          and not report["vias"]["problems"]
          and not report["placement_drift"])
    print(json.dumps({"verify_ok": ok, "coverage_problems": len(report["lines"]["coverage_problems"]),
                      "via_problems": len(report["vias"]["problems"]),
                      "drift": len(report["placement_drift"])}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
