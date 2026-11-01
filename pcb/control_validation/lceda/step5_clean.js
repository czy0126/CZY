const comps = await eda.sch_PrimitiveComponent.getAll();
const ids = comps.filter((c) => c.getState_Designator()).map((c) => c.getState_PrimitiveId());
if (ids.length) await eda.sch_PrimitiveComponent.delete(ids);
const wires = await eda.sch_PrimitiveWire.getAll();
const wids = wires.map((w) => w.getState_PrimitiveId());
if (wids.length) await eda.sch_PrimitiveWire.delete(wids);
return { deletedComps: ids.length, deletedWires: wids.length };
