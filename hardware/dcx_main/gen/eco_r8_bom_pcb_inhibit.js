// First executable power-board ECO, NOT a complete protection circuit.
//
// Scope: mark the hardwired U2.EN / RUN pull-up R8 as NOT POPULATED for both
// manufacturer BOM and PCB transfer. This is a transition-to-protected-design
// change: it makes the gate driver's default inhibit credible but does not
// provide an actual fail-safe HIGH permit. D1 still NOT_FOR_FAB.
//
// Run from a COPY of the original EasyEDA Pro .eprj2. The extension API is
// Beta and this script does not silently edit anything. Two phases, because
// this build makes them mutually exclusive (measurement 5 below):
//
//  1. VERIFY -- open a copy in a session whose five magnetic parts have had
//     their footprints injected in memory, and run this file with
//     CZY_R8_VERIFY_ONLY=true:
//       lceda-pro invoke --session <id> --ext-uuid eda --code \
//         "const CZY_R8_VERIFY_ONLY=true;$(cat \
//          hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js)"
//     It exports the native netlist, checks the pin map, returns
//     PIN_MAP_VERIFIED_NO_SAVE and NEVER mutates -- saving that session is
//     impossible anyway. Keep the returned `attestation` object.
//
//  2. APPLY -- open a fresh copy in a clean session (no injection) and run:
//       lceda-pro invoke --session <id> --ext-uuid eda --code \
//         "globalThis.CZY_APPLY_R8_DNP=true;globalThis.CZY_R8_PIN_MAP_VERIFIED=<attestation>; \
//          $(cat hardware/dcx_main/gen/eco_r8_bom_pcb_inhibit.js)"
//     A clean session cannot export (the five parts have no footprint), so the
//     pin map cannot be re-read here. The attestation is checked against this
//     session's live inventory and echoed in the result. The result then says
//     `pins_verified_in_a_different_session: true, pins_reverifiable_here:
//     false` -- say that, do not write "verified" unqualified.
//
// The flags are read from `globalThis`, not from bare identifiers, and the body
// below is wrapped in an async IIFE. Both are load-bearing: an invoke body's
// top-level `const`/`let` persist in the render's global scope, so a second
// invoke in the same session that re-declares ANY of these names dies with
// `SYNTAX_ERROR: Identifier 'info' has already been declared`. Measured here
// against tools/lceda_place_main_board.py, whose injection script also declares
// `info`/`board`. The wrapper keeps every declaration function-scoped; the body
// is deliberately not re-indented so the diff against the reviewed version
// stays readable.
//
// Once T1-T4 and CT have real footprints from vendor drawings, the export works
// in any session and one run does both phases.
//
// Run in a throwaway copy first. Real use MUST also visually verify GUI-BOM,
// transfer PCB BOM, updated native netlist and actual board gerber. R8 stays
// wired on the schematic -- DNP is an *assembly* condition, not a physical wire
// cut, and NOT a release approval.
//
// API references:
// https://prodocs.lceda.cn/cn/api/reference/pro-api.sch_primitivecomponent.modify.html
// https://prodocs.lceda.cn/cn/api/reference/pro-api.sch_primitivecomponent.getall.html
//
// Two identities are accepted, and the pair is checked the same way in
// read_native_inventory.js and value_eco.js:
//   * by studio uuid -- a project opened from the library carries the uuid
//     stored inside the .eprj2;
//   * by path name   -- opening the file with --path (the only supported way,
//     see CLAUDE.md) wraps it in a path-derived project whose uuid is NEW on
//     every open (f7433cc3..., 0054c1e0..., and another for a probe copy), so
//     the file stem is the only stable identity there.
// The stem is what the name route compares, so a rehearsal copy must still be
// named dcx_main_board.eprj2 inside its own directory; `_eco_probe4.eprj2` is
// refused (measured).
//
// Five measurements from 2026-11-06 shape the guards below. Each one refutes
// something this script previously assumed:
//
//  1. The native netlist has NO top-level `nets` map. A live export of the real
//     project is 252 408 characters with keys version / projectId /
//     components / designRule / differentialPair / netClass /
//     equalLengthNetGroup / differentialPairGroups. Connectivity lives in
//     components[*].pinInfoMap[pin].net. The old `!netlist.nets` test therefore
//     refused every real export; the gate is now `components` only.
//
//  2. Excluding a part RENUMBERS it in the export: with R8 excluded the same
//     part exports as designator R6, pins unchanged, Add into BOM "no",
//     Convert to PCB "no", other 82 designators unchanged, count still 83. The
//     renumber happens during the export, in memory. So an export that renames
//     the pull-up while live still says populated is a contradiction, not a
//     pin-map drift -- that is how it is reported now.
//
//  3. Pin->net exists ONLY in the export. `eda.sch_Net.getAllNetsName()`
//     returns 0 nets, `getNet('RUN')` returns null, `getState_Net()` is "" on
//     every component, and `getState_UniqueId()` is "" (so the export's
//     `Unique ID` cannot be joined back to a live part either). The pin guard
//     must read the export -- which is why the refusal has to be diagnostic.
//
//  4. getNetlistFile returns undefined while ANY placed part has an empty
//     footprint, for every netlist type (EasyEDA, JLCEDA, Protel2, PADS,
//     Allegro all measured). On this project exactly five parts are blank --
//     CT, T1, T2, T3, T4 -- enumerable live through getState_Footprint().uuid.
//     getBomFile keeps working (it returns an xlsx binary) but carries no pins.
//
//  5. The guard and the save are mutually exclusive in one session. Injecting
//     the five footprints unblocks the export but poisons the document:
//     sch_PrimitiveComponent.modify({otherProperty:{Footprint: uuid}}) puts an
//     unresolvable key on the instance and every later save() returns false.
//     Measured both ways on a copy of the real project: with injection the
//     export succeeds; without it, modify+save works and persists (2 355 200 ->
//     2 363 392 bytes, R8 reads back BOM=false PCB=false after reopen, save
//     returning in 14 ms). Hence the two phases above. The phase is a flag, not
//     an inference: a poisoned session shows footprints on all five parts too,
//     so "the export worked, therefore do not save" would invert the day the
//     vendor drawings arrive.
//
// A sixth measurement is the reason the two-phase attestation exists at all:
// `save()` is not slow (0.58 s on an idle document, 14 ms here) -- the
// "save exceeds the 60 s invoke cap" note in the older probe log was a wedged
// render, not a save.

