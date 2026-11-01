// Last test of the ERC: an empty page must not report warnings.  If it still
// reports five, the histogram is canned and the CLI cannot be used to sign off
// electrical rules -- which is a finding about the tool, not about the board.
// The page is restored immediately afterwards by lceda_place_main_board --all.
const info = await eda.dmt_Project.getCurrentProjectInfo();
const sch = info.data[0].schematic;
await eda.dmt_EditorControl.openDocument(sch.page[0].uuid);
await new Promise((r) => setTimeout(r, 1500));

const comps = await eda.sch_PrimitiveComponent.getAll();
const wires = await eda.sch_PrimitiveWire.getAll();
const counts = { before: { comps: comps.length, wires: wires.length } };

const cids = comps.filter((c) => c.getState_Designator() || c.getState_ComponentType())
  .map((c) => c.getState_PrimitiveId());
const wids = wires.map((w) => w.getState_PrimitiveId());
if (wids.length) await eda.sch_PrimitiveWire.delete(wids);
if (cids.length) await eda.sch_PrimitiveComponent.delete(cids);
await new Promise((r) => setTimeout(r, 800));

counts.after = { comps: (await eda.sch_PrimitiveComponent.getAll()).length };
counts.emptyPageErc = JSON.stringify(await eda.sch_Drc.check(true, false, true));
return counts;
