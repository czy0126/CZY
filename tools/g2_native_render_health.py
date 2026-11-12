"""One-process, read-only EasyEDA native render-health check for an OEM PCB.

Important: a CLI 'open' in one Runner job does not guarantee the headless
renderer survives in a different job. Keep open, settle, actual EDA API,
and source-hash verification inside one Python process. Never save.
A visible GUI is always left open; only its own isolated headless test can close.

Source and a uniquely named temporary copy are immutable. Diagnostic evidence
is explicitly NOT a fabrication / netlist / clearance approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
G2 = ROOT / "hardware/dcx_main/g2"
sys.path.insert(0, str(G1))
import run_driver_drc as D  # noqa: E402

DEFAULT_BOARD = (G2 / "dcx_main_board_g2_T530_OEM_DENSITY_B_V5_REAL_VCC12S_C111_C112_LINK_NOT_FOR_FAB.eprj2")
READBACK = G1 / "read_driver_route.js"

# A real API call, unlike return 1, is necessary to establish render health.
INFO_JS = """return await (async()=>{
  const p=await eda.dmt_Project.getCurrentProjectInfo();
  return {project_present:!!p, friendly_name:p?.friendlyName??null,
    board_uuids:Array.isArray(p?.data)?
      p.data.filter(x=>!!x?.pcb?.uuid).map(x=>x.pcb.uuid):[]};
})();"""

OPEN_DOCUMENT_JS = """return await (async()=>{
  const p=await eda.dmt_Project.getCurrentProjectInfo();
  const b=p?.data?.find(x=>x?.pcb?.uuid);
  if(!b)throw new Error("native PCB document absent");
  await eda.dmt_EditorControl.openDocument(b.pcb.uuid);
  return {opened_document_uuid:b.pcb.uuid};
})();"""

COUNT_JS = """return await (async()=>{
  const q=await eda.pcb_PrimitiveComponent.getAll();
  return {components:q.length};
})();"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarise(kind: str, response: dict) -> dict:
    value = response.get("value")
    compact = {"ok": response.get("ok") is True,
               "error": response.get("error")}
    if kind == "full_readback" and compact["ok"] and isinstance(value, dict):
        compact["counts"] = {k: len(value.get(k, []))
                             for k in ("components", "pads", "lines", "vias", "nets")}
        compact["polylines"] = value.get("polylines")
    elif kind == "open":
        compact["session_present"] = bool((value or {}).get("sessionId"))
        compact["headless"] = (value or {}).get("headless")
    elif kind == "ping":
        compact["value"] = value
    elif kind in ("project_info", "open_document", "components"):
        compact["value"] = value
    compact["duration_ms"] = response.get("durationMs")
    return compact


def reset_if_no_active_sessions() -> dict:
    """An opt-in reset that refuses to interrupt an active EDA editor."""
    listing = D.call([str(D.LEDA), "session", "list"], timeout_s=20)
    if not listing.get("ok") or not isinstance(listing.get("value"), list):
        raise RuntimeError("Cannot establish EDA session ownership; refusing reset")
    active = [x for x in listing["value"] if x.get("status") not in ("closed",)]
    if active:
        raise RuntimeError("Active EasyEDA sessions exist; refusing global stop")
    stop = D.call([str(D.LEDA), "stop"], timeout_s=40)
    if not stop.get("ok"):
        raise RuntimeError("EasyEDA stop did not acknowledge graceful reset")
    time.sleep(4)
    return {"ok": True, "closed_session_count": len(listing["value"]),
            "active_sessions_touched": 0, "command": "graceful_stop"}


