const ws = await eda.sch_PrimitiveWire.getAll();
return ws.map((w) => ({ id: w.getState_PrimitiveId(), net: w.getState_Net(), line: w.getState_Line() }));
