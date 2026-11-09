// Run only in the independent driver-eco project copy, never the baseline.
return await (async () => {
  let board;
  for (let i=0;i<20 && !board;i++) {
    const info=await eda.dmt_Project.getCurrentProjectInfo();
    board=info?.data?.find(b=>b?.pcb?.uuid);
    if (!board) await new Promise(r=>setTimeout(r,500));
  }
  if (!board) throw new Error('PCB document missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r=>setTimeout(r,1000));
  const moves={U2:[54,62],C5:[51,60],D_BT:[47,62],C103:[57,65],C104:[57,67],R18:[49,55],R19:[58,55]};
  const comps=await eda.pcb_PrimitiveComponent.getAll();
  if(comps.length!==77) throw new Error('Unexpected PCB revision');
  const before=[];
  for (const c of comps) {
    const ref=c.getState_Designator();
    if (!moves[ref]) continue;
    before.push({ref,x:c.getState_X(),y:c.getState_Y()});
    const [x,y]=moves[ref];
    await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(),{x:x/0.0254,y:-y/0.0254});
  }
  if(before.length!==7) throw new Error('Missing ECO target');
  const saved=await eda.pcb_Document.save();
  return {before,moves,saved};
})();
