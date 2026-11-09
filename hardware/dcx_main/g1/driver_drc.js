return await (async () => {
  let board;
  for (let i = 0; i < 20 && !board; i++) {
    const info = await eda.dmt_Project.getCurrentProjectInfo();
    board = info?.data?.find(b => b?.pcb?.uuid);
    if (!board) await new Promise(r => setTimeout(r, 500));
  }
  if (!board) throw new Error('PCB missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 1000));
  let rule = null;
  try { rule = await eda.pcb_Drc.getCurrentRuleConfigurationName(); }
  catch (e) { rule = String(e && e.message || e); }
  const result = await eda.pcb_Drc.check(true, false, true);
  let raw;
  try { raw = JSON.parse(JSON.stringify(result)); }
  catch (e) { raw = String(result); }
  return { rule_config: rule, count: Array.isArray(raw) ? raw.length : null, raw };
})();
