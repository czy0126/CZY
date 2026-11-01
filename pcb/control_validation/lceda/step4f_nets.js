const f = await eda.sch_ManufactureData.getNetlistFile('probe.net', 'EasyEDA');
const j = JSON.parse(await f.text());
return { top: Object.keys(j), comps: Object.keys(j.components), netKeys: j.nets ? Object.keys(j.nets) : null,
         nets: j.nets ? Object.entries(j.nets).map(([k, v]) => [k, JSON.stringify(v).slice(0, 300)]) : null };
