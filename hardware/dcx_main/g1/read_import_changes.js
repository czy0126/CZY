// Read the editor's own schematic-vs-PCB netlist difference (Import Changes).
// Read-only: opens the two documents of the current board and calls the beta
// comparator; it never imports, modifies or saves anything.
//
// The parameter shape is probed explicitly: the reference says
// {projectUuid, documentUuid} while its own example passes bare document uuids,
// and this build returned `undefined` for the object form. Every attempt is
// recorded so the receipt shows what was asked, not only what worked.
return await (async () => {
  const out = { steps: [], attempts: [] };
  let info, board;
  for (let i = 0; i < 20 && !board; i++) {
    info = await eda.dmt_Project.getCurrentProjectInfo();
    board = (info && info.data || []).find(b => b && b.schematic && b.schematic.uuid && b.pcb && b.pcb.uuid);
    if (!board) await new Promise(r => setTimeout(r, 500));
  }
  if (!board) throw new Error('schematic/PCB pair missing');
  const projectUuid = info.uuid;
  const schUuid = board.schematic.uuid;
  const pcbUuid = board.pcb.uuid;
  out.board = { name: board.name, projectUuid, schUuid, pcbUuid };

  out.api_type = typeof (eda.sys_Tool && eda.sys_Tool.netlistComparison);
  try {
    const schNetlist = await eda.sch_Netlist.getNetlist('EasyEDA');
    out.sch_netlist = { type: typeof schNetlist,
                        length: typeof schNetlist === 'string' ? schNetlist.length : null };
  } catch (e) { out.sch_netlist = { error: String((e && e.message) || e) }; }

  await eda.dmt_EditorControl.openDocument(schUuid);
  await new Promise(r => setTimeout(r, 2500));
  out.steps.push('schematic open');
  await eda.dmt_EditorControl.openDocument(pcbUuid);
  await new Promise(r => setTimeout(r, 2500));
  out.steps.push('pcb open');

  function safe(v) {
    if (typeof v === 'undefined') return 'undefined';
    try {
      const plain = JSON.parse(JSON.stringify(v));
      return plain === undefined ? 'undefined' : plain;
    } catch (e) {
      return String(v);
    }
  }
  const forms = [
    ['bare uuids (documented example)', () => eda.sys_Tool.netlistComparison(schUuid, pcbUuid)],
    ['reversed (pcb, schematic)', () => eda.sys_Tool.netlistComparison(pcbUuid, schUuid)],
    ['schematic self-compare (control)', () => eda.sys_Tool.netlistComparison(schUuid, schUuid)],
    ['pcb self-compare (control)', () => eda.sys_Tool.netlistComparison(pcbUuid, pcbUuid)],
    ['project+document objects', () => eda.sys_Tool.netlistComparison(
      { projectUuid, documentUuid: schUuid }, { projectUuid, documentUuid: pcbUuid })]
  ];
  for (const [label, call] of forms) {
    const row = { label };
    try {
      const v = await call();
      row.value = safe(v);
      row.kind = Array.isArray(v) ? 'array' : typeof v;
      row.count = Array.isArray(v) ? v.length : null;
    } catch (e) {
      row.error = String((e && e.message) || e);
    }
    out.attempts.push(row);
  }
  const hit = out.attempts.find(a => a.kind === 'array');
  out.count = hit ? hit.count : null;
  out.diff = hit ? hit.value : null;
  out.api = 'eda.sys_Tool.netlistComparison(' + (hit ? hit.label : 'no successful form') + ')';
  return out;
})();
