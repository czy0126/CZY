"""Probe the PCB document's own netlist model on a copy of the candidate.

`sys_Tool.netlistComparison(schematic, pcb)` returned 65 net rows whose PCB side
was empty for every net, while the native readback shows the same 65 net names
and a net on every one of the 299 pads. This probe asks the PCB API itself
(`pcb_Net.getNetlist`, `getAllPrimitivesByNet`, `getAllNets`) so the emptiness
is attributed to the board or to the comparator, not assumed.

  python hardware/dcx_main/g1/probe_pcb_netlist_model.py --capture

Read-only: opens a throwaway copy, never imports and never saves. The receipt is
refused if it already exists, and both the copy and the candidate must keep
their SHA-256.

One invoke carries exactly one cheap question. A first bundled body answered
nothing: it mixed `getAllNetsName` with `getNetlist`, exceeded the 60 s CLI
budget three times, and every attempt was discarded whole
(`lr_signal_pcb_netlist_model_attempt2_three_timeouts.json`). Splitting means a
slow call costs only its own probe.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
from pathlib import Path

import apply_increment as A
import run_driver_drc as D
import route_lr_signal_stubs as S

HERE = Path(__file__).resolve().parent
BOARD = (HERE / S.CANDIDATE).resolve()
READBACK = HERE / "lr_repack_readback.json"
PROBE = HERE / ".tmp_pcb_netlist_model.eprj2"
PREFIX = "lr_signal_pcb_netlist_model"
RAW = HERE / f"{PREFIX}.json"

#: Cheapest question first; `getNetlist` is last because it generates a full
#: netlist string and is the most likely to exceed the CLI budget.
PROBES: list[tuple[str, str]] = [
    ("board_and_open_pcb", """
