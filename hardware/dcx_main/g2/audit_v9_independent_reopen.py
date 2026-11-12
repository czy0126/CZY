"""One-shot INDEPENDENT visible EasyEDA reopen and read-only V9 native audit.

Opens an exact-byte copy of the SAVED .eprj2 in a separate visible editor
session. Never writes the original V9 or the three existing GUI sessions.
A native failed/timeout request is never replayed; the receipt is fail closed.
NOT_FOR_FAB: 100A metal, Kelvin, magnetic pads, D0 still require validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "hardware/dcx_main/g1"))
import g2_v9_real_t530_components as V9
import g2_v9_sch_cout72 as SCH
import g2_oem_net_islands as ISLAND
import route_open_connections as ROUTE

D = V9.D
SOURCE = V9.V9
EVIDENCE = HERE / "g2_v9_independent_gui_reopen_verified_NOT_FOR_FAB.json"
ATTEMPT = HERE / "g2_v9_independent_gui_reopen_attempt_NOT_FOR_FAB.json"
CAP_COUNTS = {"components": 149, "pads": 443, "lines": 407, "vias": 93, "nets": 65}
DRC_COUNTS = {"Connection Error": 168, "Netlist Error": 1}


def record(path: Path, data: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Never replay or overwrite native verification: {path}")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def invoke(sid: str, code: str, timeout_ms: int = 59000) -> dict:
    return D.call(D.build_invoke_args(sid, code, timeout_ms), timeout_s=76)


def required(reply: dict, what: str):
    if reply.get("ok") is not True:
        raise RuntimeError(f"{what}: native API failed: {reply.get('error')}")
    return reply.get("value")


def same_original_sessions(sessions_before: dict, sessions_after: dict) -> bool:
    def existing(r):
        return {q["sessionId"] for q in (r.get("value") or [])
                if q.get("headless") is False and q.get("status") == "alive"}
    return existing(sessions_before).issubset(existing(sessions_after))


def validate_saved_source():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    expected = json.loads(V9.HERE.joinpath(
        "g2_v9_vout_source_bottom_feeder_verified_NOT_FOR_FAB.json"
    ).read_text(encoding="utf-8"))
    current = V9.sha(SOURCE)
    if current != expected["source_sha256"]:
        raise ValueError("V9 saved binary source SHA differs from native feeder receipt")
    if V9.sha(V9.V8) != V9.EXPECTED_V8_SHA:
        raise ValueError("Frozen V8 changed")
    return current


def run() -> dict:
    if ATTEMPT.exists() or EVIDENCE.exists():
        raise FileExistsError("Independent GUI reopen already attempted: do NOT replay")
    original = validate_saved_source()
    before = D.call([str(D.LEDA), "session", "list"], timeout_s=20)
    required(before, "list pre-existing GUI sessions")
    scratch = Path(tempfile.mkdtemp(prefix="czy_v9_readonly_reopen_", dir=str(HERE)))
    target = scratch / SOURCE.name  # filename must be identical for project name
    shutil.copy2(SOURCE, target)
    if V9.sha(target) != original:
        raise RuntimeError("Exact-byte verification copy failed")
    record(ATTEMPT, {
        "status": "INDEPENDENT_GUI_REOPEN_SUBMITTED_ONCE",
        "source_sha256": original,
        "copy_sha256": V9.sha(target),
        "preexisting_visible_sessions": sum(x.get("status") == "alive" and
                  x.get("headless") is False for x in before["value"]),
        "never_write_original": True, "do_not_replay_on_error": True,
        "fabrication_approved": False
    })
    sid = None
    result = {"status": "INDEPENDENT_REOPEN_NOT_VERIFIED_NOT_FOR_FAB",
              "source_sha256": original, "native_saved_source_unchanged": False,
              "copy_unchanged": False, "other_gui_preserved": False,
              "fabrication_approved": False, "100A_qualified": False}
    try:
        args = D.build_open_args(target)
        if args[-2:] != ["--headless", "true"]:
            raise RuntimeError("Unrecognized native open invocation shape")
        args[-1] = "false"  # one independent visible read-only GUI
        opened = D.call(args, timeout_s=120)
        sid = required(opened, "open saved V9 project copy")["sessionId"]
        result["independent_session"] = sid
        time.sleep(D.SETTLE_S + 3)
        required(D.call(D.build_ping_args(sid), timeout_s=20), "renderer ping")
        info_js = """return await (async()=>{
          const p=await eda.dmt_Project.getCurrentProjectInfo();
          const pcb=p?.data?.find(x=>x?.pcb?.uuid)?.pcb?.uuid;
          const sch=p?.data?.find(x=>x?.schematic?.uuid)?.schematic;
          return {name:p?.friendlyName,pcb,pages:sch?.page?.map(q=>({name:q.name,uuid:q.uuid}))};
        })();"""
        info = required(invoke(sid, info_js, 22000), "saved native project info")
        if info.get("name") != SOURCE.stem or not info.get("pcb"):
            raise RuntimeError("Reopened wrong project or no native PCB document")
        matched = [x for x in info.get("pages") or [] if x["name"] == SCH.PAGE]
        if len(matched) != 1:
            raise RuntimeError("Saved native Cout72 schematic page absent or duplicated")
        page_id = matched[0]["uuid"]
        read_js = (ROOT / "hardware/dcx_main/g1/read_driver_route.js").read_text("utf-8")
        native = required(invoke(sid, read_js), "read saved PCB primitives")
        sizes = {k: len(native[k]) for k in CAP_COUNTS}
        if sizes != CAP_COUNTS:
            raise RuntimeError(f"Reopened PCB count drift {sizes} != {CAP_COUNTS}")
        refs = [r["ref"] for r in native["components"]]
        if len(set(refs)) != len(refs) or len(refs) != 149:
            raise RuntimeError("Duplicate designators in saved native PCB")
        caps = {}
        for pad in native["pads"]:
            ref = pad.get("ref")
            if ref and ref.startswith("CHB"):
                caps.setdefault(ref, {})[str(pad.get("PadNumber"))] = pad.get("Net")
            if str(pad.get("PadNumber", "")).startswith("CHB") and ref is None:
                raise RuntimeError("Legacy naked CHB pad in saved native board")
        if set(caps) != {f"CHB{i:02d}" for i in range(1, 73)}:
            raise RuntimeError("Saved native PCB missing CHB instances")
        if any(v != {"1": "VOUT", "2": "PGND"} for v in caps.values()):
            raise RuntimeError("Saved native capacitor polarity/net mismatch")
        islands = ISLAND.islands(native, {"VOUT", "PGND"})
        count = {name: len(islands[name]["islands"]) for name in ("VOUT","PGND")}
        vout = islands["VOUT"]["islands"]
        if len(vout) != 1 or not any("RAW.CTAP" in x["pads"] and
                                      "CHB01.1" in x["pads"] for x in vout):
            raise RuntimeError("Saved VOUT source-to-cap bank physical copper not joined")
        sch_value = required(invoke(sid, SCH.js_verify(page_id)), "read saved Cout72 schematic")
        if (sch_value.get("count") != 72 or sch_value.get("wires") != 144
            or sch_value.get("physical_component_ref_count") != 72
            or sch_value.get("issues")):
            raise RuntimeError("Reopened schematic Cout72 pin/wire parity failed")
        drc = invoke(sid, D.JS.read_text(encoding="utf-8"))
        parsed = ROUTE.categories(drc)
        if any(parsed.get(k) != v for k, v in DRC_COUNTS.items()):
            raise RuntimeError(f"Saved native DRC changed {parsed}")
        if any(v for k, v in parsed.items() if k == "Physical Error"):
            raise RuntimeError("Native physical DRC is not zero")
        result.update({
            "status": "INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED_NOT_FOR_FAB",
            "native_counts": sizes,
            "native_capacitor_instances_and_144_pins_verified": True,
            "native_schematic_72_symbols_144_wires_verified": True,
            "native_pcb_schematic_cout72_pin_parity": True,
            "native_drc": parsed,
            "vout_and_pgnd_copper_islands": count,
            "vout_ctap_and_cout_saved_copper_joined": True,
            "other_77_part_pin_parity_verified": False,
            "magnetic_physical_pads_verified": False
        })
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        # Only close the NEW verification session. NEVER touch V5/V8/V9 GUIs.
        if sid:
            closed = D.call(D.build_close_args(sid), timeout_s=36)
            result["new_verification_gui_closed"] = closed.get("ok") is True
        else:
            result["new_verification_gui_closed"] = None
        after = D.call([str(D.LEDA), "session", "list"], timeout_s=20)
        result["other_gui_preserved"] = (
            after.get("ok") is True and same_original_sessions(before, after)
        )
        result["native_saved_source_unchanged"] = V9.sha(SOURCE) == original
        result["copy_unchanged"] = V9.sha(target) == original
        result["copy_was_opened_from_distinct_path"] = True
        result["source_sha256_after"] = V9.sha(SOURCE)
        if result["status"].startswith("INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED") and (
            not result["other_gui_preserved"] or not result["native_saved_source_unchanged"]
            or not result["copy_unchanged"]):
            result["status"] = "INDEPENDENT_REOPEN_SAFETY_CHECK_FAILED_NOT_FOR_FAB"
        if result.get("new_verification_gui_closed") is True:
            try:
                target.unlink()
                scratch.rmdir()
                result["temporary_native_copy_cleaned"] = True
            except OSError:
                result["temporary_native_copy_cleaned"] = False
        record(EVIDENCE, result)
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    x = p.add_mutually_exclusive_group(required=True)
    x.add_argument("--check", action="store_true")
    x.add_argument("--verify", action="store_true")
    a = p.parse_args()
    if a.check:
        print(json.dumps({"source_sha256":validate_saved_source(),
                          "source":SOURCE.name,
                          "already_attempted":ATTEMPT.exists() or EVIDENCE.exists()}))
        return 0
    value=run()
    print(json.dumps(value,ensure_ascii=False,indent=2))
    return 0 if value["status"] == "INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED_NOT_FOR_FAB" else 1


if __name__ == "__main__":
    raise SystemExit(main())
