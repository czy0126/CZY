return await (async () => {
  let board;
  for (let i = 0; i < 20 && !board; i++) {
    const info = await eda.dmt_Project.getCurrentProjectInfo();
    board = info?.data?.find(b => b?.pcb?.uuid);
    if (!board) await new Promise(r => setTimeout(r, 500));
  }
  if (!board) throw new Error('PCB document missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 1000));
  const lines = [["GH_DRV", 9.843, 2066.89, -2460.591, 2007.874, -2460.591], ["GH_DRV", 9.843, 2007.874, -2460.591, 1935.984, -2388.701], ["GH_DRV", 9.843, 1935.984, -2388.701, 1935.984, -2263.819], ["GH", 7.874, 1995.315, -2263.819, 1995.315, -2216.535], ["GH", 7.874, 1995.315, -2216.535, 1899.488, -2216.535], ["GH", 7.874, 1899.488, -2216.535, 1899.488, -2165.394], ["GH", 7.874, 1995.315, -2216.535, 1931.102, -2216.535], ["GH", 7.874, 1931.102, -2216.535, 1931.102, -2110.236], ["GH", 7.874, 1931.102, -2110.236, 1939.685, -2099.685], ["GH", 7.874, 1939.685, -2099.685, 1939.685, -2076.811], ["GH", 7.874, 1939.685, -2076.811, 1964.685, -2076.811], ["GL_DRV", 9.843, 2185.0, -2401.614, 2244.094, -2401.614], ["GL_DRV", 9.843, 2244.094, -2401.614, 2290.315, -2355.394], ["GL_DRV", 9.843, 2290.315, -2355.394, 2290.315, -2263.819], ["GL", 7.874, 2349.606, -2263.819, 2349.606, -2216.535], ["GL", 7.874, 2349.606, -2216.535, 2253.819, -2216.535], ["GL", 7.874, 2253.819, -2216.535, 2253.819, -2165.394], ["GL", 7.874, 2349.606, -2216.535, 2285.433, -2216.535], ["GL", 7.874, 2285.433, -2216.535, 2285.433, -2110.236], ["GL", 7.874, 2285.433, -2110.236, 2294.016, -2099.685], ["GL", 7.874, 2294.016, -2099.685, 2294.016, -2076.811], ["GL", 7.874, 2294.016, -2076.811, 2319.016, -2076.811], ["HB", 11.811, 2066.89, -2440.906, 2039.37, -2440.906], ["HB", 11.811, 2039.37, -2440.906, 1980.315, -2381.85], ["HB", 11.811, 1980.315, -2381.85, 1980.315, -2362.205]];
  const out = { created: [], failed: [] };
  for (const [net, w, x1, y1, x2, y2] of lines) {
    try {
      const l = await eda.pcb_PrimitiveLine.create(net, 1, x1, y1, x2, y2, w, false);
      if (!l) { out.failed.push([net, x1, y1, x2, y2, 'null']); continue; }
      out.created.push([net, x1, y1, x2, y2, w,
                        l.getState_PrimitiveId ? l.getState_PrimitiveId() : null]);
    } catch (e) {
      out.failed.push([net, x1, y1, x2, y2, String(e && e.message || e)]);
    }
  }
  out.total = (await eda.pcb_PrimitiveLine.getAll()).length;
  out.saved = await eda.pcb_Document.save();
  return out;
})();
