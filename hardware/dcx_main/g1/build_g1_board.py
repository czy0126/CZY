"""Rebuild the G1 native PCB from committed inputs.

The board was built by ``tmp_g1_probe/g1_build.py`` — an untracked scratch
directory.  That meant the placement of the 30 control parts (the A5 table only
places the power stage) existed nowhere in the repo, and neither did the slice
bodies that created the parts.  This module replaces it:

* ``g1_placement.json`` is the authored placement — one row per part on the
  board, derived once from the board's own readback and reviewed since;
* every slice body is a pure function of that file, the committed supplier
  inventory (``hardware/dcx_main/gen/native_inventory_raw.json``) and the
  committed netlist (``hardware/dcx_main/gen/netlist_export_raw.json``).

Commands::

    python build_g1_board.py --from-board     # regenerate g1_placement.json
    python build_g1_board.py --check          # placement vs readback, offline
    python build_g1_board.py --slices DIR     # write the JS bodies
    python build_g1_board.py --run SESSION    # run them against an open session

Coordinate frames, verified against live pad geometry (docs/agent/EDA.md):
``pcb_PrimitiveComponent.create`` takes Cartesian mil, Y *up*; polygon sources
for ``pcb_MathPolygon.createPolygon`` are SVG, Y *down*.  The placement file is
authored in mm from the top-left corner, Y *down* — the frame the A5 mechanical
table uses — so components are created at ``(x*MIL, -y*MIL)``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIL = 39.37007874015748

LEDA = Path(os.environ.get("LCEDA_PRO", r"D:\lceda-pro\lceda-pro.exe"))
DUMP = HERE / "g1_pads.json"
PLACEMENT = HERE / "g1_placement.json"
INVENTORY = ROOT / "hardware/dcx_main/gen/native_inventory_raw.json"
NETLIST = ROOT / "hardware/dcx_main/gen/netlist_export_raw.json"

#: Editor re-reads re-round positions; the audit uses the same 0.25 mil budget
#: (``audit_driver_eco.py``), so a legitimate reopen is never reported as a move.
TOL_MM = 0.25 / MIL
SLICE = 16


def _value(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def inventory() -> dict[str, dict]:
    """ref -> the schematic's own record (supplier part, component uuid)."""
    return {c["ref"]: c for c in _value(INVENTORY)["components"]}


def netlist() -> dict[str, dict[str, str]]:
    """ref -> {pin: net} as exported from the native schematic."""
    return _value(NETLIST)["refs"]


def placement_from_board(dump: dict, inv: dict[str, dict],
                         nets: dict[str, dict[str, str]]) -> list[dict]:
    """One row per component on the saved board, in ref order."""
    rows = []
    for c in sorted(dump["components"], key=lambda c: c["ref"]):
        ref = c["ref"]
        if ref not in inv:
            raise KeyError(f"{ref} is on the board but not in the inventory")
        rows.append({
            "ref": ref,
            "lcsc": inv[ref]["supplier_id"],
            "component_uuid": inv[ref]["component"]["uuid"],
            "x_mm": round(c["X"] / MIL, 4),
            "y_mm": round(-c["Y"] / MIL, 4),
            "rotation_deg": round(c.get("Rotation") or 0.0, 4),
            "nets": {k: v for k, v in nets[ref].items() if v},
        })
    return rows


def check_placement(rows: list[dict], dump: dict, inv: dict[str, dict],
                    nets: dict[str, dict[str, str]]) -> list[str]:
    """Every disagreement between the authored placement and the board/netlist."""
    problems: list[str] = []
    by_ref = {r["ref"]: r for r in rows}
    on_board = {c["ref"]: c for c in dump["components"]}
    problems += [f"missing part: {ref} is on the board but not in the placement"
                 for ref in sorted(set(on_board) - set(by_ref))]
    problems += [f"unexpected part: {ref} is placed but not on the board"
                 for ref in sorted(set(by_ref) - set(on_board))]
    for ref in sorted(set(by_ref) & set(on_board)):
        row, comp = by_ref[ref], on_board[ref]
        dx = abs(row["x_mm"] - comp["X"] / MIL)
        dy = abs(row["y_mm"] + comp["Y"] / MIL)
        if max(dx, dy) > TOL_MM:
            problems.append(f"{ref} moved: placement is {row['x_mm']},{row['y_mm']} mm, "
                            f"board reads {comp['X'] / MIL:.4f},{-comp['Y'] / MIL:.4f} mm")
        want = {k: v for k, v in nets.get(ref, {}).items() if v}
        if row["nets"] != want:
            problems.append(f"{ref} net table differs from the netlist: "
                            f"{row['nets']} != {want}")
        if ref not in inv:
            problems.append(f"{ref} has no inventory record")
        elif row["lcsc"] != inv[ref]["supplier_id"]:
            problems.append(f"{ref} supplier part is {row['lcsc']}, "
                            f"the schematic says {inv[ref]['supplier_id']}")
    return problems