return await (async () => {
  let info, board;
  for (let i = 0; i < 20 && !board; i++) {
    info = await eda.dmt_Project.getCurrentProjectInfo();
    board = (info && info.data || []).find(b => b && b.schematic && b.schematic.uuid && b.pcb && b.pcb.uuid);
    if (!board) await new Promise(r => setTimeout(r, 500));
  }
  if (!board) throw new Error('schematic/PCB pair missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 2500));
  return { name: board.name, pcbUuid: board.pcb.uuid };
})();
"""),
    ("net_names", """
return await (async () => {
  const names = await eda.pcb_Net.getAllNetsName();
  return { type: typeof names, count: Array.isArray(names) ? names.length : null,
           sample: Array.isArray(names) ? names.slice(0, 5) : null, names };
})();
"""),
    ("primitives_by_net", """
return await (async () => {
  const out = {};
  for (const net of ['VOUT', 'PGND', 'SEC1_A', 'PRI_T1', 'CR_CT']) {
    const v = await eda.pcb_Net.getAllPrimitivesByNet(net);
    out[net] = { type: typeof v, count: Array.isArray(v) ? v.length : null };
  }
  return out;
})();
"""),
    ("all_nets", """
return await (async () => {
  const all = await eda.pcb_Net.getAllNets();
  return { type: typeof all, count: Array.isArray(all) ? all.length : null,
           with_length: Array.isArray(all) ? all.filter(n => n && n.length > 0).length : null,
           sample: Array.isArray(all) ? all.slice(0, 3) : null };
})();
"""),
    ("pcb_netlist", """
return await (async () => {
  const out = { label: 'JLCEDA' };
  const v = await eda.pcb_Net.getNetlist('JLCEDA');
  out.type = typeof v;
  if (typeof v === 'string') {
    out.length = v.length;
    out.lines = v.split(/\\r?\\n/).length;
    out.head = v.slice(0, 400);
  } else {
    out.value = String(v);
  }
  return out;
})();
"""),
    ("sch_netlist", """
return await (async () => {
  const out = {};
  try {
    const s = await eda.sch_Netlist.getNetlist();
    out.type = typeof s;
    out.length = typeof s === 'string' ? s.length : null;
    out.head = typeof s === 'string' ? s.slice(0, 200) : String(s);
  } catch (e) {
    out.error = String((e && e.message) || e);
  }
  return out;
})();
"""),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readback_summary() -> dict:
    """What the native readback says about nets and pads, for the same board."""
    value = json.loads(READBACK.read_text(encoding="utf-8"))["value"]
    pad_nets = collections.Counter(p.get("Net") for p in value["pads"])
    anonymous = [p for p in value["pads"] if not p.get("ref") or not p.get("PadNumber")]
    return {
        "components": len(value["components"]),
        "pads": len(value["pads"]),
        "net_names": len(value["nets"]),
        # Empty string is an unassigned pad; counting only ``None`` reported 0.
        "pads_with_empty_net_name": pad_nets.get("", 0),
        "distinct_pad_nets": len([n for n in pad_nets if n]),
        "anonymous_pads": len(anonymous),
        "anonymous_pad_terminals": sorted({str(p.get("PadNumber")) for p in anonymous}),
        "net_names_absent_from_pads": sorted(set(value["nets"]) - set(pad_nets)),
    }


def invoke_with_retry(session: str, code: str, tries: int) -> tuple[dict, list[dict]]:
    """Run one body, retrying only when the caller allows it.

    A wedged session answers every body at 59 750 ms, and retrying inside it did
    not help here (three of three attempts failed); recovery is
    ``lceda-pro stop`` + reopen (docs/agent/EDA.md §Import Changes 差异).
    Only the first body keeps one retry, so a slow probe cannot eat the run.
    """
    attempts: list[dict] = []
    raw: dict = {}
    for index in range(tries):
        raw = A.invoke(session, code)
        attempts.append({"attempt": index + 1, "ok": raw.get("ok"),
                         "error": raw.get("error"), "durationMs": raw.get("durationMs")})
        if raw.get("ok"):
            break
    return raw, attempts


def run() -> int:
    if RAW.exists():
        raise SystemExit("PCB netlist-model receipt already exists; not overwriting evidence")
    candidate_sha = sha256(BOARD)
    shutil.copy2(BOARD, PROBE)
    if sha256(PROBE) != candidate_sha:
        raise SystemExit("Probe copy is not byte-identical to the candidate")
    session = A.open_and_ping(PROBE, PREFIX, "open")
    if not session:
        raise SystemExit("Editor not available")
    results = []
    try:
        for index, (name, body) in enumerate(PROBES):
            raw, attempts = invoke_with_retry(session, body, tries=3 if index == 0 else 1)
            results.append({"probe": name, "ok": raw.get("ok"), "error": raw.get("error"),
                            "value": raw.get("value"), "attempts": attempts, "body": body.strip()})
            if name == "board_and_open_pcb" and not raw.get("ok"):
                break  # every later probe would ask an unopened PCB
    finally:
        A.dump(PREFIX, "close", D.call(D.build_close_args(session)))
    by_name = {row["probe"]: row for row in results}
    receipt = {
        "status": "PCB_NETLIST_MODEL_PROBE",
        "attempted": "read-only: opened a copy, asked the PCB API one question per invoke, never saved",
        "candidate": BOARD.relative_to(S.ROOT).as_posix(),
        "candidate_sha256": candidate_sha,
        "probe_copy_sha256": candidate_sha,
        "probe_copy_sha256_after": sha256(PROBE),
        "editor_ok": all(row["ok"] for row in results) and len(results) == len(PROBES),
        "board": (by_name.get("board_and_open_pcb") or {}).get("value"),
        "net_names": (by_name.get("net_names") or {}).get("value"),
        "primitives_by_net": (by_name.get("primitives_by_net") or {}).get("value"),
        "all_nets": (by_name.get("all_nets") or {}).get("value"),
        "pcb_netlist": (by_name.get("pcb_netlist") or {}).get("value"),
        "sch_netlist": (by_name.get("sch_netlist") or {}).get("value"),
        "native_readback_summary": readback_summary(),
        "probes": results,
        "not_erc_not_drc_not_fab": True,
    }
    RAW.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps({k: receipt[k] for k in ("editor_ok", "native_readback_summary")},
                     ensure_ascii=False, indent=2))
    print(json.dumps([{k: row.get(k) for k in ("probe", "ok", "error", "attempts")}
                      | {"value": row.get("value") if row["probe"] != "net_names" else {
                          "count": (row.get("value") or {}).get("count"),
                          "sample": (row.get("value") or {}).get("sample")}}
                      for row in results], ensure_ascii=False, indent=2))
    return 0 if receipt["editor_ok"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(run())