return await (async () => {

const PROJECT_UUID = '14837d107b6a52feb21f43869dd7378616b33db49e6c75ae2ea6bc0a53989e46';
const PATH_OPENED_NAME = 'dcx_main_board';
// Read through globalThis so an operator prefix can set them without declaring
// a binding that a second invoke in the same render would collide with.
const APPLY = globalThis.CZY_APPLY_R8_DNP === true;
const VERIFY_ONLY = globalThis.CZY_R8_VERIFY_ONLY === true;
const ATTEST = globalThis.CZY_R8_PIN_MAP_VERIFIED || null;
const fail = (why, extra = {}) => ({ status: 'REFUSED', reason: why, applied: false, ...extra });

// Deterministic fingerprint of the live inventory. Not a MAC -- it exists to
// catch "the attestation came from a different board or a different part
// numbering", which no cryptographic property would improve on here (the
// render cannot read the attestation from a trusted channel anyway).
const fingerprint = (designators) => {
  let h = 2166136261;
  const text = designators.slice().sort().join(',');
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = (h * 16777619) >>> 0;
  }
  return 'fnv1a32:' + h.toString(16).padStart(8, '0') + ':n' + designators.length;
};

let info = null, board = null;
for (let i = 0; i < 20 && !board; i++) {
  info = await eda.dmt_Project.getCurrentProjectInfo();
  board = info && info.data ? info.data.find(
    b => b && b.schematic && b.schematic.page && b.schematic.page.length
  ) : null;
  if (!board) await new Promise(resolve => setTimeout(resolve, 1000));
}
if (!board) return fail('No active, loaded native EasyEDA project');
const byStudio = info.uuid === PROJECT_UUID;
const byPath = !!info.friendlyName && String(info.friendlyName) === PATH_OPENED_NAME;
const project = {
  name: info.friendlyName === undefined ? null : info.friendlyName,
  session_uuid: info.uuid === undefined ? null : info.uuid,
  stored_uuid: PROJECT_UUID,
  identified_by: byStudio ? 'studio_uuid' : (byPath ? 'path_name' : null)
};
if (!byStudio && !byPath) {
  return fail('Wrong project: refusing to modify somebody else\'s schematic',
              { expected_project: PROJECT_UUID, expected_path_opened_name: PATH_OPENED_NAME,
                actual_project: project.session_uuid, actual_name: project.name,
                hint: 'The path-opened identity is the FILE STEM, so a rehearsal copy must be '
                      + 'named ' + PATH_OPENED_NAME + '.eprj2 inside its own directory; '
                      + 'renaming it (e.g. _eco_probe4.eprj2) is refused by design.',
                project });
}
if (board.schematic.page.length !== 1) {
  return fail('Multiple schematic pages: update this script to audit all pages first');
}
await eda.dmt_EditorControl.openDocument(board.schematic.page[0].uuid);
await new Promise(resolve => setTimeout(resolve, 1600));

// Live state FIRST, and only through the captured primitive id afterwards: an
// export in this session can rename the part (measurement 2).
const live = await eda.sch_PrimitiveComponent.getAll();
const designators = live.map(c => (c.getState_Designator ? String(c.getState_Designator()) : ''));
const inventory = { parts: live.length, fingerprint: fingerprint(designators) };
const r8Live = live.filter(c => c.getState_Designator && c.getState_Designator() === 'R8');
if (r8Live.length !== 1) {
  return fail('Expected one live R8 primitive, found ' + r8Live.length, { inventory });
}
const id = r8Live[0].getState_PrimitiveId();
const before = {
  addIntoBom: r8Live[0].getState_AddIntoBom(),
  addIntoPcb: r8Live[0].getState_AddIntoPcb()
};
const blanks = live
  .filter(c => {
    const fp = c.getState_Footprint && c.getState_Footprint();
    return !fp || !fp.uuid;
  })
  .map(c => (c.getState_Designator ? String(c.getState_Designator()) : '(unnamed)'));
const base = { project, inventory, ref: 'R8', primitiveId: id, before };

// Idempotency first: whether the next run of this script is a no-op does not
// depend on being able to export, which a clean session cannot do.
if (before.addIntoBom === false && before.addIntoPcb === false) {
  return { ...base, status: 'ALREADY_DNP', applied: false, blocking_parts: blanks,
           warning: 'Assembly exclusion is already stored on the part. Still requires '
                    + 'independent GUI BOM / PCB export verification; NOT_FOR_FAB' };
}

const jf = await eda.sch_ManufactureData.getNetlistFile('before_r8_eco.net', 'EasyEDA');
if (!jf) {
  // No export means no pin guard in this session. Apply only against an
  // attestation from a VERIFY run whose live inventory this session reproduces.
  if (VERIFY_ONLY) {
    return fail('Phase 1 needs a session that can export, and this one cannot',
                { ...base, blocking_parts: blanks, blocking_parts_count: blanks.length,
                  remedy: 'inject the footprints in memory first: python '
                          + 'tools/lceda_place_main_board.py --netlist-ready --session <id> '
                          + '(that session must not be saved)',
                  release: 'NOT_FOR_FAB' });
  }
  if (!APPLY) {
    return fail('Native netlist export is blocked, so the pin guard cannot be verified',
                { ...base, blocking_parts: blanks, blocking_parts_count: blanks.length,
                  why: 'getNetlistFile() returns undefined while any placed part has an empty '
                       + 'footprint; measured for EasyEDA, JLCEDA, Protel2, PADS and Allegro',
                  remedy: 'phase 1 -- inject the footprints in memory in a session that will '
                          + 'never be saved: python tools/lceda_place_main_board.py '
                          + '--netlist-ready --session <id>, then run this file unchanged to '
                          + 'get the attestation; phase 2 -- open a fresh copy and run it with '
                          + 'CZY_APPLY_R8_DNP=true and CZY_R8_PIN_MAP_VERIFIED=<attestation>',
                  release: 'NOT_FOR_FAB' });
  }
  if (!ATTEST) {
    return fail('Cannot apply: this session cannot export a netlist and no pin-map attestation '
                + 'was supplied',
                { ...base, blocking_parts: blanks,
                  remedy: 'run phase 1 (PIN_MAP_VERIFIED_NO_SAVE) first, then pass its '
                          + 'attestation as CZY_R8_PIN_MAP_VERIFIED' });
  }
  if (ATTEST.parts !== inventory.parts || ATTEST.inventory_fingerprint !== inventory.fingerprint) {
    return fail('The pin-map attestation was taken from a different live inventory',
                { ...base, attestation_parts: ATTEST.parts,
                  attestation_fingerprint: ATTEST.inventory_fingerprint });
  }
  if (ATTEST.r8_designator !== 'R8') {
    return fail('The attestation was taken for a different designator',
                { ...base, attestation_designator: ATTEST.r8_designator });
  }
  return apply(before, { ...base, pins_verified_in_a_different_session: true,
                         pins_reverifiable_here: false,
                         pin_map_evidence: ATTEST.pins || null,
                         attestation_fingerprint: ATTEST.inventory_fingerprint });
}

const netlist = JSON.parse(await jf.text());
if (!netlist.components) return fail('Invalid native netlist: no components map', base);
const instances = Object.values(netlist.components);
const pads = c => Object.fromEntries(Object.entries(c.pinInfoMap || {}).map(
  ([k,v]) => [String(k), v && v.net === undefined ? null : (v && v.net)]
));
const props = c => (c && c.props) || {};
const byRef = ref => instances.filter(c => props(c).Designator === ref);
const want = (ref, expected) => {
  const list = byRef(ref);
  if (list.length !== 1) return 'Expected exactly one native '+ref+', found '+list.length;
  const actual = pads(list[0]);
  for (const [pin, net] of Object.entries(expected)) {
    if (actual[pin] !== net) return ref+'.'+pin+' expected '+net+', got '+actual[pin];
  }
  return null;
};
// R7 and U2 keep their designators, so they are still checked by name.
const neighbourError = want('R7', {'1':'RUN','2':'PGND'}) || want('U2', {'6':'RUN'});
if (neighbourError) return fail('Pre-ECO native pin map drift: '+neighbourError, base);

// The EN pull-up: the only two-pin part between VCC12 and RUN. Identified by
// PINS so that measurement 2 cannot hide it; the designator is then compared
// against the live one instead of being trusted.
const pullups = instances.filter(c => {
  const p = pads(c);
  return p['1'] === 'VCC12' && p['2'] === 'RUN';
});
if (pullups.length !== 1) {
  return fail('Expected exactly one VCC12/RUN two-pin part, found '+pullups.length, {
    ...base,
    candidates: pullups.map(c => ({ designator: props(c).Designator, pads: pads(c) }))
  });
}
const exportedDesignator = props(pullups[0]).Designator;
if (exportedDesignator !== 'R8' ||
    props(pullups[0])['Add into BOM'] !== 'yes' ||
    props(pullups[0])['Convert to PCB'] !== 'yes') {
  return fail('The export and the live part disagree about the EN pull-up; refusing to guess',
              { ...base, netlist_designator: exportedDesignator,
                netlist_addIntoBom: props(pullups[0])['Add into BOM'],
                netlist_addIntoPcb: props(pullups[0])['Convert to PCB'],
                why: 'an excluded part is renumbered in the export (measured R8 -> R6); if live '
                     + 'still says populated, either a prior save is still pending or the '
                     + 'schematic changed' });
}

const pins = {
  pullup: { designator: exportedDesignator, pads: pads(pullups[0]) },
  R7: pads(byRef('R7')[0]),
  'U2.6': pads(byRef('U2')[0])['6']
};
const evidence = { ...base, netlist_components: instances.length, pin_map: pins,
                   expected_pads: {'1':'VCC12','2':'RUN'} };

// The phase is DECLARED, not inferred. A poisoned (injected) session also shows
// footprints on the five magnetic parts, so "the export worked, therefore this
// document cannot be saved" is false the moment the vendor drawings land -- and
// an inference that inverts is worse than a flag the operator must type.
if (VERIFY_ONLY) {
  return {
    ...evidence,
    status: 'PIN_MAP_VERIFIED_NO_SAVE',
    applied: false,
    attestation: { parts: inventory.parts, inventory_fingerprint: inventory.fingerprint,
                   r8_designator: 'R8', pins },
    next: 'open a fresh copy in a clean session and rerun with CZY_APPLY_R8_DNP=true and '
          + 'CZY_R8_PIN_MAP_VERIFIED=<attestation>',
    release: 'NOT_FOR_FAB'
  };
}
if (!APPLY) {
  return { ...evidence, status: 'DRY_RUN_SAFE', applied: false,
           proposed: {addIntoBom:false,addIntoPcb:false}, release: 'NOT_FOR_FAB' };
}
return apply(before, { ...evidence, pins_verified_in_a_different_session: false,
                       pins_reverifiable_here: true });

async function apply(observedBefore, extra) {
  if (observedBefore.addIntoBom !== true || observedBefore.addIntoPcb !== true) {
    return fail('Partially excluded R8: do not guess what prior ECO did', extra);
  }
  const result = await eda.sch_PrimitiveComponent.modify(extra.primitiveId, {
    addIntoBom: false,
    addIntoPcb: false
  });
  if (!result) return fail('EDA did not confirm R8 modify operation', extra);
  const refreshed = await eda.sch_PrimitiveComponent.get(extra.primitiveId);
  if (!refreshed ||
      refreshed.getState_AddIntoBom() !== false ||
      refreshed.getState_AddIntoPcb() !== false) {
    return fail('R8 state did not read back as BOM+PCB excluded; DO NOT SAVE', extra);
  }
  const saved = await eda.sch_Document.save();
  if (!saved) {
    return fail('Document save failed; inspect the GUI, do not infer success',
                { ...extra,
                  hint: 'if this session had the five footprints injected in memory, saving is '
                        + 'impossible by construction -- run that session with '
                        + 'CZY_R8_VERIFY_ONLY=true instead, then apply the attestation here' });
  }
  return {
    ...extra,
    status: 'R8_ASSEMBLY_EXCLUSION_SAVED_NOT_VERIFIED',
    applied: true,
    after: {addIntoBom:false, addIntoPcb:false},
    warning: 'Save is debounced (~20 s); reopen the native file and independently export '
             + 'BOM/PCB before trusting it. R8 stays wired on the schematic: the exported '
             + 'netlist should carry Add into BOM=no / Convert to PCB=no. This is not a '
             + 'release approval.',
    release: 'NOT_FOR_FAB'
  };
}

})();