def run(board: Path, *, settle_s: float = 45, out: Path | None = None,
        reset_before_open: bool = False, visible_editor: bool = False) -> dict:
    board = board.resolve()
    if not board.is_file() or board.suffix.lower() != ".eprj2":
        raise ValueError("Only existing native .eprj2 sources are permitted")
    original = sha(board)
    out = out or (G2 / "g2_native_render_health_readonly_NOT_FOR_FAB.json")
    if out.exists():
        raise FileExistsError("Do not overwrite previous native health diagnosis")
    tempdir = Path(tempfile.mkdtemp(prefix="czy_native_health_"))
    copied = tempdir / board.name  # preserve the *exact* basename
    shutil.copy2(board, copied)
    if sha(copied) != original:
        raise ValueError("Native temporary copy does not match original bytes")

    steps: dict[str, dict] = {}
    session = None
    actual_read = False
    try:
        if reset_before_open:
            steps["reset_before_open"] = reset_if_no_active_sessions()
        open_args = D.build_open_args(copied)
        if visible_editor:
            # Some document activation paths behave differently in a hidden
            # render. This is a distinct experiment, never a silent fallback.
            assert open_args[-2:] == ["--headless", "true"]
            open_args[-1] = "false"
        opened = D.call(open_args, timeout_s=120)
        steps["open"] = summarise("open", opened)
        session = (opened.get("value") or {}).get("sessionId")
        if session:
            time.sleep(settle_s)
            ping = D.call(D.build_ping_args(session), timeout_s=24)
            steps["ping"] = summarise("ping", ping)
            if ping.get("ok"):
                info = D.call(D.build_invoke_args(session, INFO_JS), timeout_s=80)
                steps["project_info"] = summarise("project_info", info)
                if info.get("ok") and (info.get("value") or {}).get("board_uuids"):
                    doc = D.call(D.build_invoke_args(session, OPEN_DOCUMENT_JS), timeout_s=80)
                    steps["open_document"] = summarise("open_document", doc)
                    if doc.get("ok") and (doc.get("value") or {}).get("opened_document_uuid"):
                        c = D.call(D.build_invoke_args(session, COUNT_JS), timeout_s=80)
                        steps["components"] = summarise("components", c)
                    else:
                        c = {"ok": False}
                    if c.get("ok") and (c.get("value") or {}).get("components") == 77:
                        r = D.call(D.build_invoke_args(
                            session, READBACK.read_text(encoding="utf-8")), timeout_s=88)
                        steps["full_readback"] = summarise("full_readback", r)
                        actual_read = (r.get("ok") is True
                            and steps["full_readback"]["counts"] ==
                            {"components":77,"pads":443,"lines":400,"vias":90,"nets":65})
    finally:
        if session and visible_editor:
            # The user explicitly needs the visible EDA window to remain open.
            # Never close a GUI session even when a read-only diagnostic fails.
            steps["visible_gui_retained"] = {"ok": True, "headless": False}
        elif session:
            steps["close"] = summarise("close", D.call(D.build_close_args(session), timeout_s=30))
    unchanged = sha(board) == original and sha(copied) == original
    result = {
        "schema": "D1_G2_NATIVE_ONE_PROCESS_RENDER_HEALTH_V1",
        "status": ("READBACK_READY_NOT_FOR_FAB" if actual_read and unchanged
                   else "NATIVE_READBACK_NOT_VERIFIED_NOT_FOR_FAB"),
        "source": board.relative_to(ROOT).as_posix() if board.is_relative_to(ROOT) else board.name,
        "source_sha256": original,
        "original_source_unchanged": sha(board) == original,
        "temporary_copy_unchanged": sha(copied) == original,
        "temporary_copy_name_matches_source": copied.name == board.name,
        "settle_seconds": settle_s,
        "reset_before_open": reset_before_open,
        "visible_editor": visible_editor,
        "opened_and_probed_same_process": True,
        "steps": steps,
        "fabrication_approved": False,
        "native_netlist_parity_approved": False,
        "drc_approved": False,
        "write_attempted": False,
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    a.add_argument("--settle-seconds", type=float, default=45)
    a.add_argument("--out", type=Path, default=G2 / "g2_native_render_health_readonly_NOT_FOR_FAB.json")
    a.add_argument("--reset-before-open", action="store_true",
                   help="only gracefully reset EDA when no active editor sessions exist")
    a.add_argument("--visible-editor", action="store_true",
                   help="deliberate visible-window read-only test; GUI stays open")
    args = a.parse_args()
    if not (20 <= args.settle_seconds <= 90):
        a.error("settle must be in [20,90] seconds")
    report = run(args.board, settle_s=args.settle_seconds, out=args.out,
                 reset_before_open=args.reset_before_open,
                 visible_editor=args.visible_editor)
    return 0 if report["status"] == "READBACK_READY_NOT_FOR_FAB" else 1


if __name__ == "__main__":
    raise SystemExit(main())
