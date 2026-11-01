const comps = await eda.sch_PrimitiveComponent.getAll();
return comps.map((c) => ({ id: c.getState_PrimitiveId(), ref: c.getState_Designator() }));
