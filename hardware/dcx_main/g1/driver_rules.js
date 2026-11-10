// Read the board's own design-rule configuration (read-only, no save).
// `pcb_Drc.getCurrentRuleConfiguration()` needs an open PCB document in the
// session; without it the call throws EXECUTION_ERROR "指定的参数信息在对应的会话中没有找到".
return await (async () => {
  const info = await eda.dmt_Project.getCurrentProjectInfo();
  const board = info?.data?.find(b => b?.pcb?.uuid);
  if (!board) throw new Error('PCB document missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 1000));
  return await eda.pcb_Drc.getCurrentRuleConfiguration();
})();
