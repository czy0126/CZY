// Export the native netlist the editor itself believes in, so it can be diffed
// against design/v3/pcb/board_netlist.csv.  Reconstructing nets from the wire
// primitives would test our own bookkeeping; the editor netlist tests the tool.
const f = await eda.sch_ManufactureData.getNetlistFile('main_board.net', 'EasyEDA');
if (!f) return { error: 'no netlist file returned' };
const j = JSON.parse(await f.text());
const comps = {};
for (const c of Object.values(j.components)) {
  const ref = c.props && c.props.Designator;
  if (!ref) continue;
  const nets = {};
  for (const [pad, info] of Object.entries(c.pinInfoMap || {})) {
    nets[pad] = info && info.net !== undefined ? info.net : null;
  }
  comps[ref] = nets;
}
return { refs: comps, netCount: j.nets ? Object.keys(j.nets).length : null };
