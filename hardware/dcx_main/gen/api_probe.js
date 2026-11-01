// Does the `eda` object answer for names that do not exist?
//
// `eda.sch_Drc.getCheckErrorList()` returned undefined instead of throwing a
// TypeError, and Object.keys(eda.sch_Drc) came back empty even though
// `eda.sch_Drc.check` works.  Either the API object is a proxy that stubs
// everything, or the members really are non-enumerable.  The difference decides
// how much weight an ERC result deserves: a stub returning a canned
// {type:'warn',count:5} is not evidence about the schematic at all.
const cand = ['check', 'getCheckErrorList', 'definitelyNotAnApi_9f3a', 'zzz'];
const probe = {};
for (const k of cand) {
  let t;
  try { t = typeof eda.sch_Drc[k]; } catch (e) { t = 'THREW ' + String(e); }
  probe[k] = t;
}

// Call the bogus one too: a stub that returns a non-undefined value without
// doing anything is proof the surface is generated, not real.
let bogusCall;
try { bogusCall = await eda.sch_Drc.definitelyNotAnApi_9f3a(1, 2, 3); }
catch (e) { bogusCall = 'THREW ' + String(e); }

const protoNames = (o) => {
  const out = [];
  let p = Object.getPrototypeOf(o);
  while (p && p !== Object.prototype) {
    out.push(...Object.getOwnPropertyNames(p));
    p = Object.getPrototypeOf(p);
  }
  return out;
};

return {
  types: probe,
  bogusCall: bogusCall === undefined ? '<undefined>' : JSON.stringify(bogusCall),
  ownNames: Object.getOwnPropertyNames(eda.sch_Drc || {}).slice(0, 40),
  protoNames: protoNames(eda.sch_Drc || {}).slice(0, 40),
  edaKeys: Object.keys(eda).slice(0, 60),
  drcToString: String(eda.sch_Drc),
};