def slice_js(chunk: list[tuple[str, dict]]) -> str:
    """One editor body that creates each part, sets its designator, wires its pads."""
    items = [{
        "ref": row["ref"],
        "lcsc": row["lcsc"],
        "x": round(row["x_mm"] * MIL, 3),
        "y": round(-row["y_mm"] * MIL, 3),
        "rot": row.get("rotation_deg") or 0.0,
        "nets": {k: v for k, v in row["nets"].items() if v},
    } for _, row in chunk]
    return """// G1 slice: create each part from its library device, set the designator and
// wire every pad whose netlist pin is not blank.  Generated by build_g1_board.py
// from g1_placement.json -- edit that file, not this one.
return await (async () => {
  const ITEMS = %s;
  let board = null;
  for (let i = 0; i < 20 && !board; i++) {
    const info = await eda.dmt_Project.getCurrentProjectInfo();
    board = info && info.data ? info.data.find((b) => b && b.pcb && b.pcb.uuid) : null;
    if (!board) await new Promise((r) => setTimeout(r, 1000));
  }
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise((r) => setTimeout(r, 1500));
  const sys = await eda.lib_LibrariesList.getSystemLibraryUuid();
  const out = [];
  for (const it of ITEMS) {
    const rec = { ref: it.ref };
    try {
      if (!it.lcsc) { rec.err = 'no lcsc'; out.push(rec); continue; }
      const hits = await eda.lib_Device.searchByProperties(
        { supplierId: it.lcsc }, undefined, undefined, undefined, 3, 1);
      if (!hits || !hits.length) { rec.err = 'no library hit'; out.push(rec); continue; }
      const c = await eda.pcb_PrimitiveComponent.create(
        { libraryUuid: sys, uuid: hits[0].uuid }, 1, it.x, it.y, it.rot, false);
      if (!c) { rec.err = 'create null'; out.push(rec); continue; }
      const id = c.getState_PrimitiveId();
      await eda.pcb_PrimitiveComponent.modify(id, { designator: it.ref });
      const pins = await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id);
      rec.pads = pins.map((p) => p.getState_PadNumber());
      rec.netted = {};
      for (const p of pins) {
        const num = p.getState_PadNumber();
        if (!(num in it.nets)) continue;
        await eda.pcb_PrimitivePad.modify(p.getState_PrimitiveId(), { net: it.nets[num] });
        rec.netted[num] = it.nets[num];
      }
      rec.missing = Object.keys(it.nets).filter((n) => !rec.pads.includes(n));
    } catch (e) { rec.err = String(e); }
    out.push(rec);
  }
  return out;
})();
""" % json.dumps(items, ensure_ascii=True)


