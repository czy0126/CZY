"""Apply one plan module's copper to a fresh copy of a board and read it back.

Every G1 increment uses the same editor protocol (docs/agent/EDA.md): copy the
parent candidate, open the copy by ``--path``, settle 20 s, ping with
``return 1;``, invoke the emitted body (it saves itself), wait past the save
debounce, close with ``--destroy``, reopen and read back, then let the plan
module verify the readback.  This module holds that protocol once; the
per-increment scripts only name the module, the parent and the prefix.

* The parent is never opened: a hash check fails the run if it changed.
* A render that does not answer the ping is closed, not retried -- retrying is
  what wedges the shared render for good.
* Only ``save()`` returning true and a fresh reopen readback count as applied.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import run_driver_drc as D

HERE = Path(__file__).resolve().parent
READ_JS = HERE / "read_driver_route.js"


def dump(prefix: str, name: str, payload: dict) -> None:
    (HERE / f"{prefix}_{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def invoke(session: str, code: str) -> dict:
    return D.call(D.build_invoke_args(session, code), timeout_s=150)


def open_and_ping(board: Path, prefix: str, label: str) -> str | None:
    """Open by path, settle, ping.  No answer means closed and no retry."""
    opened = D.call(D.build_open_args(board))
    dump(prefix, f"{label}_open", opened)
    session = (opened.get("value") or {}).get("sessionId")
    if not session:
        print(json.dumps({"ok": False, "why": "no session", "open": opened}, ensure_ascii=False))
        return None
    time.sleep(D.SETTLE_S)
    ping = D.call(D.build_ping_args(session), timeout_s=30)
    dump(prefix, f"{label}_ping", ping)
    if not ping.get("ok"):
        dump(prefix, f"{label}_close", D.call(D.build_close_args(session)))
        print(json.dumps({"ok": False, "why": "render not answering after settle",
                          "ping": ping}, ensure_ascii=False))
        return None
    return session


def apply(plan, source: Path, prefix: str) -> int:
    """Copy ``source`` to ``plan.CANDIDATE``, apply, reopen-read-back, verify."""
    target = HERE / plan.CANDIDATE
    source_md5 = D.md5(source)
    shutil.copy2(source, target)
    print(json.dumps({"copied_from_md5": source_md5, "target": target.name,
                      "target_size": target.stat().st_size}))

    session = open_and_ping(target, prefix, "apply")
    if not session:
        return 1
    applied = invoke(session, plan.R.emit_js(plan.copper(), plan.vias()))
    dump(prefix, "apply", applied)
    time.sleep(30)  # save() is debounced ~20 s
    dump(prefix, "close", D.call(D.build_close_args(session)))
    value = applied.get("value") or {}
    print(json.dumps({"apply_ok": applied.get("ok"),
                      "created": len(value.get("created") or []),
                      "vias": len(value.get("viasCreated") or []),
                      "failed": value.get("failed"), "saved": value.get("saved"),
                      "target_md5_after": D.md5(target)}, ensure_ascii=False))
    if not applied.get("ok") or value.get("failed") or not value.get("saved"):
        return 1
    if D.md5(source) != source_md5:
        print(json.dumps({"ok": False, "why": "the parent candidate changed"}, ensure_ascii=False))
        return 1

    return verify_existing(plan, source, prefix)


def verify_existing(plan, source: Path, prefix: str) -> int:
    """Read-only native reopen/verification of an already saved candidate.

    Recovery does not repeat any PrimitiveLine.create calls or overwrite the PCB.
    A prior save response alone never counts as validated copper.
    """
    target = HERE / plan.CANDIDATE
    if not target.is_file():
        raise FileNotFoundError("No saved candidate to verify: " + str(target))
    before_source = D.md5(source)
    before_target = D.md5(target)
    session = open_and_ping(target, prefix, "reopen")
    if not session:
        return 1
    try:
        readback = invoke(session, READ_JS.read_text(encoding="utf-8"))
    finally:
        dump(prefix, "reopen_close", D.call(D.build_close_args(session)))
    plan.READBACK_OUT.write_text(json.dumps(readback, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    if D.md5(source) != before_source or D.md5(target) != before_target:
        raise ValueError("Native verification unexpectedly changed a PCB")
    rb = readback.get("value") or {}
    print(json.dumps({"readback_ok": readback.get("ok"),
                      "components": len(rb.get("components") or []),
                      "pads": len(rb.get("pads") or []), "nets": len(rb.get("nets") or []),
                      "polylines": rb.get("polylines"),
                      "lines": len(rb.get("lines") or []),
                      "vias": len(rb.get("vias") or [])}, ensure_ascii=False))
    if not readback.get("ok"):
        return 1

    report = plan.verify()
    plan.REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    ok = (report["layout_counts"]["unchanged"]
          and not report["lines"]["coverage_problems"]
          and not report["vias"]["problems"]
          and not report["placement_drift"])
    print(json.dumps({"verify_ok": ok,
                      "coverage_problems": len(report["lines"]["coverage_problems"]),
                      "via_problems": len(report["vias"]["problems"]),
                      "drift": len(report["placement_drift"])}, ensure_ascii=False))
    return 0 if ok else 1
