return await (async () => {
  let board;
  for(let i=0;i<20 && !board;i++) {
    const info=await eda.dmt_Project.getCurrentProjectInfo();
    board=info?.data?.find(b=>b?.pcb?.uuid);
    if(!board) await new Promise(r=>setTimeout(r,500));
  }
  if(!board) throw new Error('PCB missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r=>setTimeout(r,1000));
  const components=[],pads=[],seen=new Set();
  function pad(p,ref) {
    return {ref,X:p.getState_X(),Y:p.getState_Y(),Rotation:p.getState_Rotation(),
      Net:p.getState_Net(),PadNumber:p.getState_PadNumber(),Layer:p.getState_Layer(),Pad:p.getState_Pad()};
  }
  await Promise.all((await eda.pcb_PrimitiveComponent.getAll()).map(async c => {
    const ref=c.getState_Designator();
    components.push({ref,X:c.getState_X(),Y:c.getState_Y(),Rotation:c.getState_Rotation()});
    for(const p of await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId())) {
      seen.add(p.getState_PrimitiveId());pads.push(pad(p,ref));
    }
  }));
  for(const p of await eda.pcb_PrimitivePad.getAll()) if(!seen.has(p.getState_PrimitiveId())) pads.push(pad(p,null));
  return {components,pads,nets:await eda.pcb_Net.getAllNetsName(),
    polylines:(await eda.pcb_PrimitivePolyline.getAll()).length};
})();
