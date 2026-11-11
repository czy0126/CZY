"""Export the candidate PCB's own netlist (JLCEDA format) on a throwaway copy.

`pcb_Net.getNetlist('JLCEDA')` returns a real 165 kB netlist even though
`getNetlistFile` is null on a `--path`-opened project, and even though
`sys_Tool.netlistComparison` reported an empty PCB side for every net. This
export is what makes the pin pairing checkable offline against the comparator's
schematic-side pin lists and the native pad readback.

  python hardware/dcx_main/g1/export_pcb_netlist.py --export

Read-only: opens a copy, never imports and never saves. Both receipts refuse to
overwrite, and both the copy and the candidate must keep their SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import apply_increment as A
import run_driver_drc as D
import route_lr_signal_stubs as S

HERE = Path(__file__).resolve().parent
BOARD = (HERE / S.CANDIDATE).resolve()
PROBE = HERE / ".tmp_pcb_netlist_export.eprj2"
PREFIX = "lr_signal_pcb_netlist_export"
RAW = HERE / f"{PREFIX}.json"
NETLIST = HERE / "lr_repack_pcb_netlist_jlc.json"
BODY = """
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
  const text = await eda.pcb_Net.getNetlist('JLCEDA');
  return { pcbUuid: board.pcb.uuid, type: typeof text, text };
})();
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> int:
    if RAW.exists() or NETLIST.exists():
        raise SystemExit("PCB netlist export already exists; not overwriting evidence")
    candidate_sha = sha256(BOARD)
    shutil.copy2(BOARD, PROBE)
    if sha256(PROBE) != candidate_sha:
        raise SystemExit("Probe copy is not byte-identical to the candidate")
    session = A.open_and_ping(PROBE, PREFIX, "open")
    if not session:
        raise SystemExit("Editor not available")
    try:
        # One retry only: a wedged session answers every body at 59 750 ms and
        # recovery is `lceda-pro stop` + reopen (docs/agent/EDA.md); this body
        # itself takes ~1 s once the session is healthy.
        attempts = []
        raw: dict = {}
        for index in range(2):
            raw = A.invoke(session, BODY)
            attempts.append({"attempt": index + 1, "ok": raw.get("ok"),
                             "error": raw.get("error"), "durationMs": raw.get("durationMs")})
            if raw.get("ok"):
                break
    finally:
        A.dump(PREFIX, "close", D.call(D.build_close_args(session)))
    value = raw.get("value") or {}
    text = value.get("text")
    if not raw.get("ok") or value.get("type") != "string" or not text:
        raise SystemExit("PCB netlist export failed: "
                         + json.dumps(raw.get("error") or value, ensure_ascii=False)[:500])
    NETLIST.write_bytes(text.encode("utf-8"))
    receipt = {
        "status": "PCB_NETLIST_EXPORT_JLCEDA",
        "attempted": "read-only: opened a copy, exported pcb_Net.getNetlist('JLCEDA'), never saved",
        "candidate": BOARD.relative_to(S.ROOT).as_posix(),
        "candidate_sha256": candidate_sha,
        "probe_copy_sha256": candidate_sha,
        "probe_copy_sha256_after": sha256(PROBE),
        "pcbUuid": value.get("pcbUuid"),
        "netlist_file": NETLIST.name,
        "netlist_sha256": hashlib.sha256(NETLIST.read_bytes()).hexdigest(),
        "netlist_chars": len(text),
        "netlist_lines": text.count("\n") + 1,
        "invoke_attempts": attempts,
        "not_erc_not_drc_not_fab": True,
    }
    RAW.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(run())