def frame_js(dump: dict) -> str:
    """Board outline (layer 11), the core-body zones and the DOT marks (layer 13)."""
    zones = [{"ref": z["ref"], "x": z["x_mm"] * MIL, "y": z["y_mm"] * MIL,
              "w": z["w_mm"] * MIL, "d": z["d_mm"] * MIL} for z in dump["tbd_zones"]]
    dots = [{"x": d["x_mm"] * MIL, "y": d["y_mm"] * MIL, "s": d["size_mm"] * MIL}
            for d in dump["dot_marks"]]
    return """// Board outline (layer 11) plus the core-body zones and DOT marks (layer 13).
// Polygon sources are SVG (Y down), so these millimetre values are used as-is.
return await (async () => {
  const MIL = 39.37007874015748;
  const ZONES = %s;
  const DOTS = %s;
  let board = null;
  for (let i = 0; i < 20 && !board; i++) {
    const info = await eda.dmt_Project.getCurrentProjectInfo();
    board = info && info.data ? info.data.find((b) => b && b.pcb && b.pcb.uuid) : null;
    if (!board) await new Promise((r) => setTimeout(r, 1000));
  }
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise((r) => setTimeout(r, 1500));
  const out = { outline: null, zones: [], dots: [] };
  const W = %r, H = %r;
  try {
    const p = await eda.pcb_MathPolygon.createPolygon([0, 0, 'L', W, 0, 'L', W, H, 'L', 0, H]);
    const r = await eda.pcb_PrimitivePolyline.create('', 11, p, 10, false);
    out.outline = r ? 'ok' : 'null';
  } catch (e) { out.outlineErr = String(e); }
  for (const z of ZONES) {
    const x0 = z.x - z.w / 2, y0 = z.y - z.d / 2;
    const rec = { ref: z.ref };
    try {
      const p = await eda.pcb_MathPolygon.createPolygon(
        [x0, y0, 'L', x0 + z.w, y0, 'L', x0 + z.w, y0 + z.d, 'L', x0, y0 + z.d]);
      const r = await eda.pcb_PrimitivePolyline.create('', 13, p, 10, false);
      rec.ret = r ? 'ok' : 'null';
    } catch (e) { rec.err = String(e); }
    out.zones.push(rec);
  }
  for (const d of DOTS) {
    const x0 = d.x - d.s / 2, y0 = d.y - d.s / 2;
    const rec = { x: d.x, y: d.y };
    try {
      const p = await eda.pcb_MathPolygon.createPolygon(
        [x0, y0, 'L', x0 + d.s, y0, 'L', x0 + d.s, y0 + d.s, 'L', x0, y0 + d.s]);
      const r = await eda.pcb_PrimitivePolyline.create('', 13, p, 10, false);
      rec.ret = r ? 'ok' : 'null';
    } catch (e) { rec.err = String(e); }
    out.dots.push(rec);
  }
  try { out.saved = await eda.pcb_Document.save(); }
  catch (e) { out.saveErr = String(e); }
  return out;
})();
""" % (json.dumps(zones, ensure_ascii=True), json.dumps(dots, ensure_ascii=True),
       dump["board"]["w_mm"] * MIL, dump["board"]["d_mm"] * MIL)


def invoke(session: str, js: str, timeout_ms: int = 60000) -> dict:
    """Run one body, redirecting to files: the detached app keeps a pipe open forever."""
    args = [str(LEDA), "invoke", "--session", session, "--ext-uuid", "eda",
            "--timeout", str(timeout_ms), "--code", js]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(args, stdout=out, stderr=err)
        try:
            proc.wait(timeout=timeout_ms / 1000 + 60)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"ok": False, "error": "CLI_TIMEOUT"}
        out.seek(0)
        err.seek(0)
        text = out.read().decode("utf-8", errors="replace").strip() or \
            err.read().decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "raw": text[:2000]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-board", action="store_true",
                        help="regenerate g1_placement.json from the board readback")
    parser.add_argument("--check", action="store_true",
                        help="compare the placement file with the board and the netlist")
    parser.add_argument("--slices", type=Path, help="directory for the generated JS bodies")
    parser.add_argument("--run", metavar="SESSION", help="run the bodies against a session")
    args = parser.parse_args(argv)

    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    inv, nets = inventory(), netlist()

    if args.from_board:
        rows = placement_from_board(dump, inv, nets)
        PLACEMENT.write_text(json.dumps({
            "status": "AUTHORED_G1_PLACEMENT_FROM_BOARD_READBACK",
            "source": "g1_pads.json (pcb_PrimitiveComponent.getAll) + native_inventory_raw.json "
                      "+ netlist_export_raw.json",
            "frame": "mm from the top-left corner, Y down; the PCB stores mil, Y up",
            "board": dump["board"],
            "rows": rows,
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {PLACEMENT.name}: {len(rows)} parts")

    rows = json.loads(PLACEMENT.read_text(encoding="utf-8"))["rows"]

    if args.check:
        problems = check_placement(rows, dump, inv, nets)
        for p in problems:
            print(p)
        print(f"placement ok: {len(rows)} parts, 0 problems" if not problems
              else f"placement FAILED: {len(problems)} problems")
        if problems:
            return 1

    if args.slices:
        args.slices.mkdir(parents=True, exist_ok=True)
        pairs = [(r["ref"], r) for r in rows]
        for i in range(0, len(pairs), SLICE):
            path = args.slices / f"g1_{i // SLICE:02d}.js"
            path.write_text(slice_js(pairs[i:i + SLICE]), encoding="utf-8", newline="\n")
            print(f"{path} ({len(pairs[i:i + SLICE])} parts)")
        frame = args.slices / "g1_frame.js"
        frame.write_text(frame_js(dump), encoding="utf-8", newline="\n")
        print(f"{frame}")

    if args.run:
        names = sorted(args.slices.glob("g1_*.js")) if args.slices else []
        for path in names:
            print(f"== {path.name}")
            print(json.dumps(invoke(args.run, path.read_text(encoding="utf-8")))[:400])
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
