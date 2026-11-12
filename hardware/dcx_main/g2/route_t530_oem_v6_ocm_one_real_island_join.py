"""V6 one-shot native OCM island join based only on saved+reopened V5 OEM board.

This is a low-current, control-only experimental ECO. It does not route
VOUT/PGND, transformer, SR gate or Kelvin nets and is NEVER for fabrication.

--check: independent dry-run geometry and source-provenance preflight.
--apply: make a new native .eprj2 copy exactly once, then verify by actual DRC.
--resume: read-only native reopen and verify; never re-apply a timed-out batch.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import time

import route_t530_oem_v5_one_real_island_join as V

HERE = Path(__file__).resolve().parent
SOURCE = V.TARGET
TARGET = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V6_REAL_OCM_R17_C11_LINK_NOT_FOR_FAB.eprj2"
PREFIX = "g2_t530_oem_v6_ocm_r17_c11"
PLAN = HERE / (PREFIX + "_route_plan.json")
DELTA = HERE / (PREFIX + "_drc_delta.json")
RAW = HERE / (PREFIX + "_drc_raw.json")
REOPEN = HERE / (PREFIX + "_reopen_readback.json")
NET = "OCM"
START = "R17.2"
END = "C11.2"
CORRIDOR_Y = 63.4
EXPECTED_COUNTS = (77, 443, 400, 90, 65)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(tag, value):
    (HERE / (PREFIX + "_" + tag + ".json")).write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n")


def frozen_source():
    accepted = json.loads(V.DELTA.read_text(encoding="utf-8"))
    if not SOURCE.is_file() or sha(SOURCE) != accepted["candidate_sha256"]:
        raise ValueError("V5 native source differs from saved+reopened accepted candidate")
    if accepted["actual_native_drc"] != {"Connection Error": 172, "Netlist Error": 1}:
        raise ValueError("V5 accepted native DRC baseline changed")
    native = json.loads(V.REOPEN.read_text(encoding="utf-8"))
    if native.get("ok") is not True:
        raise ValueError("V5 native reopen evidence absent")
    value = native["value"]
    if tuple(len(value[k]) for k in ("components", "pads", "lines", "vias", "nets")) != EXPECTED_COUNTS:
        raise ValueError("V5 native object count changed")
    V.verify(value, V.plan())
    native_drc = json.loads(V.RAW.read_text(encoding="utf-8"))
    if not native_drc.get("ok") or V.A.R.categories(native_drc) != accepted["actual_native_drc"]:
        raise ValueError("V5 native original DRC receipt mismatch")
    return value, accepted


def geometry_plan():
    native, accepted = frozen_source()
    groups = V.ISLAND.islands(native, {NET})[NET]["islands"]
    hits = [[i for i, group in enumerate(groups) if name in group["pads"]]
            for name in (START, END)]
    if any(len(q) != 1 for q in hits) or hits[0] == hits[1]:
        raise ValueError("OCM endpoints do not belong to distinct unique native copper islands")
    a = V.pad(native["pads"], NET, "R17", "2")
    b = V.pad(native["pads"], NET, "C11", "2")
    if not (0.5 <= math.dist(a, b) < 9):
        raise ValueError("Unexpected OCM endpoint geometry")
    points = [a, (a[0], CORRIDOR_Y), (b[0], CORRIDOR_Y), b]
    core = V.MAG.load_current()
    magnets = json.loads(V.MAG.MAG.read_text(encoding="utf-8"))
    body, tf, _ = V.MAG.core_rects(core, magnets)
    ferrites = [("Lr", body), *tf.items()]
    tracks, problems = [], []
    for i, (start, end) in enumerate(zip(points, points[1:])):
        wire = V.track(NET, start, end)
        for hit in V.C._conflicts_line(wire, native):
            problems.append(f"line{i}/unlike_{hit}")
        for name, rect in ferrites:
            box = tuple(rect[k] for k in ("left", "top", "right", "bottom"))
            gap = V.R._segment_rect(start, end, box) - V.STUB_WIDTH / 2
            if gap < 0.5:
                problems.append(f"line{i}/ferrite_{name}/gap_{gap:.3f}")
        tracks.append(wire)
    if len(tracks) != 3 or {q["net"] for q in tracks} != {NET}:
        raise ValueError("Unreviewed route scope expansion")
    return {
        "schema": "D1_G2_NATIVE_V6_REAL_OCM_SINGLE_COPPER_ISLAND_JOIN",
        "source_eprj2_sha256": sha(SOURCE),
        "source_native_readback_canonical_lf_sha256": V.ISLAND.sha_lf(V.REOPEN),
        "native_drc_before": accepted["actual_native_drc"],
        "path": {"net": NET, "start": START, "end": END,
                 "path_mm": [list(q) for q in points],
                 "source_copper_islands_distinct": True},
        "tracks": tracks,
        "preflight_problems": sorted(set(problems)),
        "high_current_and_sense_nets_untouched": True,
        "oem_72_components_schematic_parity_verified": False,
        "100A_power_copper_qualified": False,
        "manufacturing_approved": False,
    }


def verify_target(actual, order):
    original, _ = frozen_source()
    if tuple(len(actual[k]) for k in ("components", "pads", "vias", "nets")) != (77, 443, 90, 65):
        raise ValueError("Native V6 lost original component/pad/via/net")
    for key in ("components", "pads", "vias", "nets"):
        if Counter(json.dumps(v, sort_keys=True) for v in actual[key]) != Counter(
                json.dumps(v, sort_keys=True) for v in original[key]):
            raise ValueError("Native V6 changed original " + key)
    for old in original["lines"]:
        if not V.C.coverage(old, actual["lines"]) and not V.C.physical_copper_covers(
                old, actual["lines"], full_original_width=True):
            raise ValueError("Native V6 erased source copper " + str(old["id"]))
    for new in order["tracks"]:
        if not V.C.coverage(new, actual["lines"]) and not V.C.physical_copper_covers(
                new, actual["lines"], full_original_width=False):
            raise ValueError("Native V6 did not write requested copper")
    groups = V.ISLAND.islands(actual, {NET})[NET]["islands"]
    joins = [[i for i, group in enumerate(groups) if name in group["pads"]]
             for name in (START, END)]
    if any(len(q) != 1 for q in joins) or joins[0] != joins[1]:
        raise ValueError("OCM target copper islands remain separate after EDA save")
    return {"old_native_copper_preserved": True,
            "new_ocm_tracks_physically_covered": len(order["tracks"]),
            "ocm_target_island_joined": True,
            "manufacturer_approved": False}


def open_board(stage):
    reply = V.A.D.call(V.A.D.build_open_args(TARGET), timeout_s=110)
    dump(stage + "_open", reply)
    session = (reply.get("value") or {}).get("sessionId")
    if not session:
        return None
    time.sleep(V.A.D.SETTLE_S)
    ping = V.A.D.call(V.A.D.build_ping_args(session), timeout_s=32)
    dump(stage + "_ping", ping)
    if not ping.get("ok"):
        dump(stage + "_close", V.A.D.call(V.A.D.build_close_args(session)))
        return None
    # The renderer can accept return 1 while every actual EDA API call hangs.
    # Establish real document readiness BEFORE even attempting a write.  If
    # this probe times out, do not retry a possibly still-running mutation.
    native_probe = V.A.invoke(session, V.A.READ_JS.read_text(encoding="utf-8"))
    probe_value = native_probe.get("value") or {}
    measured = tuple(len(probe_value.get(k, [])) for k in
                     ("components", "pads", "lines", "vias", "nets"))
    ready = native_probe.get("ok") is True and measured == EXPECTED_COUNTS
    dump(stage + "_native_probe", {"ok": ready, "observed_counts": measured,
                                     "source_shape_verified": ready,
                                     "error": native_probe.get("error")})
    if not ready:
        dump(stage + "_close", V.A.D.call(V.A.D.build_close_args(session)))
        return None
    return session


def resume():
    order = geometry_plan()
    if order["preflight_problems"]:
        raise ValueError("OCM V6 preflight unsafe")
    if not PLAN.is_file() or json.loads(PLAN.read_text(encoding="utf-8")) != order:
        raise ValueError("No matching frozen V6 source-locked route plan")
    if not TARGET.is_file() or sha(TARGET) == sha(SOURCE):
        raise ValueError("No saved V6 native candidate")
    candidate_before = sha(TARGET)
    session = open_board("reopen")
    if not session:
        return 1
    try:
        readback = V.A.invoke(session, V.A.READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback", readback)
        if not readback.get("ok"):
            raise ValueError("V6 genuine EasyEDA readback failed")
        receipt = verify_target(readback["value"], order)
        drc = V.A.invoke(session, V.A.DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw", drc)
        if not drc.get("ok"):
            raise ValueError("V6 genuine EasyEDA DRC failed")
    finally:
        dump("reopen_close", V.A.D.call(V.A.D.build_close_args(session)))
    if sha(TARGET) != candidate_before:
        raise ValueError("V6 read-only verification modified native PCB")
    after = V.A.R.categories(drc)
    before = order["native_drc_before"]
    if (after.get("Connection Error", 9999) >= before["Connection Error"]
            or after.get("Netlist Error", 9999) > before["Netlist Error"]
            or after.get("Physical Error", 0)):
        raise ValueError("V6 no genuine improvement in native DRC or new physical errors")
    summary = {"status": "REAL_NATIVE_V6_OCM_REOPEN_DRC_NOT_FOR_FAB",
               "source_sha256": sha(SOURCE), "candidate_sha256": sha(TARGET),
               "plan_sha256": sha(PLAN), "previous_native_drc": before,
               "actual_native_drc": after, "reopen": receipt,
               "100A_busbar_or_protection_approved": False,
               "fabrication_approved": False}
    dump("drc_delta", summary)
    print(json.dumps(summary, indent=2))
    return 0


def apply():
    order = geometry_plan()
    if order["preflight_problems"]:
        raise ValueError("Unsafe physical native OCM route: " + str(order["preflight_problems"]))
    if TARGET.exists() or PLAN.exists():
        raise FileExistsError("Never overwrite/reapply an existing V6 native trial")
    PLAN.write_text(json.dumps(order, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    original_sha = sha(SOURCE)
    shutil.copy2(SOURCE, TARGET)
    session = open_board("apply")
    if not session:
        return 1
    saved = False
    try:
        reply = V.A.invoke(session, V.C.js_tracks(order["tracks"]))
        dump("apply_batch_1", reply)
        if not reply.get("ok") or not (reply.get("value") or {}).get("all_created"):
            raise RuntimeError("Native one-shot OCM write unverified: never repeat --apply")
        saved_result = V.A.invoke(session, "return await eda.pcb_Document.save();")
        dump("apply_save", saved_result)
        saved = saved_result.get("ok") and saved_result.get("value") is True
        if saved:
            time.sleep(30)
    finally:
        dump("apply_close", V.A.D.call(V.A.D.build_close_args(session)))
    if not saved or sha(SOURCE) != original_sha or sha(TARGET) == original_sha:
        raise ValueError("Native V6 save not confirmed; do not retry --apply")
    return resume()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    switches = parser.add_mutually_exclusive_group(required=True)
    for item in ("check", "apply", "resume"):
        switches.add_argument("--" + item, action="store_true")
    args = parser.parse_args()
    if args.check:
        plan = geometry_plan()
        print(json.dumps({k: v for k, v in plan.items() if k != "tracks"}, indent=2))
        return int(bool(plan["preflight_problems"]))
    return apply() if args.apply else resume()


if __name__ == "__main__":
    raise SystemExit(main())
